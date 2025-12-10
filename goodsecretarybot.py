from groq import Groq
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from urllib.parse import urlparse
import asyncio
import io
import magic
import os
import requests
import aiosqlite
import time
import hashlib
import sentry_sdk
import sqlite3
from dotenv import load_dotenv

MAX_MESSAGE_LENGTH = 4096

load_dotenv()


def clean_env_str(value: str | None) -> str | None:
    """Normalize env strings that may be quoted or empty."""
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    return cleaned or None


telegram_token = clean_env_str(os.environ.get('TELEGRAM_TOKEN'))
bot_name = clean_env_str(os.environ.get('BOT_NAME'))
groq_api_key = clean_env_str(os.environ.get('GROQ_API_KEY'))
groq_model = clean_env_str(os.environ.get('GROQ_MODEL')) or 'whisper-large-v3'
sentry_dsn = clean_env_str(os.environ.get('SENTRY_DSN'))

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text('Привет! Я распознаю голосовые сообщения. Вы кидаете мне голосовое, я в ответ возвращаю его текстовую версию. \n \nЕсть ограничение на максимальную длину голосового — около 40-80 минут в зависимости от того, как именно оно записано. Ещё мне можно прислать голосовую заметку из встроенного приложения айфона. \n \nРаспознавание занимает от пары секунд до пары десятков секунд, в зависимости от длины аудио. \n \nНичего не записываю и не храню.')


async def handle_voice(update: Update, context: CallbackContext) -> None:
    
    hashed_user_id = hashlib.sha256(str(update.message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    if update.message.voice:
        file_duration = update.message.voice.duration
    elif update.message.audio:
        file_duration = update.message.audio.duration
    elif update.message.video_note:
        file_duration = update.message.video_note.duration
    else:
        file_duration = 0
    placeholder_message = None

    try:
        placeholder_message = await update.message.reply_text(
            "Сейчас пришлю транскрипцию...",
            reply_to_message_id=update.message.message_id,
        )
        if update.message.voice:
            file_handle = await context.bot.get_file(update.message.voice.file_id)
        elif update.message.audio:
            file_handle = await context.bot.get_file(update.message.audio.file_id)
        elif update.message.video_note:
            file_handle = await context.bot.get_file(update.message.video_note.file_id)
        file_data = io.BytesIO()
        await file_handle.download_to_memory(file_data)
        file_data.seek(0)
        mime_type = magic.from_buffer(file_data.read(2048), mime=True)
        file_data.seek(0)
        extension = mime_type.split("/")[-1] if mime_type and "/" in mime_type else "bin"
        file_data.name = f"audio.{extension}"
        start_time = time.time()
        transcript = client.audio.transcriptions.create(
          model=groq_model,
          file=file_data,
          response_format="text",
        )
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        transcription_time = time.time() - start_time
        first_chunk = transcript[:MAX_MESSAGE_LENGTH]
        if placeholder_message:
            try:
                await placeholder_message.edit_text(first_chunk)
            except Exception:
                await update.message.reply_text(first_chunk, reply_to_message_id=update.message.message_id)
        else:
            await update.message.reply_text(first_chunk, reply_to_message_id=update.message.message_id)

        for i in range(MAX_MESSAGE_LENGTH, len(transcript), MAX_MESSAGE_LENGTH):
            await update.message.reply_text(transcript[i:i+MAX_MESSAGE_LENGTH], reply_to_message_id=update.message.message_id)

        print(f"{hashed_user_id}, {file_duration}, {transcription_time}", flush=True)
        async with aiosqlite.connect("transcriptions.db") as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS transcriptions (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                hashed_user_id TEXT,
                                audio_duration INTEGER,
                                transcription_time REAL,
                                created_at TEXT
                            )""")
            await db.execute("INSERT INTO transcriptions (hashed_user_id, audio_duration, transcription_time, created_at) VALUES (?, ?, ?, ?)",
                             (hashed_user_id, file_duration, transcription_time, current_time))
            await db.commit()

    except Exception as e:
        error_text = f"Ошибочка: {e}"
        if placeholder_message:
            try:
                await placeholder_message.edit_text(error_text)
            except Exception:
                await update.message.reply_text(error_text, reply_to_message_id=update.message.message_id)
        else:
            await update.message.reply_text(error_text, reply_to_message_id=update.message.message_id)
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect("transcriptions.db") as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS transcriptions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        hashed_user_id TEXT,
                        audio_duration INTEGER,
                        transcription_time REAL,
                        created_at TEXT        
                    )""")
            await db.execute("INSERT INTO transcriptions (hashed_user_id, audio_duration, transcription_time, created_at) VALUES (?, ?, ?, ?)",
                             (hashed_user_id, file_duration, -1, current_time))
            await db.commit()
        sentry_sdk.capture_exception(e)

async def handle_command(update: Update, context: CallbackContext) -> None:
    # If the bot is mentioned in a reply to a voice message
    if update.message.reply_to_message and (
        update.message.reply_to_message.voice
        or update.message.reply_to_message.audio
        or update.message.reply_to_message.video_note
    ):
        voice_message = update.message.reply_to_message
        voice_update = type('obj', (object,), {'message' : voice_message})
        await handle_voice(voice_update, context)

def main():
    application = Application.builder().token(telegram_token).build()

    start_handler = CommandHandler('start', start)
    voice_handler = MessageHandler(
        (filters.ChatType.PRIVATE | filters.ChatType.GROUPS)
        & (filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE),
        handle_voice,
    )
    text_handler = CommandHandler('text', handle_command)
    mention_handler = MessageHandler(filters.ChatType.GROUPS & filters.Mention(bot_name), handle_command)

    application.add_handler(start_handler)
    application.add_handler(voice_handler)
    application.add_handler(text_handler)
    application.add_handler(mention_handler)

    application.run_polling()

if __name__ == '__main__': 
    if not sentry_dsn:
        os.environ.pop("SENTRY_DSN", None)
    dsn_arg = sentry_dsn or None
    sentry_sdk.init(
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        traces_sample_rate=1.0,
        # Set profiles_sample_rate to 1.0 to profile 100%
        # of sampled transactions.
        # We recommend adjusting this value in production.
        profiles_sample_rate=1.0,
        dsn=dsn_arg,
    )
    client = Groq(api_key=groq_api_key)
    print("Bot started, polling Telegram...", flush=True)
    main()
