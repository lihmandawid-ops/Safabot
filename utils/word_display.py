"""Renders a services.word_service.WordCard into the display text used by
both 📖 Словарь and ⭐ Мои слова (spec section 15) - kept in one place so
the two handlers never format a word card differently.
"""
from __future__ import annotations

from utils.i18n import t
from utils.languages import LANGUAGE_BY_CODE

_LANG = "ru"


def status_label(status: str) -> str:
    return t(f"card.status.{status}", _LANG)


_POS_WITH_LABEL = {
    "noun", "verb", "adjective", "adverb", "pronoun",
    "preposition", "conjunction", "article", "particle", "phrase",
}


def part_of_speech_label(part_of_speech: str | None) -> str | None:
    """None for "other"/unset - there's nothing meaningful to show the
    user for those, so the 📌 line is simply omitted (bugfix spec: word
    cards were missing part of speech entirely)."""
    if part_of_speech not in _POS_WITH_LABEL:
        return None
    return t("card.pos_line", _LANG, pos=t(f"card.pos.{part_of_speech}", _LANG))


def render_word_card_text(card, *, status: str | None = None) -> str:
    lang = LANGUAGE_BY_CODE.get(card.word.language_code)
    flag = lang.flag if lang else ""

    lines = [f"{flag} {card.word.word}"]

    pos_label = part_of_speech_label(card.word.part_of_speech)
    if pos_label is not None:
        lines.append(pos_label)

    if card.translations:
        translation_lang = LANGUAGE_BY_CODE.get(card.translations[0].language_code)
        t_flag = translation_lang.flag if translation_lang else ""
        joined = ", ".join(tr.translation for tr in card.translations)
        lines.append(f"{t_flag} {joined}")

    if status is not None:
        lines.append("")
        lines.append(status_label(status))

    lines.append("")
    if card.word.pronunciation:
        lines.append(t("card.pronunciation_line", _LANG, pronunciation=card.word.pronunciation))
    else:
        lines.append(t("card.pronunciation_placeholder", _LANG))

    lines.append("")
    if card.examples:
        example = card.examples[0]
        lines.append(t("card.example_label", _LANG))
        lines.append(example.example_text)
        if example.translation:
            lines.append(example.translation)
    else:
        lines.append(t("card.no_examples", _LANG))

    usage_notes = [tr.usage_note for tr in card.translations if tr.usage_note]
    if usage_notes:
        lines.append("")
        lines.append(t("card.usage_note", _LANG, note=usage_notes[0]))

    return "\n".join(lines)


def render_forms_text(card) -> str:
    if not card.forms:
        return t("card.no_forms", _LANG)
    lines = [t("card.forms_header", _LANG)]
    for form in card.forms:
        info = f" ({form.grammatical_info})" if form.grammatical_info else ""
        lines.append(f"  {form.form_type}: {form.form}{info}")
    return "\n".join(lines)
