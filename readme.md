# telegram_groq_whisper_api_transcriber

Telegram bot to transcribe voice messages using the Groq Whisper API.

## Installation

pip3 install -r requirements.txt  
sudo apt install libmagic1

## Configuration & Running

1. Create a `.env` file with at least `TELEGRAM_TOKEN` and `GROQ_API_KEY` (see `.env.example` below). Optional: `BOT_NAME`, `SENTRY_DSN`, `GROQ_MODEL`.
2. Run with `python3 goodsecretarybot.py` or use the Docker helper script: `./run_bot.sh` (builds the image, stops/removes any old container, then starts a new one with your `.env`).

Поддерживаются голосовые, аудио и видео-заметки (кружки).

## Using Docker

1. Set `TELEGRAM_TOKEN` and `GROQ_API_KEY` in the `Dockerfile` or supply them at runtime with `--env-file .env`.
2. `docker build -t transcriber .`
3. `docker run --env-file .env transcriber`
