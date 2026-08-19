"""Minimal localization system (spec section 6).

Only locales/ru.json exists today, but every user-facing string in
handlers is looked up through t(key, language) instead of being written
inline, so adding English/Deutsch/עברית/etc. later is just dropping in
new locales/<code>.json files - no handler code changes required.

Usage:
    t("onboarding.welcome", user.interface_language)
    t("settings.daily_words", user.interface_language, count=4)
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from utils.logging import get_logger

logger = get_logger(__name__)

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
FALLBACK_LANGUAGE = "ru"


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
