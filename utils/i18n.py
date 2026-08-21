"""Minimal localization system (spec section 6).

locales/ru.json plus real translations for the 8 languages onboarding
offers (see locales/*.json) - every user-facing string in handlers is
looked up through t(key, language) instead of being written inline, so
adding another language later is just dropping in a new
locales/<code>.json file, no handler code changes required.

Usage:
    t("onboarding.welcome", user.interface_language)
    t("settings.daily_words", user.interface_language, count=4)

settings-improvements stage, real root cause of "changing the interface
language does nothing anywhere except the settings screen itself":
every handler/keyboard module called t(key, _LANG) with _LANG a HARDCODED
module-level "ru" constant - user.interface_language was saved to the
database correctly, but nothing downstream ever read it back. Fixing that
by threading an explicit language argument through every keyboard
function and every handler call site would have meant touching every
call site's *signature*, not just its call - a much larger, riskier
diff. Instead, current_language() is a contextvars.ContextVar: each
Telegram update is handled in its own asyncio task, so set_current_language()
called once near the top of a handler (right after the user is loaded
from the database) is automatically visible to every t(key,
get_current_language(), ...) call made anywhere further down that same
call chain - including inside keyboard-builder functions several calls
deep - without passing it through every function signature by hand, and
without two concurrent users' requests ever seeing each other's language
(ContextVar values are per-task, never shared globally).
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from utils.logging import get_logger

logger = get_logger(__name__)

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
FALLBACK_LANGUAGE = "ru"

_current_language: ContextVar[str] = ContextVar("current_language", default=FALLBACK_LANGUAGE)


def set_current_language(language: str | None) -> None:
    """Call once per update, as soon as the user's row is loaded (e.g.
    right after users_repo.get_by_telegram_id) - every t() call made
    anywhere else during the handling of THIS update picks it up
    automatically. Falls back to FALLBACK_LANGUAGE for None/unknown so a
    user with no row yet (or a corrupted value) never crashes lookups."""
    _current_language.set(language or FALLBACK_LANGUAGE)


def get_current_language() -> str:
    return _current_language.get()


@lru_cache(maxsize=None)
def available_languages() -> tuple[str, ...]:
    """Every language with a real locales/<code>.json file - used by
    keyboards.main_menu.resolve_menu_action to recognize a persistent
    reply-keyboard button tap regardless of which language it was
    rendered in (a reply keyboard has no callback_data, only its literal
    label text, so routing has to work by scanning every known
    translation of each button, not just the user's current language)."""
    return tuple(sorted(p.stem for p in LOCALES_DIR.glob("*.json")))


@lru_cache(maxsize=None)
def _load_locale(language: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{language}.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def t(key: str, language: str = FALLBACK_LANGUAGE, **kwargs: object) -> str:
    """Look up `key` in `language`'s locale file, falling back to
    FALLBACK_LANGUAGE, then to the raw key itself so a missing
    translation is visible instead of crashing the bot."""
    catalog = _load_locale(language)
    template = catalog.get(key)

    if template is None and language != FALLBACK_LANGUAGE:
        template = _load_locale(FALLBACK_LANGUAGE).get(key)

    if template is None:
        logger.warning("Missing locale key %r for language %r", key, language)
        return key

    try:
        return template.format(**kwargs)
    except KeyError as exc:
        logger.warning("Missing placeholder %s for locale key %r", exc, key)
        return template
