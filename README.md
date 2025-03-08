# Project Monitor Telegram Bot

A Telegram bot that monitors project status and issues using Sentry API and website accessibility checks. The bot uses Claude AI to provide intelligent responses about your projects' status.

## Features

- Asynchronous operation for better performance
- Authorization layer for secure access
- Integration with Sentry API for issue tracking
- Website accessibility monitoring
- AI-powered responses using Anthropic's Claude
- Docker support for easy deployment

## Setup

1. Clone this repository
2. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
3. Edit `.env` file with your credentials:
   - Get a Telegram bot token from [@BotFather](https://t.me/BotFather)
   - Get an Anthropic API key from [Anthropic](https://www.anthropic.com/)
   - Add your Sentry token and organization
   - Add authorized Telegram user IDs (comma-separated)
   - Add websites to monitor (comma-separated)

## Running with Docker

1. Build and start the container:
   ```bash
   docker-compose up -d
   ```

2. View logs:
   ```bash
   docker-compose logs -f
   ```

## Running without Docker

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the bot:
   ```bash
   python bot.py
   ```

## Usage

1. Start a chat with your bot on Telegram
2. Send the `/start` command to begin
3. Ask questions about your projects' status
4. The bot will check website accessibility and Sentry issues before responding

## Environment Variables

- `TELEGRAM_TOKEN`: Your Telegram bot token
- `ANTHROPIC_API_KEY`: Your Anthropic API key
- `SENTRY_TOKEN`: Your Sentry API token
- `SENTRY_ORG`: Your Sentry organization name
- `AUTHORIZED_USERS`: Comma-separated list of authorized Telegram user IDs
- `MONITORED_WEBSITES`: Comma-separated list of websites to monitor

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- Only share your bot with trusted users
- Regularly rotate API keys and tokens
- Monitor bot usage for any suspicious activity 