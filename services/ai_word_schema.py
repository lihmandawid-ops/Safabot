"""Strict validation for AI-generated word data (bugfix spec: "невалидные
ответы AI никогда не должны попадать в базу"). Used by both
dictionary_service.py (single-word lookup fallback) and
word_generation_service.py (bulk generation) so the two features validate
AI output the same way instead of each parsing JSON by hand.

Nothing here calls an AI provider - it only turns a raw dict (already
returned by services/ai_service.py) into validated dataclasses, or
discards it. A malformed top-level shape yields an empty list; a
malformed individual word entry is skipped without discarding the rest of
an otherwise-valid batch.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_VALID_PARTS_OF_SPEECH = {
    "noun", "verb", "adjective", "adverb", "pronoun",
    "preposition", "conjunction", "article", "particle", "phrase", "other",
}
_VALID_DIFFICULTIES = {"beginner", "elementary", "intermediate", "upper_intermediate", "advanced"}


@dataclass
class ExampleEntry:
    text: str
    translation: str | None = None


@dataclass
class WordEntry:
    word: str
    translations: list[str] = field(default_factory=list)
    part_of_speech: str | None = None
    phonetic: str | None = None
    examples: list[ExampleEntry] = field(default_factory=list)
    difficulty: str | None = None
    category: str | None = None


def _clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def parse_word_entry(data: object) -> WordEntry | None:
    """Validate one word object. Returns None if `word` or every
    translation is missing/empty - those are the two fields nothing
    downstream can function without."""
    if not isinstance(data, dict):
        return None

    word = _clean_str(data.get("word"))
    if word is None:
        return None

    raw_translation = data.get("translation")
    if isinstance(raw_translation, str):
        translations = [t for t in [_clean_str(raw_translation)] if t]
    elif isinstance(raw_translation, list):
        translations = [t for t in (_clean_str(item) for item in raw_translation) if t]
    else:
        translations = []
    if not translations:
        return None

    part_of_speech = _clean_str(data.get("part_of_speech"))
    if part_of_speech is not None:
        part_of_speech = part_of_speech.lower()
        if part_of_speech not in _VALID_PARTS_OF_SPEECH:
            part_of_speech = None

    difficulty = _clean_str(data.get("difficulty"))
    if difficulty is not None:
        difficulty = difficulty.lower()
        if difficulty not in _VALID_DIFFICULTIES:
            difficulty = None

    examples: list[ExampleEntry] = []
    raw_examples = data.get("examples")
    if isinstance(raw_examples, list):
        for raw_example in raw_examples:
            if not isinstance(raw_example, dict):
                continue
            text = _clean_str(raw_example.get("text"))
            if text is None:
                continue
            examples.append(ExampleEntry(text=text, translation=_clean_str(raw_example.get("translation"))))

    return WordEntry(
        word=word,
        translations=translations,
        part_of_speech=part_of_speech,
        phonetic=_clean_str(data.get("phonetic")),
        examples=examples,
        difficulty=difficulty,
        category=_clean_str(data.get("category")),
    )


def parse_generation_response(raw: object) -> list[WordEntry]:
    """Validate a bulk-generation response shaped like
    {"words": [...]}. Any entry that fails parse_word_entry is silently
    dropped rather than discarding the whole batch - one bad entry from an
    otherwise-good AI response shouldn't cost the user every other word."""
    if not isinstance(raw, dict):
        return []
    raw_words = raw.get("words")
    if not isinstance(raw_words, list):
        return []
    parsed = [parse_word_entry(item) for item in raw_words]
    return [entry for entry in parsed if entry is not None]
