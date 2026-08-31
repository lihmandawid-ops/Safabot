"""Tests for services/word_generation_service.py (bugfix spec root cause
#2: Safabot never auto-generated new words; AI-integration spec section
11-13). Covers local-pool-first, AI-fallback-for-the-shortfall-only,
daily-limit respect, level preference, duplicate avoidance/bounded
retries, and graceful AI failure handling.
"""
from __future__ import annotations

from datetime import time

from database.models import WordGenerationLog, WordSource, WordStatus
from database.repositories import sessions as sessions_repo
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


async def _seed_local_words(session, n, *, prefix="genword", difficulty="beginner", category=None):
    words = []
    for i in range(n):
        word, _ = await word_service.get_or_create_word(
            session, language_code="en", word=f"{prefix}{i}", difficulty=difficulty, category=category
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

    async def generate_words(self, *, language_code, translation_language, level, amount, category=None, industry=None, goal=None, known_words=None, performance_note=None, user_id=None):
        self.calls += 1
        self.last_category = category
        self.last_industry = industry
        self.last_goal = goal
        self.last_known_words = list(known_words) if known_words is not None else None
        self.last_level = level
        self.last_performance_note = performance_note
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


async def test_generate_new_words_keeps_retrying_after_an_empty_ai_response(session, monkeypatch):
    """Real user report: a single AI hiccup (empty response - a timeout/
    network blip already exhausted its own internal retries) used to
    abort the whole outer retry loop immediately, instead of using the
    remaining attempts MAX_GENERATION_ATTEMPTS budgeted. The loop must
    keep trying until it either succeeds or genuinely runs out of
    attempts."""
    import config

    monkeypatch.setenv("MAX_GENERATION_ATTEMPTS", "3")
    config.get_settings.cache_clear()

    class _FlakyThenWorks:
        def __init__(self):
            self.calls = 0

        async def generate_words(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ai_models.GenerateWordsResult(words=[])  # empty response, not an exception
            return ai_models.GenerateWordsResult(words=[_generated("recovered")])

    fake = _FlakyThenWorks()
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    user, ul = await _create_user(session, telegram_id=5023)
    created = await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=1)

    assert len(created) == 1
    assert created[0].word.word == "recovered"
    assert fake.calls == 2  # first attempt empty, second attempt succeeded
    config.get_settings.cache_clear()


async def test_generate_candidates_keeps_retrying_after_ai_raises_once(session, monkeypatch):
    """Same fix, for the 🆕/🎯 candidate-generation path (generate_
    candidates) - a raised AIError on the first attempt must not prevent
    a later attempt from succeeding."""
    import config

    monkeypatch.setenv("MAX_GENERATION_ATTEMPTS", "3")
    config.get_settings.cache_clear()

    class _FailsOnceThenWorks:
        def __init__(self):
            self.calls = 0

        async def generate_words(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise AIUnavailableError("transient")
            return ai_models.GenerateWordsResult(words=[_generated("recovered2")])

    fake = _FailsOnceThenWorks()
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    user, ul = await _create_user(session, telegram_id=5024)
    candidates = await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1)

    assert len(candidates) == 1
    assert candidates[0].word == "recovered2"
    assert fake.calls == 2
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


async def test_find_unknown_words_for_generation_prefers_topic_over_level(session):
    """settings-improvements stage section 22: a topic-matching word at
    the "wrong" level must still outrank a level-matching word from an
    unrelated topic - the user explicitly said they're interested in
    this topic."""
    user, ul = await _create_user(session, telegram_id=5009, level="advanced")
    await _seed_local_words(session, 3, prefix="ontopic", difficulty="beginner", category="travel")
    await _seed_local_words(session, 3, prefix="onlevel", difficulty="advanced", category="business")
    await session.commit()

    candidates = await words_repo.find_unknown_words_for_generation(
        session, user_id=user.id, language_code="en", level="advanced", limit=3, topics=["travel"]
    )
    assert all(w.category == "travel" for w in candidates)


async def test_find_unknown_words_for_generation_empty_topics_falls_back_to_level(session):
    user, ul = await _create_user(session, telegram_id=5010, level="advanced")
    await _seed_local_words(session, 3, prefix="beg", difficulty="beginner")
    await _seed_local_words(session, 3, prefix="adv", difficulty="advanced")
    await session.commit()

    candidates = await words_repo.find_unknown_words_for_generation(
        session, user_id=user.id, language_code="en", level="advanced", limit=3, topics=[]
    )
    assert all(w.difficulty == "advanced" for w in candidates)


async def test_generate_new_words_passes_selected_topics_and_industry_to_ai(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5011)
    ul.learning_goal = "work"
    ul.work_industry = "healthcare"
    ul.selected_topics = ["travel", "food"]
    await session.commit()

    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=1)

    assert fake.last_category == "travel, food"
    assert fake.last_industry == "healthcare"


async def test_generate_new_words_includes_industry_even_when_goal_is_not_work(session, monkeypatch):
    """AI-new-words stage section 1: a stated profession is useful context
    regardless of the learner's stated goal - no longer gated behind
    learning_goal == "work" (that used to hide a legitimately set
    profession from the AI just because the goal field said something
    else)."""
    user, ul = await _create_user(session, telegram_id=5012)
    ul.learning_goal = "travel"
    ul.work_industry = "healthcare"
    await session.commit()

    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=1)

    assert fake.last_industry == "healthcare"


async def test_generate_new_words_omits_industry_when_unset(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5013)
    ul.learning_goal = "travel"
    ul.work_industry = None
    await session.commit()

    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_new_words(session, user=user, user_language=ul, amount=1)

    assert fake.last_industry is None


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


async def test_new_word_batch_regenerates_via_ai_for_repeated_same_day_launches(session, monkeypatch):
    """Bugfix stage, explicit product decision: no daily cap on new words
    - once local seed words run out, a repeated same-day 📚 Учить слова
    must top up via AI generation rather than coming back empty."""
    from services.repetition_service import ReviewGrade
    from database.repositories import sessions as sessions_repo

    user, ul = await _create_user(session, telegram_id=5010, daily_new_words=2)
    await _seed_local_words(session, 2)  # exactly enough for one batch, none left over

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

    fake = _FakeAIService([_generated("second_day_word_1", "слово1"), _generated("second_day_word_2", "слово2")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    second = await learning_service.build_learning_session(session, user=user, user_language=ul)

    assert second is not None
    assert second.total_words == 2
    assert second.id != first.id


async def test_generate_extra_words_adds_words_beyond_the_daily_new_words_quota(session):
    """Bugfix spec sections 9-11: ➕ Ещё новые слова tops up on top of
    daily_new_words, tracked under its own WordGenerationLog trigger."""
    user, ul = await _create_user(session, telegram_id=5015, daily_new_words=2)
    await _seed_local_words(session, 10)
    await session.commit()

    result = await word_generation_service.generate_extra_words(session, user=user, user_language=ul, amount=4)

    assert len(result.words) == 4
    assert result.limit_reached is False
    # Real user request: ➕ Ещё новые слова is a live add - it must enter
    # repetition immediately.
    assert all(uw.status == WordStatus.LEARNING for uw in result.words)

    logs = (
        await session.execute(select(WordGenerationLog).where(WordGenerationLog.user_id == user.id))
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].trigger == "extra_request"


async def test_generate_extra_words_respects_its_own_daily_cap(session, monkeypatch):
    import config

    monkeypatch.setenv("MAX_EXTRA_WORDS_PER_DAY", "4")
    config.get_settings.cache_clear()

    user, ul = await _create_user(session, telegram_id=5016, daily_new_words=2)
    await _seed_local_words(session, 20)
    await session.commit()

    first = await word_generation_service.generate_extra_words(session, user=user, user_language=ul, amount=4)
    await session.commit()
    assert len(first.words) == 4
    assert first.limit_reached is False

    second = await word_generation_service.generate_extra_words(session, user=user, user_language=ul, amount=4)
    assert second.words == []
    assert second.limit_reached is True

    config.get_settings.cache_clear()


async def test_generate_extra_words_bounds_amount_to_whats_left_of_the_cap(session, monkeypatch):
    import config

    monkeypatch.setenv("MAX_EXTRA_WORDS_PER_DAY", "5")
    config.get_settings.cache_clear()

    user, ul = await _create_user(session, telegram_id=5017, daily_new_words=2)
    await _seed_local_words(session, 20)
    await session.commit()

    first = await word_generation_service.generate_extra_words(session, user=user, user_language=ul, amount=4)
    await session.commit()
    assert len(first.words) == 4

    second = await word_generation_service.generate_extra_words(session, user=user, user_language=ul, amount=4)
    assert len(second.words) == 1  # only 1 left before hitting the cap of 5
    assert second.limit_reached is False
    assert second.remaining_today == 0

    config.get_settings.cache_clear()


async def test_get_new_words_for_today_never_double_counts_extra_words_added_today(session):
    """Real user request superseded the old "➕ Ещё новые слова words are
    reachable in today's session" behavior this test used to check: extras
    now enter repetition immediately (status=LEARNING, not NEW - see
    generate_extra_words), so they're no longer sitting in the local "not
    yet started" NEW pool get_new_word_candidates searches (the daily-
    quota flow this feeds is itself unreachable from any live button, but
    the query itself is still real code). A later same-day call for the
    main daily portion must top up from what's left of the local seed
    pool instead of re-surfacing the same 4 extra words a second time."""
    from services.repetition_service import ReviewGrade

    user, ul = await _create_user(session, telegram_id=5018, daily_new_words=2)
    await _seed_local_words(session, 10)
    await session.commit()

    main_session = await learning_service.build_learning_session(session, user=user, user_language=ul)
    assert main_session.total_words == 2  # today's main portion, consumed below
    item = sessions_repo.next_incomplete_item(main_session)
    while item is not None:
        await learning_service.record_review_answer(session, main_session, item.user_word_id, grade=ReviewGrade.GOOD)
        item = sessions_repo.next_incomplete_item(main_session)
    await learning_service.finish_session_if_complete(session, user, main_session)
    await session.commit()

    extra = await word_generation_service.generate_extra_words(session, user=user, user_language=ul, amount=4)
    await session.commit()
    assert len(extra.words) == 4
    assert all(uw.status == WordStatus.LEARNING for uw in extra.words)

    result = await learning_service.get_new_words_for_today(session, user=user, user_language=ul)
    assert len(result.words) == 2  # tops up from the remaining local pool
    extra_ids = {uw.id for uw in extra.words}
    assert extra_ids.isdisjoint({uw.id for uw in result.words})


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


# --- generate_words_ai_first() (level-and-difficulty stage, spec sections
# 40-62: 🆕 Новые слова / 🎯 Новые слова по теме must be AI-first, never a
# local-pool draw, even when the local pool has plenty of unused words.) ---

async def test_generate_words_ai_first_never_touches_the_local_pool(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5020)
    await _seed_local_words(session, 10)  # plenty available locally - must be ignored
    monkeypatch.setattr(words_repo, "find_unknown_words_for_generation", _fail_if_called())

    fake = _FakeAIService([_generated("aiword1"), _generated("aiword2")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    created = await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=2)

    assert len(created) == 2
    assert fake.calls == 1
    assert {uw.word.word for uw in created} == {"aiword1", "aiword2"}
    assert all(uw.source == WordSource.GENERATED for uw in created)


async def test_generate_words_ai_first_returns_empty_list_never_raises_on_ai_failure(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5021)
    monkeypatch.setattr(
        word_generation_service, "get_ai_service",
        lambda: _FakeAIService(raises=AIUnavailableError("down")),
    )

    created = await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=3)

    assert created == []  # never a random-DB fallback in disguise


async def test_generate_words_ai_first_amount_zero_is_a_noop(session):
    user, ul = await _create_user(session, telegram_id=5022)
    assert await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=0) == []


async def test_generate_words_ai_first_topics_override_beats_saved_selected_topics(session, monkeypatch):
    """🎯 Новые слова по теме passes its own one-off topic, which must win
    over whatever is saved on the profile for this single call."""
    user, ul = await _create_user(session, telegram_id=5023)
    ul.selected_topics = ["travel", "food"]
    await session.commit()

    fake = _FakeAIService([_generated("topicword")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_words_ai_first(
        session, user=user, user_language=ul, amount=1, topics=["cooking"]
    )

    assert fake.last_category == "cooking"


async def test_generate_words_ai_first_falls_back_to_saved_topics_when_no_override(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5024)
    ul.selected_topics = ["business"]
    await session.commit()

    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=1)

    assert fake.last_category == "business"


async def test_generate_words_ai_first_passes_learning_goal(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5025)
    ul.learning_goal = "travel"
    await session.commit()

    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=1)

    assert fake.last_goal == "travel"


async def test_generate_words_ai_first_logs_with_its_own_trigger(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5026)
    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_words_ai_first(
        session, user=user, user_language=ul, amount=1, trigger="explicit_new_words_topic"
    )
    await session.commit()

    logs = (await session.execute(select(WordGenerationLog).where(WordGenerationLog.user_id == user.id))).scalars().all()
    assert len(logs) == 1
    assert logs[0].trigger == "explicit_new_words_topic"


async def test_generate_words_ai_first_excludes_already_known_words(session, monkeypatch):
    """Same known-words hint mechanism generate_new_words already uses -
    the AI must be told what this learner already has."""
    user, ul = await _create_user(session, telegram_id=5027)
    known = await _seed_local_words(session, 2, prefix="known")
    for word in known:
        await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
    await session.commit()

    fake = _FakeAIService([_generated("newword")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=1)

    assert set(fake.last_known_words) == {"known0", "known1"}


async def test_generate_words_ai_first_effective_difficulty_uses_manual_pick(session, monkeypatch):
    """Section 6: manual difficulty_mode must drive AI-first generation
    too, not just the daily-quota path - never the auto-tracked estimate."""
    user, ul = await _create_user(session, telegram_id=5028, level="a1")
    ul.difficulty_mode = "manual"
    ul.learning_difficulty = "c1"
    await session.commit()

    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=1)

    assert fake.last_level == "c1"


async def test_generate_words_ai_first_effective_difficulty_uses_estimated_level_when_automatic(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5029, level="a1")
    ul.difficulty_mode = "automatic"
    ul.learning_difficulty = "c1"  # stale manual pick from before switching back - must be ignored
    await session.commit()

    fake = _FakeAIService([_generated("word1")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_words_ai_first(session, user=user, user_language=ul, amount=1)

    assert fake.last_level == "a1"


# --- generate_candidates() / add_candidate_to_learning() / reject_word()
# (AI-new-words stage sections 1-7, 32-33): the interactive per-word
# candidate flow behind 🆕 Новые слова / 🎯 Новые слова по теме - unlike
# generate_words_ai_first, nothing is persisted until the caller explicitly
# accepts a candidate. ---

async def test_generate_candidates_does_not_persist_anything(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5030)
    fake = _FakeAIService([_generated("candword")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    candidates = await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1)

    assert [c.word for c in candidates] == ["candword"]
    words = await user_words_repo.get_user_words(session, user_id=user.id, language_code="en")
    assert words == []


async def test_generate_candidates_amount_zero_is_a_noop(session):
    user, ul = await _create_user(session, telegram_id=5031)
    assert await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=0) == []


async def test_generate_candidates_excludes_known_and_rejected_words(session, monkeypatch):
    from database.repositories import rejected_words as rejected_words_repo

    user, ul = await _create_user(session, telegram_id=5032)
    known = await _seed_local_words(session, 1, prefix="known")
    await user_words_repo.add_word(session, user_id=user.id, word_id=known[0].id, language_code="en")
    await rejected_words_repo.add(session, user_id=user.id, language_code="en", word="rejectedword")
    await session.commit()

    fake = _FakeAIService([_generated("newword")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1)

    assert set(fake.last_known_words) == {"known0", "rejectedword"}


async def test_generate_candidates_topics_override_scopes_a_single_call(session, monkeypatch):
    user, ul = await _create_user(session, telegram_id=5033)
    fake = _FakeAIService([_generated("topicword")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1, topics=["travel"])

    assert fake.last_category == "travel"


async def test_generate_candidates_broadens_to_goal_industry_when_topic_is_exhausted(session, monkeypatch):
    """Real user request: a narrow/exhausted topic must not just report
    "nothing found" - generate_candidates makes one more bounded attempt-
    block with the topic dropped (still scoped to the learner's own
    goal/industry, just not pinned to that one topic) before genuinely
    giving up."""
    user, ul = await _create_user(session, telegram_id=5037)

    class _TopicAwareAI:
        def __init__(self):
            self.categories_seen: list[str | None] = []

        async def generate_words(self, *, category=None, **kwargs):
            self.categories_seen.append(category)
            if category == "travel":
                return ai_models.GenerateWordsResult(words=[])  # topic exhausted - nothing new left
            return ai_models.GenerateWordsResult(words=[_generated("broadword")])

    fake = _TopicAwareAI()
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    candidates = await word_generation_service.generate_candidates(
        session, user=user, user_language=ul, amount=1, topics=["travel"],
    )

    assert [c.word for c in candidates] == ["broadword"]
    assert "travel" in fake.categories_seen  # the topic was genuinely tried first
    assert None in fake.categories_seen  # then broadened, never skipped straight to giving up


async def test_generate_candidates_broadens_to_goal_only_when_industry_is_also_exhausted(session, monkeypatch):
    """Real user report: a learner with both a saved topic AND a narrow
    work_industry (e.g. a niche trade) can exhaust tier 2 (industry+goal,
    topic dropped) just as fast as tier 1 - this must not just give up,
    it drops the industry too and makes one final bounded attempt-block
    scoped to the goal alone before genuinely reporting nothing found."""
    user, ul = await _create_user(session, telegram_id=5040)
    ul.work_industry = "Установка окон"
    await session.commit()

    class _IndustryAwareAI:
        def __init__(self):
            self.industries_seen: list[str | None] = []

        async def generate_words(self, *, category=None, industry=None, **kwargs):
            self.industries_seen.append(industry)
            if industry == "Установка окон":
                return ai_models.GenerateWordsResult(words=[])  # topic AND industry both exhausted
            return ai_models.GenerateWordsResult(words=[_generated("goalword")])

    fake = _IndustryAwareAI()
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    candidates = await word_generation_service.generate_candidates(
        session, user=user, user_language=ul, amount=1, topics=["travel"],
    )

    assert [c.word for c in candidates] == ["goalword"]
    assert "Установка окон" in fake.industries_seen  # industry genuinely tried before being dropped
    assert None in fake.industries_seen  # then broadened to goal-only, never skipped straight to giving up


async def test_generate_candidates_broadening_is_still_bounded(session, monkeypatch):
    """Never unbounded, even with the new broadening step: if neither the
    topic nor the broadened goal/industry search find anything new, the
    function still returns (empty) rather than retrying forever."""
    from config import get_settings

    user, ul = await _create_user(session, telegram_id=5038)

    class _NeverFindsAnything:
        def __init__(self):
            self.calls = 0

        async def generate_words(self, *, category=None, **kwargs):
            self.calls += 1
            return ai_models.GenerateWordsResult(words=[])

    fake = _NeverFindsAnything()
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    candidates = await word_generation_service.generate_candidates(
        session, user=user, user_language=ul, amount=1, topics=["travel"],
    )

    assert candidates == []
    assert fake.calls == get_settings().max_generation_attempts * 2  # topic tier + broadened tier, no more


async def test_generate_candidates_no_broadening_when_there_was_no_topic_to_begin_with(session, monkeypatch):
    """A plain 🆕 Новые слова request with no saved topics is already at
    its broadest - there is nothing to fall back FROM, so it must not
    double its AI-call budget for no reason."""
    from config import get_settings

    user, ul = await _create_user(session, telegram_id=5039)

    class _NeverFindsAnything:
        def __init__(self):
            self.calls = 0

        async def generate_words(self, *, category=None, **kwargs):
            self.calls += 1
            return ai_models.GenerateWordsResult(words=[])

    fake = _NeverFindsAnything()
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    candidates = await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1)

    assert candidates == []
    assert fake.calls == get_settings().max_generation_attempts


async def test_add_candidate_to_learning_persists_as_learning_status(session, monkeypatch):
    """Real user request: a candidate the learner just accepted is a LIVE
    add - it must enter repetition immediately, not sit as an untouched
    NEW candidate."""
    user, ul = await _create_user(session, telegram_id=5034)
    fake = _FakeAIService([_generated("candword")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    candidates = await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1)
    added = await word_generation_service.add_candidate_to_learning(session, entry=candidates[0], user=user, user_language=ul)

    assert added is not None
    assert added.status == WordStatus.LEARNING
    words = await user_words_repo.get_user_words(session, user_id=user.id, language_code="en")
    assert [uw.word.word for uw in words] == ["candword"]


async def test_reject_word_creates_no_userword_and_is_idempotent(session):
    from database.repositories import rejected_words as rejected_words_repo

    user, ul = await _create_user(session, telegram_id=5035)

    await word_generation_service.reject_word(session, user=user, user_language=ul, word="skipword")
    await word_generation_service.reject_word(session, user=user, user_language=ul, word="SkipWord")  # same word, different case
    await session.commit()

    rejected = await rejected_words_repo.list_words(session, user_id=user.id, language_code="en")
    assert rejected == ["skipword"]  # idempotent, not duplicated
    words = await user_words_repo.get_user_words(session, user_id=user.id, language_code="en")
    assert words == []


async def test_generate_candidates_excludes_a_previously_rejected_word_from_a_later_batch(session, monkeypatch):
    """End-to-end proof of spec section 7: reject once, never suggested
    again."""
    user, ul = await _create_user(session, telegram_id=5036)

    await word_generation_service.reject_word(session, user=user, user_language=ul, word="alreadyrejected")
    await session.commit()

    fake = _FakeAIService([_generated("freshword")])
    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: fake)

    await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1)

    assert "alreadyrejected" in fake.last_known_words
