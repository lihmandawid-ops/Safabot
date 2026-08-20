"""📷 Разбор текста с фотографии / 🎤 Разбор голосовой записи (bugfix
spec sections 17-19).

Both share the same shape: download the Telegram file (utils/media.py),
run it through a dedicated recognition provider (services/ocr_service.py
or services/stt_service.py - never the configured AI chat model itself;
neither capability is documented as something it supports), then hand the
recognized text to handlers/text_analysis.py's existing handle_text_input
so translation, key-word extraction, and ⭐ Добавить все/выбранные reuse
the exact same, already-tested pipeline 📝 Разбор текста uses - never a
second implementation of "analyze text and offer to add words" (spec:
must use the existing UserWordService, no separate add system).

Registered in bot.py as content-type MessageHandlers (filters.PHOTO,
filters.VOICE | filters.AUDIO) - independent of context.user_data["mode"],
so a photo or voice message is recognized and processed no matter what
section the user was last in, the same way Telegram users expect to just
send a photo/voice note at any time.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import get_settings
from handlers import text_analysis as text_analysis_handler
from services.media_errors import OCRConfigurationError, OCRError, STTConfigurationError, STTError
from services.ocr_service import get_ocr_service
from services.stt_service import get_stt_service
from utils.i18n import t
from utils.logging import get_logger
from utils.media import MediaDownloadError, MediaTooLargeError, download_telegram_file

_LANG = "ru"
logger = get_logger(__name__)


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    photo = update.message.photo[-1]  # PhotoSize list is ordered smallest -> largest

    try:
        image_bytes = await download_telegram_file(
            context.bot, photo.file_id, max_size_bytes=settings.max_image_size_bytes
        )
    except MediaTooLargeError:
        await update.message.reply_text(t("media.photo_too_large", _LANG))
        return
    except MediaDownloadError as exc:
        logger.warning("Photo download failed: %s", exc)
        await update.message.reply_text(t("media.download_failed", _LANG))
        return

    try:
        text = await get_ocr_service().extract_text_from_image(
            image_bytes, mime_type="image/jpeg", user_id=update.effective_user.id
        )
    except OCRConfigurationError:
        await update.message.reply_text(t("media.ocr_not_configured", _LANG))
        return
    except OCRError as exc:
        logger.warning("OCR failed user_id=%s error=%s", update.effective_user.id, type(exc).__name__)
        await update.message.reply_text(t("media.ocr_failed", _LANG))
        return

    if not text.strip():
        await update.message.reply_text(t("media.ocr_empty", _LANG))
        return

    await update.message.reply_text(t("media.photo_recognized", _LANG, text=text))
    await text_analysis_handler.handle_text_input(update, context, text)


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    voice = update.message.voice or update.message.audio
    mime_type = voice.mime_type or "audio/ogg"
    filename = "voice.ogg" if update.message.voice else (getattr(voice, "file_name", None) or "audio.mp3")

    try:
        audio_bytes = await download_telegram_file(
            context.bot, voice.file_id, max_size_bytes=settings.max_audio_size_bytes
        )
    except MediaTooLargeError:
        await update.message.reply_text(t("media.audio_too_large", _LANG))
        return
    except MediaDownloadError as exc:
        logger.warning("Voice download failed: %s", exc)
        await update.message.reply_text(t("media.download_failed", _LANG))
        return

    try:
        text = await get_stt_service().transcribe_audio(
            audio_bytes, mime_type=mime_type, filename=filename, user_id=update.effective_user.id
        )
    except STTConfigurationError:
        await update.message.reply_text(t("media.stt_not_configured", _LANG))
        return
    except STTError as exc:
        logger.warning("Speech-to-text failed user_id=%s error=%s", update.effective_user.id, type(exc).__name__)
        await update.message.reply_text(t("media.stt_failed", _LANG))
        return

    if not text.strip():
        await update.message.reply_text(t("media.stt_empty", _LANG))
        return

    await update.message.reply_text(t("media.voice_recognized", _LANG, text=text))
    await text_analysis_handler.handle_text_input(update, context, text)


async def prompt_for_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📷 Разобрать фото main-menu button: just points the user at sending
    a photo - the actual processing (handle_photo_message) is wired to
    fire on any incoming photo regardless of menu state."""
    await update.message.reply_text(t("media.photo_prompt", _LANG))


async def prompt_for_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🎤 Разобрать голос main-menu button - same idea as prompt_for_photo."""
    await update.message.reply_text(t("media.voice_prompt", _LANG))
