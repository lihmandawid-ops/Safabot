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


def language_display_name(lang: Language, language: str | None = None) -> str:
    """A language's name translated into `language` (the viewer's interface
    language), e.g. Language("de", ...) reads "German" for an English
    interface and "Немецкий" for a Russian one - settings-improvements
    stage section 2 requires every visible piece of UI, including language
    names themselves, to follow interface_language rather than always
    showing Russian. Defaults to the current per-update language (see
    utils.i18n.get_current_language) so most call sites don't need to
    thread a language value through just for this."""
    from utils.i18n import get_current_language, t

    return t(f"language.name.{lang.code}", language or get_current_language())
