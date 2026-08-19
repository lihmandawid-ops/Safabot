"""The 8 languages Safabot supports (spec section 2), in one place.

Both the database layer (language_code columns) and the keyboards module
import from here, so the supported-language list never has to be kept in
sync across files by hand.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name_ru: str
    flag: str


SUPPORTED_LANGUAGES: tuple[Language, ...] = (
    Language("en", "Английский", "🇬🇧"),
    Language("ru", "Русский", "🇷🇺"),
    Language("de", "Немецкий", "🇩🇪"),
    Language("he", "Иврит", "🇮🇱"),
    Language("es", "Испанский", "🇪🇸"),
    Language("fr", "Французский", "🇫🇷"),
    Language("it", "Итальянский", "🇮🇹"),
    Language("uk", "Украинский", "🇺🇦"),
)

LANGUAGE_BY_CODE: dict[str, Language] = {lang.code: lang for lang in SUPPORTED_LANGUAGES}


def is_supported(code: str) -> bool:
    return code in LANGUAGE_BY_CODE
