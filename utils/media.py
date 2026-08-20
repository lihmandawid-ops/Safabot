"""Telegram file download helper for handlers/media.py (bugfix spec
section 19): every media handler needs the exact same fetch -> size
check -> temp file -> cleanup sequence, so it lives in exactly one place
instead of being duplicated between the photo and voice handlers.
"""
from __future__ import annotations

import os
import tempfile

from telegram import Bot
from telegram.error import TelegramError


class MediaTooLargeError(Exception):
    def __init__(self, size: int, max_size: int) -> None:
        self.size = size
        self.max_size = max_size
        super().__init__(f"File too large: {size} bytes (max {max_size})")


class MediaDownloadError(Exception):
    """Wraps any Telegram Bot API failure while fetching/downloading the
    file (spec section 19: never let a raw telegram.error.TelegramError
    reach the user)."""


async def download_telegram_file(bot: Bot, file_id: str, *, max_size_bytes: int, timeout: float = 30.0) -> bytes:
    """Downloads a Telegram file into memory via a short-lived temp file,
    always deleted before returning or raising - spec section 19: never
    leave temp files on the server, regardless of outcome.

    Raises MediaTooLargeError before downloading anything if Telegram
    already reports an oversized file (get_file's response includes
    file_size), and again after downloading as a defensive fallback for
    the (rare) case file_size was missing up front. Raises
    MediaDownloadError for any Telegram API failure (network error,
    expired file, etc).
    """
    try:
        tg_file = await bot.get_file(file_id, read_timeout=timeout)
    except TelegramError as exc:
        raise MediaDownloadError(f"Could not fetch file metadata: {exc}") from exc

    if tg_file.file_size and tg_file.file_size > max_size_bytes:
        raise MediaTooLargeError(tg_file.file_size, max_size_bytes)

    fd, path = tempfile.mkstemp(prefix="safabot_media_")
    os.close(fd)
    try:
        try:
            await tg_file.download_to_drive(path, read_timeout=timeout)
        except TelegramError as exc:
            raise MediaDownloadError(f"Could not download file: {exc}") from exc

        with open(path, "rb") as f:
            data = f.read()
        if len(data) > max_size_bytes:
            raise MediaTooLargeError(len(data), max_size_bytes)
        return data
    finally:
        if os.path.exists(path):
            os.remove(path)
