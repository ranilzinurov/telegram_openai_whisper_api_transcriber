from groq import Groq
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import asyncio
import io
import magic
import os
import aiosqlite
import time
import hashlib
import sentry_sdk
from dotenv import load_dotenv

MAX_MESSAGE_LENGTH = 4096
DB_PATH = "transcriptions.db"

load_dotenv()


def clean_env_str(value: str | None) -> str | None:
    """Normalize env strings that may be quoted or empty."""
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()
    return cleaned or None


telegram_token = clean_env_str(os.environ.get('TELEGRAM_TOKEN'))
bot_name = clean_env_str(os.environ.get('BOT_NAME'))
groq_api_key = clean_env_str(os.environ.get('GROQ_API_KEY'))
groq_model = clean_env_str(os.environ.get('GROQ_MODEL')) or 'whisper-large-v3'
sentry_dsn = clean_env_str(os.environ.get('SENTRY_DSN'))


async def init_db(_: Application) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS transcriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hashed_user_id TEXT,
                audio_duration INTEGER,
                transcription_time REAL,
                created_at TEXT
            )"""
        )
        await db.commit()


def resolve_audio_fields(message):
    if message.voice:
        return message.voice.file_id, message.voice.duration
    if message.audio:
        return message.audio.file_id, message.audio.duration
    if message.video_note:
        return message.video_note.file_id, message.video_note.duration
    return None, 0


async def transcribe_audio(file_data: io.BytesIO) -> str:
    return await asyncio.to_thread(
        client.audio.transcriptions.create,
        model=groq_model,
        file=file_data,
        response_format="text",
    )


async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text('Привет! Я распознаю голосовые сообщения. Вы кидаете мне голосовое, я в ответ возвращаю его текстовую версию. \n \nЕсть ограничение на максимальную длину голосового — около 40-80 минут в зависимости от того, как именно оно записано. Ещё мне можно прислать голосовую заметку из встроенного приложения айфона. \n \nРаспознавание занимает от пары секунд до пары десятков секунд, в зависимости от длины аудио. \n \nНичего не записываю и не храню.')


async def handle_voice(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    hashed_user_id = hashlib.sha256(str(update.message.from_user.id).encode()).hexdigest()
    sentry_sdk.set_user({"id": hashed_user_id})
    file_id, file_duration = resolve_audio_fields(update.message)
    placeholder_message = None

    try:
        placeholder_message = await update.message.reply_text(
            "Сейчас пришлю транскрипцию...",
            reply_to_message_id=update.message.message_id,
        )
        if not file_id:
            await placeholder_message.edit_text("Не могу понять тип аудио.")
            return
        file_handle = await context.bot.get_file(file_id)
        file_data = io.BytesIO()
        await file_handle.download_to_memory(file_data)
        file_data.seek(0)
        mime_type = magic.from_buffer(file_data.read(2048), mime=True)
        file_data.seek(0)
        extension = mime_type.split("/")[-1] if mime_type and "/" in mime_type else "bin"
        file_data.name = f"audio.{extension}"
        start_time = time.time()
        transcript = await transcribe_audio(file_data)
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
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO transcriptions (hashed_user_id, audio_duration, transcription_time, created_at) VALUES (?, ?, ?, ?)",
                             (hashed_user_id, file_duration, transcription_time, current_time))
            await db.commit()

    except Exception as e:
        error_text = f"Ошибочка: {e}"
        if "403" in str(e) and "Forbidden" in str(e):
            error_text += (
                "\nПохоже, нет доступа к Groq API. "
                "Проверь, что GROQ_API_KEY начинается с gsk_, "
                "ключ принадлежит проекту с доступом к модели, "
                "и .env/ENV подхватывается при запуске."
            )
        if placeholder_message:
            try:
                await placeholder_message.edit_text(error_text)
            except Exception:
                await update.message.reply_text(error_text, reply_to_message_id=update.message.message_id)
        else:
            await update.message.reply_text(error_text, reply_to_message_id=update.message.message_id)
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(DB_PATH) as db:
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
    if not telegram_token:
        raise RuntimeError("Missing TELEGRAM_TOKEN. Set it in the environment or .env.")
    if not groq_api_key:
        raise RuntimeError("Missing GROQ_API_KEY. Set it in the environment or .env.")
    if groq_api_key and not groq_api_key.startswith("gsk_"):
        print("Warning: GROQ_API_KEY does not look like a Groq key (expected gsk_...)", flush=True)
    application = Application.builder().token(telegram_token).post_init(init_db).build()

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
