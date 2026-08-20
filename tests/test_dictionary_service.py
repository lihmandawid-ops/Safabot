"""Tests for services/dictionary_service.py and services/ai_word_schema.py
(bugfix spec root cause #1: manual word add must never dead-end just
because the word isn't in the tiny local seed set).
"""
from __future__ import annotations

from database.repositories import words as words_repo
from services import ai_word_schema, dictionary_service, word_service
from services.dictionary_service import DictionaryProvider, WordData


class _FakeProvider(DictionaryProvider):
    def __init__(self, data: WordData | None):
        self._data = data
        self.calls: list[str] = []

    async def lookup(self, raw_word, *, language_code, translation_language):
        self.calls.append(raw_word)
        return self._data


async def test_lookup_word_returns_local_match_without_calling_provider(session, monkeypatch):
    await word_service.get_or_create_word(session, language_code="en", word="go")
    await session.commit()

    provider = _FakeProvider(WordData(word="should-not-be-used", translations=["x"]))
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="go"
    )
    assert [w.word for w in results] == ["go"]
    assert provider.calls == []  # local hit - provider never consulted


async def test_lookup_word_falls_back_to_provider_and_persists(session, monkeypatch):
    data = WordData(
        word="beautiful",
        translations=["красивый", "прекрасный"],
        part_of_speech="adjective",
        phonetic="BYOO-tuh-fuhl",
        examples=[ai_word_schema.ExampleEntry(text="What a beautiful day.", translation="Какой прекрасный день.")],
        difficulty="intermediate",
        category="other",
    )
    provider = _FakeProvider(data)
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="beautiful"
    )
    assert provider.calls == ["beautiful"]
    assert len(results) == 1
    word = results[0]
    assert word.word == "beautiful"
    assert word.part_of_speech == "adjective"
    assert {tr.translation for tr in word.translations} == {"красивый", "прекрасный"}
    assert word.examples[0].example_text == "What a beautiful day."

    # Persisted for real - a second lookup finds it locally, no provider call.
    provider.calls.clear()
    again = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="beautiful"
    )
    assert again[0].id == word.id
    assert provider.calls == []


async def test_lookup_word_returns_empty_when_provider_has_nothing(session, monkeypatch):
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: _FakeProvider(None))

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="zzzznotaword"
    )
    assert results == []


async def test_lookup_word_with_default_provider_and_unconfigured_ai_returns_empty(session):
    """AI_PROVIDER=none (this project's default) means AIDictionaryProvider
    hits NotConfiguredAIService's NotImplementedError - lookup_word must
    degrade to "nothing found", never raise."""
    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="zzzznotaword"
    )
    assert results == []


async def test_lookup_word_does_not_duplicate_when_provider_echoes_existing_word(session, monkeypatch):
    existing, _ = await word_service.get_or_create_word(session, language_code="en", word="cat")
    await session.commit()

    # Search for "cats" won't exact-match "cat" locally with the default
    # search (no plural stemming) - the provider is consulted and echoes
    # back "cat", which already exists.
    provider = _FakeProvider(WordData(word="cat", translations=["кошка"]))
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="cats"
    )
    assert len(results) == 1
    assert results[0].id == existing.id


def test_parse_word_entry_requires_word_and_translation():
    assert ai_word_schema.parse_word_entry({"word": "go"}) is None  # no translation
    assert ai_word_schema.parse_word_entry({"translation": "идти"}) is None  # no word
    assert ai_word_schema.parse_word_entry("not-a-dict") is None
    assert ai_word_schema.parse_word_entry({"word": "go", "translation": "идти"}) is not None


def test_parse_word_entry_accepts_translation_list_or_string():
    from_list = ai_word_schema.parse_word_entry({"word": "go", "translation": ["идти", "ехать"]})
    from_str = ai_word_schema.parse_word_entry({"word": "go", "translation": "идти"})
    assert from_list.translations == ["идти", "ехать"]
    assert from_str.translations == ["идти"]


def test_parse_word_entry_rejects_invalid_enum_values_but_keeps_the_rest():
    entry = ai_word_schema.parse_word_entry(
        {"word": "go", "translation": "идти", "part_of_speech": "not-a-real-pos", "difficulty": "expert"}
    )
    assert entry is not None
    assert entry.part_of_speech is None
    assert entry.difficulty is None


def test_parse_generation_response_requires_words_list():
    assert ai_word_schema.parse_generation_response({"not_words": []}) == []
    assert ai_word_schema.parse_generation_response("not-a-dict") == []
    assert ai_word_schema.parse_generation_response([1, 2, 3]) == []


def test_parse_generation_response_skips_bad_entries_keeps_good_ones():
    raw = {
        "words": [
            {"word": "go", "translation": "идти"},
            {"word": "no-translation"},
            "not-even-a-dict",
            {"word": "make", "translation": ["делать"]},
        ]
    }
    entries = ai_word_schema.parse_generation_response(raw)
    assert [e.word for e in entries] == ["go", "make"]
