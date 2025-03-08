import os
import logging
from typing import List, Optional, Dict
import aiohttp
import anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from datetime import datetime, timedelta
from collections import deque

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class Cache:
    """Simple in-memory cache with expiration."""

    def __init__(self, expiration_minutes: int = 5):
        self._cache = {}
        self._expiration_minutes = expiration_minutes

    def set(self, key: str, value: any) -> None:
        """Set a value in the cache with expiration time."""
        self._cache[key] = {
            "value": value,
            "expires_at": datetime.now() + timedelta(minutes=self._expiration_minutes),
        }

    def get(self, key: str) -> Optional[any]:
        """Get a value from the cache if it exists and hasn't expired."""
        if key not in self._cache:
            return None

        cache_data = self._cache[key]
        if datetime.now() > cache_data["expires_at"]:
            del self._cache[key]
            return None

        return cache_data["value"]

    def clear(self) -> None:
        """Clear all cached items."""
        self._cache.clear()


class ChatHistory:
    """Manages chat history for users with time-based expiration."""

    def __init__(self, max_messages: int = 5, expiry_hours: float = 1.0):
        self._histories: Dict[int, deque] = {}
        self._max_messages = max_messages
        self._expiry_hours = expiry_hours

    def _cleanup_old_messages(self, user_id: int) -> None:
        """Remove messages older than expiry time."""
        if user_id not in self._histories:
            return

        current_time = datetime.now()
        expiry_delta = timedelta(hours=self._expiry_hours)

        # Convert deque to list for filtering
        messages = list(self._histories[user_id])
        valid_messages = [
            msg
            for msg in messages
            if current_time - datetime.fromisoformat(msg["timestamp"]) <= expiry_delta
        ]

        if not valid_messages:
            # If all messages are expired, remove the user's history
            del self._histories[user_id]
        else:
            # Update with only valid messages
            self._histories[user_id] = deque(valid_messages, maxlen=self._max_messages)

    def add_message(self, user_id: int, message: str, response: str) -> None:
        """Add a message and its response to the user's history."""
        # Clean up old messages first
        self._cleanup_old_messages(user_id)

        if user_id not in self._histories:
            self._histories[user_id] = deque(maxlen=self._max_messages)

        self._histories[user_id].append(
            {
                "message": message,
                "response": response,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def get_history(self, user_id: int) -> List[Dict]:
        """Get the chat history for a user, removing expired messages first."""
        self._cleanup_old_messages(user_id)
        return list(self._histories.get(user_id, deque()))

    def clear_history(self, user_id: int) -> None:
        """Clear the chat history for a user."""
        if user_id in self._histories:
            del self._histories[user_id]

    def cleanup_all(self) -> None:
        """Clean up expired messages for all users."""
        for user_id in list(self._histories.keys()):
            self._cleanup_old_messages(user_id)


# Constants
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SENTRY_TOKEN = os.getenv("SENTRY_TOKEN")
SENTRY_ORG = os.getenv("SENTRY_ORG")
SENTRY_DOMAIN = os.getenv("SENTRY_DOMAIN", "sentry.io")
SENTRY_PROJECTS = [
    project.strip()
    for project in os.getenv("SENTRY_PROJECTS", "").split(",")
    if project.strip()
]
AUTHORIZED_USERS = [
    int(user_id.strip())
    for user_id in os.getenv("AUTHORIZED_USERS", "").split(",")
    if user_id.strip()
]
MONITORED_WEBSITES = os.getenv("MONITORED_WEBSITES", "").split(",")

# Initialize clients and storage
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
sentry_cache = Cache(expiration_minutes=5)
chat_history = ChatHistory(max_messages=5, expiry_hours=1.0)


async def check_auth(user_id: int) -> bool:
    """Check if user is authorized to use the bot."""
    return user_id in AUTHORIZED_USERS


async def check_website_status(url: str) -> dict:
    """Check if a website is accessible."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                return {
                    "url": url,
                    "status": response.status,
                    "accessible": response.status == 200,
                }
    except Exception as e:
        return {"url": url, "status": None, "accessible": False, "error": str(e)}


async def get_sentry_issues() -> List[dict]:
    """Fetch latest issues from Sentry API for specified projects with caching."""
    # Check cache first
    cached_issues = sentry_cache.get("sentry_issues")
    if cached_issues is not None:
        logger.info("Using cached Sentry issues")
        return cached_issues

    if not SENTRY_PROJECTS:
        logger.warning("No Sentry projects specified in environment variables")
        return []

    headers = {
        "Authorization": f"Bearer {SENTRY_TOKEN}",
        "Content-Type": "application/json",
    }

    all_issues = []
    async with aiohttp.ClientSession() as session:
        for project in SENTRY_PROJECTS:
            url = (
                f"https://{SENTRY_DOMAIN}/api/0/projects/{SENTRY_ORG}/{project}/issues/"
            )
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        issues = await response.json()
                        for issue in issues:
                            issue["project"] = project  # Add project info to each issue
                        all_issues.extend(issues)
                    else:
                        logger.error(
                            f"Failed to fetch Sentry issues for project {project}: {response.status}"
                        )
            except Exception as e:
                logger.error(f"Error fetching Sentry issues for project {project}: {e}")

    # Sort issues by date
    all_issues.sort(key=lambda x: x.get("lastSeen", ""), reverse=True)

    # Cache the results
    sentry_cache.set("sentry_issues", all_issues)
    logger.info("Cached new Sentry issues")

    return all_issues


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not await check_auth(update.effective_user.id):
        await update.message.reply_text(
            "Sorry, you are not authorized to use this bot."
        )
        return

    welcome_message = (
        "👋 Welcome to the Project Monitor Bot!\n\n"
        "I can help you monitor your projects and check their status. Here's what I can do:\n"
        "- Check website accessibility\n"
        "- Get latest Sentry issues from monitored projects\n"
        "- Answer questions about your projects\n\n"
        "Just ask me anything about your projects!"
    )
    await update.message.reply_text(welcome_message)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages and generate responses."""
    user_id = update.effective_user.id
    logger.info(f"Received message from user {user_id}: {update.message.text}")

    if not await check_auth(user_id):
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        await update.message.reply_text(
            "Sorry, you are not authorized to use this bot."
        )
        return

    # Clean up expired messages for all users periodically
    chat_history.cleanup_all()

    user_message = update.message.text
    logger.info(f"User {user_id} is authorized. Processing message: {user_message}")

    # Collect context information
    logger.info("Checking website status...")
    websites_status = [await check_website_status(url) for url in MONITORED_WEBSITES]
    logger.info(f"Website status collected: {websites_status}")

    logger.info("Fetching Sentry issues...")
    sentry_issues = await get_sentry_issues()
    logger.info(f"Fetched Sentry issues: {sentry_issues}")

    # Get chat history
    user_history = chat_history.get_history(user_id)
    logger.info("user history: " + str(user_history))
    history_context = "\nPrevious Conversation:\n"
    for entry in user_history:
        history_context += (
            f"User: {entry['message']}\nAssistant: {entry['response']}\n\n"
        )

    # Prepare context for Claude
    context_message = f"""
    User Query: {user_message}

    Current Status:
    Website Status: {websites_status}
    Latest Sentry Issues: {sentry_issues[:5] if sentry_issues[:5] else 'No issues found'}

    Projects being monitored: {', '.join(SENTRY_PROJECTS)}
    {history_context if user_history else ''}
    """
    logger.info("Preparing context message for Claude...")

    try:
        # Get response from Claude
        logger.info("Sending request to Claude...")
        response = anthropic_client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=1024,
            messages=[{"role": "user", "content": context_message}],
            system="You are a helpful assistant specializing in monitoring project status and issues. "
            "Analyze the provided website status and Sentry issues to give concise, relevant answers. "
            "make it so the formating parses right in markdown parsetype of telegram , also use appropriate emoji's"
            "Consider the conversation history when providing responses to maintain context."
            "make it so the culprit or reason is obvious for example 500 request in a subclient module",
        )

        # Extract the response text
        response_text = (
            response.content[0].text if response.content else "No response generated"
        )
        logger.info("Received response from Claude.")

        # Add message and response to chat history
        chat_history.add_message(user_id, user_message, response_text)

        # Send the response with markdown parsing
        await update.message.reply_text(response_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        await update.message.reply_text(
            "I apologize, but I encountered an error while processing your request. "
            "Please try again later."
        )


def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
