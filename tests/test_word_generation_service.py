"""Tests for services/word_generation_service.py (bugfix spec root cause
#2: Safabot never auto-generated new words; AI-integration spec section
11-13). Covers local-pool-first, AI-fallback-for-the-shortfall-only,
daily-limit respect, level preference, duplicate avoidance/bounded
retries, and graceful AI failure handling.
"""
from __future__ import annotations

from datetime import time

from database.models import WordGenerationLog, WordSource, WordStatus
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.repositories import words as words_repo
from services import ai_models, learning_service, word_generation_service, word_service
from services.ai_errors import AIUnavailableError
from sqlalchemy import select


async def _create_user(session, *, telegram_id=5000, daily_new_words=4, level="beginner"):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username=None, first_name="Test",
        interface_language="ru", timezone="UTC", level=level, daily_new_words=daily_new_words,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="ru",
        level=level, daily_new_words=daily_new_words,
    )
    return user, ul


async def _seed_local_words(session, n, *, prefix="genword", difficulty="beginner"):
    words = []
    for i in range(n):
        word, _ = await word_service.get_or_create_word(
            session, language_code="en", word=f"{prefix}{i}", difficulty=difficulty
        )
        words.append(word)
    await session.commit()
    return words


def _generated(word: str, translation: str = "перевод") -> ai_models.GeneratedWord:
    return ai_models.GeneratedWord(word=word, translations=[ai_models.TranslationResult(translation=translation)])


class _FakeAIService:
    """A minimal AIService double - only generate_words is exercised by
    word_generation_service, so that's all this implements."""

    def __init__(self, words: list[ai_models.GeneratedWord] | None = None, *, raises: Exception | None = None):
        self._words = words or []
        self._raises = raises
        self.calls = 0

    async def generate_words(self, *, language_code, translation_language, level, amount, category=None, known_words=None, user_id=None):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return ai_models.GenerateWordsResult(words=self._words)


def _fail_if_called():
    def _raise():
        raise AssertionError("AI provider should not have been called - local pool covered the request")
    return _raise


async def test_generate_new_words_uses_local_pool_first_without_ai(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5001)
    await _seed_local_words(session, 5)
    monkeypatch.setattr(word_generation_service, "get_ai_service", _fail_if_called())

    created = await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=3)

    assert len(created) == 3
    assert all(uw.status == WordStatus.NEW for uw in created)
    assert all(uw.source == WordSource.GENERATED for uw in created)


async def test_generate_new_words_excludes_already_known_words_in_any_status(session):
    user, ul = await _create_user(session, telegram_id=5002)
    known = await _seed_local_words(session, 4, prefix="known")
    unknown = await _seed_local_words(session, 3, prefix="unknown")

    statuses = [WordStatus.NEW, WordStatus.LEARNING, WordStatus.PAUSED, WordStatus.MASTERED]
    for word, status in zip(known, statuses):
        uw = await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
        uw.status = status
    await session.commit()

    created = await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=10)

    created_word_ids = {uw.word_id for uw in created}
    known_ids = {w.id for w in known}
    assert created_word_ids.isdisjoint(known_ids)
    assert created_word_ids == {w.id for w in unknown}


async def test_generate_new_words_calls_ai_only_for_the_shortfall(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5003)
    await _seed_local_words(session, 1)  # only 1 available locally, need 3

    fake = _FakeAIService([_generated("extra1", "доп1"), _generated("extra2", "доп2")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    created = await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=3)

    assert fake.calls == 1
    assert len(created) == 3
    assert all(uw.source == WordSource.GENERATED for uw in created)
    words = {uw.word.word for uw in created}
    assert "extra1" in words and "extra2" in words


async def test_generate_new_words_persists_definition_and_verb_forms(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5014)
    entry = ai_models.GeneratedWord(
        word="go", translations=[ai_models.TranslationResult(translation="идти")],
        part_of_speech="verb", definition="to move from one place to another",
        verb_forms={"past": "went", "gerund": "going"},
    )
    fake = _FakeAIService([entry])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    created = await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=1)

    assert len(created) == 1
    word = created[0].word
    assert word.definition == "to move from one place to another"
    forms = {f.form_type: f.form for f in word.forms}
    assert forms == {"past": "went", "gerund": "going"}


async def test_generate_new_words_ai_failure_degrades_gracefully(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5004)
    await _seed_local_words(session, 1)

    fake = _FakeAIService(raises=AIUnavailableError("provider unreachable"))
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    created = await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=3)

    assert len(created) == 1  # only what the local pool had - no crash


async def test_generate_new_words_amount_zero_is_a_noop(session):
    user, ul = await _create_user(session, telegram_id=5006)
    assert await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=0) == []


async def test_generate_new_words_logs_every_call(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5007)
    await _seed_local_words(session, 5)
    monkeypatch.setattr(word_generation_service, "get_ai_service", _fail_if_called())

    await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=3)
    await session.commit()

    result = await session.execute(select(WordGenerationLog).where(WordGenerationLog.user_id == user.id))
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].requested_amount == 3
    assert logs[0].generated_amount == 3
    assert logs[0].language_code == "en"


async def test_generate_new_words_retries_ai_up_to_max_attempts_on_duplicates(session, monkeypatch):
    """Section 12: if AI keeps handing back a word the user already has
    (or that a previous attempt already consumed), retry for more - but
    never more than MAX_GENERATION_ATTEMPTS times."""
    import config

    monkeypatch.setenv("MAX_GENERATION_ATTEMPTS", "3")
    config.get_settings.cache_clear()

    user, ul = await _create_user(session, telegram_id=5012)
    # AI always offers the exact same word - only the first attempt can
    # possibly succeed, every retry after that is a duplicate.
    fake = _FakeAIService([_generated("dup")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    created = await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=3)

    assert len(created) == 1  # only the first attempt actually added anything new
    assert fake.calls == 3  # bounded - not unbounded retries
    config.get_settings.cache_clear()


async def test_find_unknown_words_for_generation_prefers_level_match(session):
    user, ul = await _create_user(session, telegram_id=5008, level="advanced")
    await _seed_local_words(session, 3, prefix="beg", difficulty="beginner")
    await _seed_local_words(session, 3, prefix="adv", difficulty="advanced")
    await session.commit()

    candidates = await words_repo.find_unknown_words_for_generation(
        session, user_id=user.id, language_code="en", level="advanced", limit=3
    )
    assert all(w.difficulty == "advanced" for w in candidates)


async def test_get_new_words_for_today_auto_generates_the_shortfall(session):
    """services/learning_service.py's actual bugfix wiring: a user who has
    never manually added a single word must still get their daily quota
    from the local seed pool via auto-generation."""
    user, ul = await _create_user(session, telegram_id=5009, daily_new_words=4)
    await _seed_local_words(session, 10)

    result = await learning_service.get_new_words_for_today(session, user=user, user_language=ul)

    assert len(result.words) == 4
    assert result.shortfall is False
    assert all(uw.status == WordStatus.NEW for uw in result.words)


async def test_get_new_words_for_today_reports_shortfall_when_ai_unavailable(session, monkeypatch):
    """AI-integration spec section 20/28: when local pool + AI still can't
    fill the quota, callers must be told so they can show a friendly
    "couldn't load new words" message instead of silently under-delivering."""
    user, ul = await _create_user(session, telegram_id=5013, daily_new_words=4)
    # No local pool at all, and AI fails - nothing can fill the quota.
    monkeypatch.setattr(
        word_generation_service, "get_ai_service",
        lambda: _FakeAIService(raises=AIUnavailableError("down")),
    )

    result = await learning_service.get_new_words_for_today(session, user=user, user_language=ul)

    assert result.words == []
    assert result.shortfall is True


async def test_daily_new_word_limit_holds_across_repeated_learning_launches(session):
    from services.repetition_service import ReviewGrade
    from database.repositories import sessions as sessions_repo

    user, ul = await _create_user(session, telegram_id=5010, daily_new_words=2)
    await _seed_local_words(session, 10)

    first = await learning_service.build_learning_session(session, user=user, user_language=ul)
    assert first is not None
    assert first.total_words == 2

    # Finish the session so a rebuild isn't just resuming the same one.
    item = sessions_repo.next_incomplete_item(first)
    while item is not None:
        await learning_service.record_review_answer(session, first, item.user_word_id, grade=ReviewGrade.GOOD)
        item = sessions_repo.next_incomplete_item(first)
    await learning_service.finish_session_if_complete(session, user, first)
    await session.commit()

    second = await learning_service.build_learning_session(session, user=user, user_language=ul)
    assert second is None  # limit of 2 already used today, nothing due yet either


async def test_generation_is_isolated_between_languages_for_the_same_user(session):
    user, ul_en = await _create_user(session, telegram_id=5011, daily_new_words=3)
    ul_de = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="de", translation_language="ru", level="beginner", daily_new_words=3
    )
    await _seed_local_words(session, 5, prefix="en_word")
    for i in range(5):
        await word_service.get_or_create_word(session, language_code="de", word=f"de_word{i}", difficulty="beginner")
    await session.commit()

    en_created = await word_generation_service.generate_new_words(session, user=user, user_language=ul_en, amount=3)
    de_created = await word_generation_service.generate_new_words(session, user=user, user_language=ul_de, amount=3)

    assert {uw.language_code for uw in en_created} == {"en"}
    assert {uw.language_code for uw in de_created} == {"de"}
    assert {uw.word.word for uw in en_created}.isdisjoint({uw.word.word for uw in de_created})
