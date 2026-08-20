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


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


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
    ai_model: str
    ai_base_url: str | None
    ai_enabled: bool
    ai_timeout_seconds: float
    max_ai_retries: int
    ai_requests_per_minute: int
    ai_requests_per_day: int
    max_generation_attempts: int
    max_extra_words_per_day: int
    max_text_length: int
    max_image_size_bytes: int
    max_audio_size_bytes: int
    ocr_api_key: str | None
    ocr_enabled: bool
    ocr_provider: str
    ocr_model: str
    ocr_base_url: str | None
    stt_api_key: str | None
    stt_enabled: bool
    stt_provider: str
    stt_model: str
    stt_base_url: str | None
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
        # AI (services/ai_service.py): AI_API_KEY is the only thing that
        # actually gates whether AI features work - AI_ENABLED is an
        # explicit kill switch on top of that (section 27: AI_ENABLED=false
        # must keep the bot fully usable on the local database alone, e.g.
        # for offline development). Neither missing nor invalid AI config
        # may ever prevent the bot from starting - see get_ai_service().
        ai_provider=os.getenv("AI_PROVIDER", "none"),
        ai_api_key=os.getenv("AI_API_KEY") or None,
        ai_model=os.getenv("AI_MODEL", "gpt-4o-mini"),
        ai_base_url=os.getenv("AI_BASE_URL") or None,
        ai_enabled=_get_bool("AI_ENABLED", True),
        ai_timeout_seconds=_get_float("AI_TIMEOUT_SECONDS", 30.0),
        max_ai_retries=_get_int("MAX_AI_RETRIES", 2),
        ai_requests_per_minute=_get_int("AI_REQUESTS_PER_MINUTE", 5),
        ai_requests_per_day=_get_int("AI_REQUESTS_PER_DAY", 200),
        max_generation_attempts=_get_int("MAX_GENERATION_ATTEMPTS", 3),
        # Bugfix stage: "➕ Ещё новые слова" draws from a separate daily
        # pool than daily_new_words, precisely so an eager user can ask for
        # more today without silently raising everyone's default pace -
        # and so DeepSeek usage from repeated presses stays bounded.
        max_extra_words_per_day=_get_int("MAX_EXTRA_WORDS_PER_DAY", 20),
        # Cost control (section 22): caps on what gets sent to AI/media
        # providers, regardless of what a user pastes/uploads.
        max_text_length=_get_int("MAX_TEXT_LENGTH", 2000),
        max_image_size_bytes=_get_int("MAX_IMAGE_SIZE_BYTES", 10 * 1024 * 1024),
        max_audio_size_bytes=_get_int("MAX_AUDIO_SIZE_BYTES", 20 * 1024 * 1024),
        # OCR (services/ocr_service.py, bugfix spec section 17): DeepSeek's
        # chat model is not documented as vision-capable, so 📷 Разбор фото
        # never assumes it is - OCR_API_KEY/OCR_BASE_URL point at a
        # separate, independently-configurable vision endpoint. Same
        # never-block-startup rule as AI: missing config just means
        # get_ocr_service() hands back the "not configured" implementation.
        ocr_api_key=os.getenv("OCR_API_KEY") or None,
        ocr_enabled=_get_bool("OCR_ENABLED", True),
        ocr_provider=os.getenv("OCR_PROVIDER", "none"),
        ocr_model=os.getenv("OCR_MODEL", "gpt-4o-mini"),
        ocr_base_url=os.getenv("OCR_BASE_URL") or None,
        # Speech-to-text (services/stt_service.py, bugfix spec section 18):
        # same reasoning - DeepSeek does not do audio transcription, so
        # STT_API_KEY/STT_BASE_URL point at a separate Whisper-style
        # endpoint, independently configurable and optional.
        stt_api_key=os.getenv("STT_API_KEY") or None,
        stt_enabled=_get_bool("STT_ENABLED", True),
        stt_provider=os.getenv("STT_PROVIDER", "none"),
        stt_model=os.getenv("STT_MODEL", "whisper-1"),
        stt_base_url=os.getenv("STT_BASE_URL") or None,
    )
