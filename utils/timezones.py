"""Curated timezone choices for onboarding (spec section 9) and Settings
(bugfix stage: ⚙️ Настройки → 🌍 Часовой пояс).

The Telegram Bot API does not expose a user's timezone directly, so we
offer a short, understandable list instead of free-text IANA names -
one representative city per supported language's main region, plus UTC -
backed by a "🔎 Другой часовой пояс" free-text search (search_timezones)
over the real IANA database (zoneinfo) for anyone not covered by the
curated list. Notifications convert each user's stored IANA name to their
local day using this value (utils/time.py's local_day_bounds).
"""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import available_timezones


@dataclass(frozen=True)
class TimezoneChoice:
    iana_name: str
    label: str


TIMEZONE_CHOICES: tuple[TimezoneChoice, ...] = (
    TimezoneChoice("Asia/Jerusalem", "🇮🇱 Израиль (Иерусалим)"),
    TimezoneChoice("Europe/Moscow", "🇷🇺 Москва"),
    TimezoneChoice("Europe/Kyiv", "🇺🇦 Киев"),
    TimezoneChoice("Europe/Berlin", "🇩🇪 Берлин"),
    TimezoneChoice("Europe/London", "🇬🇧 Лондон"),
    TimezoneChoice("America/New_York", "🇺🇸 Нью-Йорк"),
    TimezoneChoice("Europe/Madrid", "🇪🇸 Мадрид"),
    TimezoneChoice("Europe/Paris", "🇫🇷 Париж"),
    TimezoneChoice("Europe/Rome", "🇮🇹 Рим"),
    TimezoneChoice("UTC", "🌍 UTC"),
)

TIMEZONE_BY_NAME: dict[str, TimezoneChoice] = {tz.iana_name: tz for tz in TIMEZONE_CHOICES}

# Real IANA database (stdlib zoneinfo, no network/third-party dependency) -
# loaded once at import time since available_timezones() does a directory
# scan; the set itself never changes within a running process.
_ALL_IANA_TIMEZONES: frozenset[str] = frozenset(available_timezones())


def is_valid_timezone(iana_name: str) -> bool:
    """True for anything the system's real tz database recognizes, not
    just the curated shortlist above - so a "🔎 Другой часовой пояс"
    search result (or a directly-typed exact IANA name) validates too."""
    return iana_name in _ALL_IANA_TIMEZONES


def search_timezones(query: str, *, limit: int = 8) -> list[str]:
    """Case/underscore-insensitive substring search over every real IANA
    zone name (e.g. "tel aviv" -> "Asia/Jerusalem" only matches if the
    zone name itself contains it - most cities are covered by a handful
    of regional zones, e.g. "new york" -> "America/New_York"). Returns
    at most `limit` names, shortest/most-canonical-looking first so
    "Europe/Paris" outranks "America/Indiana/Indianapolis"-style deep
    aliases for an ambiguous query.
    """
    normalized = query.strip().lower().replace(" ", "_")
    if not normalized:
        return []
    matches = [name for name in _ALL_IANA_TIMEZONES if normalized in name.lower()]
    matches.sort(key=lambda name: (len(name), name))
    return matches[:limit]
