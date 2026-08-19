"""Curated timezone choices for onboarding (spec section 9).

The Telegram Bot API does not expose a user's timezone directly, so we
offer a short, understandable list instead of free-text IANA names -
one representative city per supported language's main region, plus UTC.
Notifications (a later stage) convert each user's stored IANA name to UTC
using this value.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimezoneChoice:
    iana_name: str
    label: str


TIMEZONE_CHOICES: tuple[TimezoneChoice, ...] = (
    TimezoneChoice("Europe/Moscow", "🇷🇺 Москва"),
    TimezoneChoice("Europe/Kyiv", "🇺🇦 Киев"),
    TimezoneChoice("Europe/London", "🇬🇧 Лондон"),
    TimezoneChoice("Europe/Berlin", "🇩🇪 Берлин"),
    TimezoneChoice("Europe/Madrid", "🇪🇸 Мадрид"),
    TimezoneChoice("Europe/Paris", "🇫🇷 Париж"),
    TimezoneChoice("Europe/Rome", "🇮🇹 Рим"),
    TimezoneChoice("Asia/Jerusalem", "🇮🇱 Иерусалим"),
    TimezoneChoice("UTC", "🌍 UTC"),
)

TIMEZONE_BY_NAME: dict[str, TimezoneChoice] = {tz.iana_name: tz for tz in TIMEZONE_CHOICES}


def is_valid_timezone(iana_name: str) -> bool:
    return iana_name in TIMEZONE_BY_NAME
