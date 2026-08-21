"""Renders a services.word_service.WordCard into the display text used by
both 📖 Словарь and ⭐ Мои слова (spec section 15) - kept in one place so
the two handlers never format a word card differently.
"""
from __future__ import annotations

from utils.i18n import get_current_language, t
from utils.languages import LANGUAGE_BY_CODE


def status_label(status: str) -> str:
    return t(f"card.status.{status}", get_current_language())


def translation_for(user_word, translation_language: str) -> str | None:
    """The one translation to show for `user_word` in a single-line
    context (a numbered list row, a quiz question, a review card) - the
    user's current translation_language if the word has one in it,
    otherwise whichever translation happens to be first. None only when
    the word has no translations at all."""
    matches = [tr.translation for tr in user_word.word.translations if tr.language_code == translation_language]
    if matches:
        return matches[0]
    return user_word.word.translations[0].translation if user_word.word.translations else None


def format_pronunciation(word) -> str | None:
    """Latin-only transcription (global pronunciation rule, sections 35-36):
    Word.pronunciation is the readable Latin transliteration (e.g. "goh")
    and is always preferred/shown alone when present. Word.phonetic (IPA -
    e.g. "/ɡoʊ/") is shown only as a last-resort fallback when no readable
    pronunciation exists at all - IPA must never be the primary/default
    display. Returns None only when neither is set, so callers can show
    their own "not available yet" placeholder."""
    return word.pronunciation or word.phonetic


_POS_WITH_LABEL = {
    "noun", "verb", "adjective", "adverb", "pronoun",
    "preposition", "conjunction", "article", "particle", "phrase",
}


def part_of_speech_label(part_of_speech: str | None) -> str | None:
    """None for "other"/unset - there's nothing meaningful to show the
    user for those, so the part-of-speech section is simply omitted
    (bugfix spec: word cards were missing part of speech entirely)."""
    if part_of_speech not in _POS_WITH_LABEL:
        return None
    return t(f"card.pos.{part_of_speech}", get_current_language())


def render_word_card_text(card, *, status: str | None = None) -> str:
    """DeepSeek-integration spec section 6's exact card layout: word, one
    line per translation, then part of speech / pronunciation / meaning /
    example each as its own "label:\\nvalue" section, ending with the
    action buttons (keyboards.dictionary.word_card_keyboard)."""
    lang = LANGUAGE_BY_CODE.get(card.word.language_code)
    flag = lang.flag if lang else ""

    lines = [f"{flag} {card.word.word}"]

    if card.translations:
        translation_lang = LANGUAGE_BY_CODE.get(card.translations[0].language_code)
        t_flag = translation_lang.flag if translation_lang else ""
        lines.append("")
        lines.extend(f"{t_flag} {tr.translation}" for tr in card.translations)

    if status is not None:
        lines.append("")
        lines.append(status_label(status))

    pos_label = part_of_speech_label(card.word.part_of_speech)
    if pos_label is not None:
        lines.append("")
        lines.append(t("card.pos_header", get_current_language()))
        lines.append(pos_label)

    lines.append("")
    lines.append(t("card.pronunciation_header", get_current_language()))
    pronunciation = format_pronunciation(card.word)
    lines.append(pronunciation if pronunciation else t("card.no_pronunciation", get_current_language()))

    lines.append("")
    lines.append(t("card.definition_header", get_current_language()))
    lines.append(card.word.definition if card.word.definition else t("card.no_definition", get_current_language()))

    lines.append("")
    lines.append(t("card.example_label", get_current_language()))
    if card.examples:
        example = card.examples[0]
        lines.append(example.example_text)
        if example.translation:
            lines.append(example.translation)
    else:
        lines.append(t("card.no_examples", get_current_language()))

    usage_notes = [tr.usage_note for tr in card.translations if tr.usage_note]
    if usage_notes:
        lines.append("")
        lines.append(t("card.usage_note", get_current_language(), note=usage_notes[0]))

    return "\n".join(lines)


def render_forms_text(card) -> str:
    if not card.forms:
        return t("card.no_forms", get_current_language())
    lines = [t("card.forms_header", get_current_language())]
    for form in card.forms:
        info = f" ({form.grammatical_info})" if form.grammatical_info else ""
        lines.append(f"  {form.form_type}: {form.form}{info}")
    return "\n".join(lines)


# Telegram's hard cap is 4096 characters per message; a safety margin
# below that (repetition-system stage section 25: split into multiple
# messages rather than truncate or fall back to a popup).
_MAX_CONJUGATION_MESSAGE_CHARS = 3500


def _render_conjugated_form(item) -> str:
    """Word.verb_conjugation is a schema-less JSON column, so an entry
    cached before the global pronunciation rule (section 49) is still a
    plain form string, while a freshly generated one is a {"form":
    "pronunciation"} dict - handled per-item (not by branching on the
    whole table's shape) so even a table with a mix of old and new
    entries renders correctly."""
    if isinstance(item, dict):
        form = item.get("form", "")
        pronunciation = item.get("pronunciation")
        return f"{form} ({pronunciation})" if pronunciation else form
    return item


def render_conjugation_messages(word, conjugation: dict[str, list]) -> list[str]:
    """🔤 Все формы (sections 19-20, 25): one vertical block per tense/mood
    - a tense name header, then each conjugated form on its own line -
    rather than a person x tense table, which would either force every
    language into the same fixed set of persons or render far too wide
    for a phone screen. Split into several messages only when the whole
    table would exceed Telegram's length limit, always breaking between
    whole tense blocks so one is never cut in half."""
    lang = LANGUAGE_BY_CODE.get(word.language_code)
    flag = lang.flag if lang else ""
    header = f"{flag} {word.word}".strip()

    blocks = []
    for tense, forms in conjugation.items():
        lines = [f"{tense.strip().capitalize()}:"]
        lines.extend(_render_conjugated_form(item) for item in forms)
        blocks.append("\n".join(lines))

    messages: list[str] = []
    current = [header]
    current_len = len(header)
    for block in blocks:
        if current_len + len(block) + 2 > _MAX_CONJUGATION_MESSAGE_CHARS and len(current) > 1:
            messages.append("\n\n".join(current))
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len += len(block) + 2
    messages.append("\n\n".join(current))
    return messages
