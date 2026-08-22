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
    gemini_api_key: str | None
    gemini_model: str
    gemini_text_model: str | None
    gemini_multimodal_model: str | None
    gemini_base_url: str | None
    gemini_enabled: bool
    gemini_proxy_url: str | None
    ai_gateway_api_key: str | None
    ai_gateway_model: str
    ai_gateway_base_url: str
    ai_gateway_enabled: bool
    max_generation_attempts: int
    # LevelProgressService thresholds (level-and-difficulty stage) - a
    # learner's estimated CEFR level only advances one tier when ALL
    # three hold, never from elapsed time or a handful of lucky answers:
    # enough distinct words at the CURRENT level genuinely mastered, each
    # one reviewed enough times to rule out a fluke, and a high enough
    # aggregate accuracy across all of them.
    level_up_min_mastered_words: int
    level_up_min_repetitions_per_word: int
    level_up_min_accuracy: float
    max_extra_words_per_day: int
    max_text_length: int
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
        # Google Gemini (services/gemini_provider.py): the PRIMARY AI
        # provider when configured - AI_API_KEY (DeepSeek by default)
        # becomes its text-only FALLBACK instead of disappearing (see
        # services/ai_service.py's get_ai_service()). Same never-block-
        # startup rule as AI_*: missing GEMINI_API_KEY just means Safabot
        # runs on DeepSeek alone (or the local database), exactly like
        # before this integration existed.
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        # "-latest" aliases (per Gemini API docs) always point at the
        # newest release of that model family, so this stays "the actual
        # current model" without editing config on every Gemini release -
        # pin an exact version instead (e.g. gemini-2.5-flash) if stability
        # across silent model upgrades matters more than always-newest.
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
        # Optional per-capability overrides (spec: split text vs
        # image/audio only if that's actually beneficial) - both fall back
        # to GEMINI_MODEL when unset, so the common case is one setting.
        gemini_text_model=os.getenv("GEMINI_TEXT_MODEL") or None,
        gemini_multimodal_model=os.getenv("GEMINI_MULTIMODAL_MODEL") or None,
        gemini_base_url=os.getenv("GEMINI_BASE_URL") or None,
        gemini_enabled=_get_bool("GEMINI_ENABLED", True),
        # Some regions are not served by the Gemini Developer API at all
        # ("User location is not supported for the API use") - set this to
        # route ONLY Gemini's own HTTP requests through a forward proxy
        # sitting in a supported region, without touching DeepSeek/
        # Telegram/OCR-legacy traffic, which never sees this setting.
        # Standard proxy URL form: http://user:pass@host:port.
        gemini_proxy_url=os.getenv("GEMINI_PROXY_URL") or None,
        # Vercel AI Gateway (https://vercel.com/docs/ai-gateway): an
        # OpenAI-Chat-Completions-compatible endpoint that routes to
        # Gemini (and other providers) from Vercel's own infrastructure -
        # useful when the server's own region is blocked from calling
        # Gemini directly ("User location is not supported for the API
        # use"). Reuses services.ai_provider.HttpAIProvider unchanged
        # (same transport already used for DeepSeek) - no new provider
        # class needed. When configured, this becomes the HIGHEST-priority
        # text provider, ahead of direct Gemini and DeepSeek.
        ai_gateway_api_key=os.getenv("AI_GATEWAY_API_KEY") or None,
        # google/<model> naming (Vercel's own catalog convention) - the
        # full current list is public, unauthenticated:
        # curl https://ai-gateway.vercel.sh/v1/models
        ai_gateway_model=os.getenv("AI_GATEWAY_MODEL", "google/gemini-2.5-flash"),
        ai_gateway_base_url=os.getenv("AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1"),
        ai_gateway_enabled=_get_bool("AI_GATEWAY_ENABLED", True),
        max_generation_attempts=_get_int("MAX_GENERATION_ATTEMPTS", 3),
        # Deliberately conservative defaults (spec: never advance a level
        # from a handful of correct answers or from time passing alone) -
        # 15 distinct words genuinely mastered at the current level, each
        # reviewed at least 3 times, at 85%+ aggregate accuracy.
        level_up_min_mastered_words=_get_int("LEVEL_UP_MIN_MASTERED_WORDS", 15),
        level_up_min_repetitions_per_word=_get_int("LEVEL_UP_MIN_REPETITIONS_PER_WORD", 3),
        level_up_min_accuracy=_get_float("LEVEL_UP_MIN_ACCURACY", 0.85),
        # Bugfix stage: "➕ Ещё новые слова" draws from a separate daily
        # pool than daily_new_words, precisely so an eager user can ask for
        # more today without silently raising everyone's default pace -
        # and so DeepSeek usage from repeated presses stays bounded.
        max_extra_words_per_day=_get_int("MAX_EXTRA_WORDS_PER_DAY", 20),
        # Cost control (section 22): a cap on what gets sent to AI
        # providers, regardless of what a user pastes.
        max_text_length=_get_int("MAX_TEXT_LENGTH", 2000),
    )
