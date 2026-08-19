"""Central configuration for Safabot.

Loads settings from environment variables (via .env, see .env.example) and
exposes them as a single, typed Settings object. Nothing in this module
talks to Telegram, the database, or any external API - it only reads config.

Section 26 of the spec requires PRO/FREE feature limits to live in
configuration rather than being hardcoded in handlers; PlanLimits is that
single source of truth.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass(frozen=True)
class PlanLimits:
    """Feature limits per subscription plan (spec section 26).

    Services and handlers must read limits from here instead of hardcoding
    numbers, so pricing/limit changes never require touching handler code.
    """

    daily_new_words_options: tuple[int, ...] = (2, 4, 8)
    free_daily_new_words_max: int = 4
    free_max_languages: int = 1
    pro_daily_new_words_max: int = 8
    pro_max_languages: int = 8
    free_ai_enabled: bool = False
    free_ocr_enabled: bool = False
    free_voice_enabled: bool = False


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    log_level: str
    default_timezone: str
    trial_days: int
    default_daily_new_words: int
    max_daily_reviews: int
    default_morning_time: str
    default_afternoon_time: str
    default_evening_time: str
    ai_provider: str
    ai_api_key: str | None
    ocr_api_key: str | None
    plan_limits: PlanLimits = field(default_factory=PlanLimits)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build (and cache) the Settings object from the current environment.

    bot_token is intentionally allowed to be empty here - callers that
    actually need to talk to Telegram (bot.py) validate it themselves so
    that tests and tooling can import this module without a real token.
    """
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        database_url=os.getenv(
            "DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR / 'safabot.db'}"
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC"),
        trial_days=_get_int("TRIAL_DAYS", 7),
        default_daily_new_words=_get_int("DEFAULT_DAILY_NEW_WORDS", 4),
        # Section 8 of the learning-core stage: cap how many overdue
        # reviews get queued into one session, so a user who skipped a
        # week never gets buried under hundreds of due words at once.
        max_daily_reviews=_get_int("MAX_DAILY_REVIEWS", 30),
        default_morning_time=os.getenv("DEFAULT_MORNING_TIME", "09:00"),
        default_afternoon_time=os.getenv("DEFAULT_AFTERNOON_TIME", "14:00"),
        default_evening_time=os.getenv("DEFAULT_EVENING_TIME", "20:00"),
        ai_provider=os.getenv("AI_PROVIDER", "none"),
        ai_api_key=os.getenv("AI_API_KEY") or None,
        ocr_api_key=os.getenv("OCR_API_KEY") or None,
    )
