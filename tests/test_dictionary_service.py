"""Tests for services/dictionary_service.py (bugfix spec root cause #1 +
AI-integration spec section 7): local dictionary first, AI as fallback,
cached (never re-asks AI for a word already persisted).
"""
from __future__ import annotations

from services import ai_models, dictionary_service, word_service
from services.ai_errors import AIConfigurationError
from services.dictionary_service import DictionaryProvider


class _FakeProvider(DictionaryProvider):
    def __init__(self, data: ai_models.GeneratedWord | None = None, *, raises: Exception | None = None):
        self._data = data
        self._raises = raises
        self.calls: list[str] = []

    async def lookup(self, raw_word, *, language_code, translation_language, user_level, user_id):
        self.calls.append(raw_word)
        if self._raises is not None:
            raise self._raises
        return self._data


def _word(word: str, **kwargs) -> ai_models.GeneratedWord:
    kwargs.setdefault("translations", [ai_models.TranslationResult(translation="перевод")])
    return ai_models.GeneratedWord(word=word, **kwargs)


async def test_lookup_word_returns_local_match_without_calling_provider(session, monkeypatch):
    await word_service.get_or_create_word(session, language_code="en", word="go")
    await session.commit()

    provider = _FakeProvider(_word("should-not-be-used"))
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="go", user_id=1
    )
    assert [w.word for w in results] == ["go"]
    assert provider.calls == []  # local hit - provider never consulted (spec section 8: cache)


async def test_lookup_word_falls_back_to_provider_and_persists(session, monkeypatch):
    data = _word(
        "beautiful",
        translations=[
            ai_models.TranslationResult(translation="красивый"),
            ai_models.TranslationResult(translation="прекрасный"),
        ],
        part_of_speech="adjective",
        phonetic="BYOO-tuh-fuhl",
        pronunciation="/ˈbjuːtɪfʊl/",
        examples=[ai_models.ExampleResult(text="What a beautiful day.", translation="Какой прекрасный день.")],
        difficulty="intermediate",
        verb_forms={"past": "should-be-ignored-not-a-verb"},
    )
    provider = _FakeProvider(data)
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="beautiful", user_id=1
    )
    assert provider.calls == ["beautiful"]
    assert len(results) == 1
    word = results[0]
    assert word.word == "beautiful"
    assert word.part_of_speech == "adjective"
    assert word.pronunciation == "/ˈbjuːtɪfʊl/"
    assert {tr.translation for tr in word.translations} == {"красивый", "прекрасный"}
    assert word.examples[0].example_text == "What a beautiful day."
    assert word.forms == []  # not a verb - verb_forms must be ignored

    # Persisted for real - a second lookup finds it locally, no provider call.
    provider.calls.clear()
    again = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="beautiful", user_id=1
    )
    assert again[0].id == word.id
    assert provider.calls == []


async def test_lookup_word_persists_verb_forms_for_a_verb(session, monkeypatch):
    data = _word(
        "go", part_of_speech="verb",
        verb_forms={"past": "went", "gerund": "going"},
    )
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: _FakeProvider(data))

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="go", user_id=1
    )
    forms = {f.form_type: f.form for f in results[0].forms}
    assert forms == {"past": "went", "gerund": "going"}


async def test_lookup_word_returns_empty_when_provider_has_nothing(session, monkeypatch):
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: _FakeProvider(None))

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="zzzznotaword", user_id=1
    )
    assert results == []


async def test_lookup_word_with_default_provider_and_unconfigured_ai_returns_empty(session):
    """AI_ENABLED default / no AI_API_KEY (this project's default in
    tests) means the real AIDictionaryProvider hits NotConfiguredAIService's
    AIConfigurationError and catches it itself (a DictionaryProvider must
    never raise - see AIDictionaryProvider.lookup) - lookup_word degrades
    to "nothing found" (spec section 28: Dictionary falls back to local DB)."""
    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="zzzznotaword", user_id=1
    )
    assert results == []


async def test_ai_dictionary_provider_swallows_ai_errors(monkeypatch):
    """The real AIDictionaryProvider (not a test double) must catch any
    AIError from get_ai_service() and return None, never propagate."""
    from services.ai_service import get_ai_service
    from services.dictionary_service import AIDictionaryProvider

    class _RaisingAIService:
        async def lookup_word(self, *a, **k):
            raise AIConfigurationError()

    monkeypatch.setattr("services.dictionary_service.get_ai_service", lambda: _RaisingAIService())
    provider = AIDictionaryProvider()
    result = await provider.lookup("go", language_code="en", translation_language="ru", user_level=None, user_id=1)
    assert result is None


async def test_lookup_word_does_not_duplicate_when_provider_echoes_existing_word(session, monkeypatch):
    existing, _ = await word_service.get_or_create_word(session, language_code="en", word="cat")
    await session.commit()

    # Search for "cats" won't exact-match "cat" locally with the default
    # search (no plural stemming) - the provider is consulted and echoes
    # back "cat", which already exists.
    provider = _FakeProvider(_word("cat", translations=[ai_models.TranslationResult(translation="кошка")]))
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    results = await dictionary_service.lookup_word(
        session, language_code="en", translation_language="ru", raw_word="cats", user_id=1
    )
    assert len(results) == 1
    assert results[0].id == existing.id
