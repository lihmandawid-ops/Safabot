"""Tests for the on-demand translation backfill (level-and-difficulty
stage, spec sections 18-25's global language audit): services.
word_service.ensure_translation(). A local/seed Word can carry
translations into only some languages (a lot of seed data was only ever
translated into Russian) - a learner whose translation_language isn't one
of those must never be shown a blank translation line just because the
word itself already existed locally.
"""
from __future__ import annotations

from services import word_service


async def test_ensure_translation_is_a_noop_when_already_present(session, monkeypatch):
    """No AI call at all when the exact language is already there - the
    mock below would raise if it were ever reached."""
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet")
    from database.repositories import words as words_repo

    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="тихий")
    await session.commit()

    def _boom():
        raise AssertionError("should never call the dictionary provider when the translation already exists")

    monkeypatch.setattr("services.dictionary_service.get_dictionary_provider", _boom)

    result = await word_service.ensure_translation(session, word, translation_language="ru", user_id=1)

    assert {t.language_code for t in result.translations} == {"ru"}


async def test_ensure_translation_gracefully_noop_when_ai_unconfigured(session):
    """Default test environment has AI forced unconfigured (conftest.py's
    autouse fixture) - ensure_translation must degrade to a no-op, not
    raise or crash the card render."""
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet")
    await session.commit()

    result = await word_service.ensure_translation(session, word, translation_language="de", user_id=1)
    assert result.translations == []


async def test_ensure_translation_backfills_a_missing_language_from_ai(session, monkeypatch):
    """The core bug this fixes: a word already translated into Russian
    only, opened by a learner translating into German, must get a German
    translation added - never left blank, and the existing Russian
    translation must survive untouched."""
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService, get_ai_service

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            return (
                '{"word": "quiet", "translations": [{"translation": "ruhig", "usage_note": null}], '
                '"part_of_speech": "adjective", "phonetic": null, "pronunciation": null, '
                '"definition": null, "examples": [], "difficulty": null, "category": null, '
                '"verb_forms": null}'
            )

    live = LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()
    monkeypatch.setattr("services.dictionary_service.get_ai_service", lambda: live)

    from database.repositories import words as words_repo

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="тихий")
    await session.commit()

    result = await word_service.ensure_translation(session, word, translation_language="de", user_id=1)

    by_language = {t.language_code: t.translation for t in result.translations}
    assert by_language == {"ru": "тихий", "de": "ruhig"}

    get_ai_service.cache_clear()
