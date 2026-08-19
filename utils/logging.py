"""Logging setup (spec section 29).

Logs bot startup, handler errors and API/scheduler failures. Never logs the
bot token, API keys, payment secrets, or raw user content - callers must
pass only safe, already-redacted context into log messages.
"""
from __future__ import annotations

import logging

from config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Configure root logging once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = get_settings().log_level.upper()
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=level,
    )
    # httpx (used internally by python-telegram-bot) is noisy at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
