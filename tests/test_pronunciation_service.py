"""Tests for the centralized services.pronunciation_service facade (global
pronunciation rule, section 38) - confirms it's a thin, behavior-preserving
wrapper over word_service.ensure_pronunciation + utils.word_display.
format_pronunciation, and that 🔁 Обычное повторение (services.
review_now_service.build_flashcard_items) now backfills pronunciation the
same way the dictionary/⭐ Мои слова/📚 Учить слова cards already did.
"""
from __future__ import annotations

from services import pronunciation_service, word_service


async def test_format_pronunciation_is_latin_only(session):
    word, _ = await word_service.get_or_create_word(
        session, language_code="en", word="quiet", pronunciation="KWY-et", phonetic="/kwaɪət/"
    )
    await session.commit()
    assert pronunciation_service.format_pronunciation(word) == "KWY-et"


async def test_display_line_uses_the_shared_placeholder_when_unset(session):
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="hush")
    await session.commit()
    assert pronunciation_service.display_line(word) == "Произношение пока недоступно."


async def test_display_line_wraps_pronunciation_in_the_shared_speaker_format(session):
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="loud", pronunciation="lowd")
    await session.commit()
    assert pronunciation_service.display_line(word) == "🔊 lowd"


async def test_ensure_is_a_noop_when_already_set(session, monkeypatch):
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="calm", pronunciation="kahm")
    await session.commit()

    def _boom():
        raise AssertionError("should never call the dictionary provider when pronunciation is already set")

    monkeypatch.setattr("services.dictionary_service.get_dictionary_provider", _boom)

    result = await pronunciation_service.ensure(session, word, translation_language="ru", user_id=1)
    assert result.pronunciation == "kahm"


async def test_ensure_and_format_backfills_and_formats_in_one_call(session):
    from services.ai_provider import AIProvider
    from services.ai_service import LiveAIService, get_ai_service

    class _MockProvider(AIProvider):
        async def complete(self, *, system, user):
            return (
                '{"word": "quiet", "translations": [{"translation": "тихий", "usage_note": null}], '
                '"part_of_speech": "adjective", "phonetic": "/\\u02c8kwa\\u026a\\u0259t/", '
                '"pronunciation": "KWY-et", "definition": null, "examples": [], '
                '"difficulty": null, "category": null, "verb_forms": null}'
            )

    live = LiveAIService(
        provider=_MockProvider(), model="test-model", provider_label="mock",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )
    get_ai_service.cache_clear()

    import services.dictionary_service as dictionary_service_module
    original = dictionary_service_module.get_ai_service
    dictionary_service_module.get_ai_service = lambda: live
    try:
        word, _ = await word_service.get_or_create_word(session, language_code="en", word="quiet")
        await session.commit()
        result = await pronunciation_service.ensure_and_format(
            session, word, translation_language="ru", user_id=1
        )
        assert result == "KWY-et"
    finally:
        dictionary_service_module.get_ai_service = original
        get_ai_service.cache_clear()


async def test_review_now_flashcards_backfill_pronunciation(session, monkeypatch):
    """🔁 Обычное повторение previously showed pronunciation only when it
    happened to already be cached (services.review_now_service never
    called ensure_pronunciation at all) - unlike every other screen that
    shows a word card. It must now backfill exactly like the rest."""
    from database.repositories import user_words as user_words_repo
    from database.repositories import users as users_repo
    from database.repositories import user_languages as user_languages_repo
    from services import review_now_service
    from datetime import time

    def _mock_ai_service():
        from services.ai_provider import AIProvider
        from services.ai_service import LiveAIService

        class _MockProvider(AIProvider):
            async def complete(self, *, system, user):
                return (
                    '{"word": "silent", "translations": [{"translation": "тихий", "usage_note": null}], '
                    '"part_of_speech": "adjective", "phonetic": "/saɪlənt/", '
                    '"pronunciation": "SY-lent", "definition": null, "examples": [], '
                    '"difficulty": null, "category": null, "verb_forms": null}'
                )

        return LiveAIService(
            provider=_MockProvider(), model="test-model", provider_label="mock",
            max_retries=0, requests_per_minute=1000, requests_per_day=1000,
        )

    monkeypatch.setattr("services.dictionary_service.get_ai_service", _mock_ai_service)

    user = await users_repo.create_user(
        session, telegram_id=777, username="reviewer", first_name="R",
        interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="ru",
        level="beginner", daily_new_words=4,
    )
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="silent")
    from database.repositories import words as words_repo
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="тихий")
    uw = await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
    await session.commit()

    uw = await user_words_repo.get_by_id(session, uw.id)
    items = await review_now_service.build_flashcard_items(session, [uw], "ru", user_id=user.id)

    assert items[0]["pronunciation"] == "SY-lent"
