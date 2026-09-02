"""Tests for the statistics/progress stage (📊 Мой прогресс):
- ReviewLog is written exactly once per applied grade (database/
  repositories/learning.py::apply_review_result), the single choke point
  every review write path already funnels through.
- database/repositories/progress.py's aggregate queries.
- services/progress_service.py's snapshot + trend detection.
- services/level_progress_service.py's new get_level_progress().
- services/learner_profile_service.py's structured AI profile.
- handlers/progress.py's 📊 Мой прогресс screen (no language / empty /
  populated).
- word_generation_service wiring the profile into the AI prompt as
  performance_note.
"""
from __future__ import annotations

import os
import tempfile
from datetime import time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import ReviewLog, WordStatus
from database.repositories import progress as progress_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.repositories.learning import apply_review_result
from services import learner_profile_service, level_progress_service, progress_service, word_service
from services.repetition_service import ReviewGrade, calculate_next_review
from sqlalchemy import select
from utils.time import utc_now


async def _create_user(session, *, telegram_id=9000, level="b1"):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username=None, first_name="Test",
        interface_language="en", timezone="UTC", level=level, daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="ru",
        level=level, daily_new_words=4,
    )
    return user, ul


async def _add_word(session, *, user, word_text, difficulty="b1", status=WordStatus.LEARNING):
    word, _ = await word_service.get_or_create_word(
        session, language_code="en", word=word_text, difficulty=difficulty
    )
    uw = await user_words_repo.add_word(
        session, user_id=user.id, word_id=word.id, language_code="en", status=status
    )
    await session.flush()
    return uw


# --------------------------------------------------------------------- #
# ReviewLog write path
# --------------------------------------------------------------------- #

async def test_apply_review_result_writes_exactly_one_review_log_row(session):
    user, _ = await _create_user(session)
    uw = await _add_word(session, user=user, word_text="hello")

    result = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.GOOD)
    await apply_review_result(session, uw, result)
    await session.commit()

    rows = (await session.execute(select(ReviewLog).where(ReviewLog.user_word_id == uw.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].correct_delta == 1
    assert rows[0].wrong_delta == 0
    assert rows[0].user_id == user.id
    assert rows[0].language_code == "en"


async def test_apply_review_result_again_grade_logs_wrong_delta(session):
    user, _ = await _create_user(session)
    uw = await _add_word(session, user=user, word_text="hello")

    result = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.AGAIN)
    await apply_review_result(session, uw, result)
    await session.commit()

    row = (await session.execute(select(ReviewLog).where(ReviewLog.user_word_id == uw.id))).scalar_one()
    assert row.correct_delta == 0
    assert row.wrong_delta == 1


async def test_apply_review_result_hard_grade_logs_neither(session):
    """HARD carries (0, 0) on UserWord's own counters - ReviewLog must
    mirror that exactly, never inventing a new right/wrong categorization."""
    user, _ = await _create_user(session)
    uw = await _add_word(session, user=user, word_text="hello")

    result = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.HARD)
    await apply_review_result(session, uw, result)
    await session.commit()

    row = (await session.execute(select(ReviewLog).where(ReviewLog.user_word_id == uw.id))).scalar_one()
    assert (row.correct_delta, row.wrong_delta) == (0, 0)


async def test_user_cascade_delete_removes_review_logs(session):
    """statistics/progress stage must not break the existing full-account
    reset feature - ReviewLog needs ondelete=CASCADE like every other
    user-owned table."""
    user, _ = await _create_user(session)
    uw = await _add_word(session, user=user, word_text="hello")
    result = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.GOOD)
    await apply_review_result(session, uw, result)
    await session.commit()

    await users_repo.delete_user(session, user)
    await session.commit()

    rows = (await session.execute(select(ReviewLog))).scalars().all()
    assert rows == []


# --------------------------------------------------------------------- #
# database/repositories/progress.py
# --------------------------------------------------------------------- #

async def test_consolidation_buckets_classifies_by_stage_and_status(session):
    user, _ = await _create_user(session)

    mastered = await _add_word(session, user=user, word_text="mastered1", status=WordStatus.MASTERED)
    consolidated = await _add_word(session, user=user, word_text="consolidated1")
    consolidated.repetition_stage = 5
    struggling = await _add_word(session, user=user, word_text="struggling1")
    struggling.wrong_answers = 2
    struggling.difficulty_score = 3.0
    fresh = await _add_word(session, user=user, word_text="fresh1")
    await session.commit()

    buckets = await progress_repo.consolidation_buckets(session, user_id=user.id, language_code="en")
    assert buckets["well_consolidated"] == 2  # mastered + high-stage
    assert buckets["difficult"] == 1
    assert buckets["in_progress"] == 1


async def test_new_words_since_counts_only_words_added_in_window(session):
    user, _ = await _create_user(session)
    old = await _add_word(session, user=user, word_text="old1")
    old.added_at = utc_now() - timedelta(days=40)
    recent = await _add_word(session, user=user, word_text="recent1")
    await session.commit()

    since = utc_now() - timedelta(days=7)
    count = await progress_repo.new_words_since(session, user_id=user.id, language_code="en", since=since)
    assert count == 1


async def test_review_totals_since_uses_review_log_window(session):
    user, _ = await _create_user(session)
    uw = await _add_word(session, user=user, word_text="hello")

    old_result = calculate_next_review(0, 0, ReviewGrade.GOOD)
    await apply_review_result(session, uw, old_result, now=utc_now() - timedelta(days=40))
    recent_result = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.AGAIN)
    await apply_review_result(session, uw, recent_result, now=utc_now())
    await session.commit()

    since = utc_now() - timedelta(days=7)
    count, correct, wrong = await progress_repo.review_totals_since(
        session, user_id=user.id, language_code="en", since=since
    )
    assert count == 1
    assert correct == 0
    assert wrong == 1


async def test_weakest_and_strongest_words(session):
    user, _ = await _create_user(session)
    weak = await _add_word(session, user=user, word_text="weakword")
    weak.difficulty_score = 4.0
    weak.wrong_answers = 3
    strong = await _add_word(session, user=user, word_text="strongword", status=WordStatus.MASTERED)
    strong.difficulty_score = 0.0
    await session.commit()

    weak_words = await progress_repo.weakest_words(session, user_id=user.id, language_code="en", limit=5)
    strong_words = await progress_repo.strongest_words(session, user_id=user.id, language_code="en", limit=5)
    assert weak_words == ["weakword"]
    assert strong_words == ["strongword"]


# --------------------------------------------------------------------- #
# services/progress_service.py
# --------------------------------------------------------------------- #

async def test_build_snapshot_empty_user_has_zero_totals(session):
    user, ul = await _create_user(session)
    snapshot = await progress_service.build_snapshot(session, user_id=user.id, user_language=ul, timezone="UTC")
    assert snapshot.total_words == 0
    assert snapshot.total_reviews == 0
    assert snapshot.overall_accuracy == 0.0


async def test_build_snapshot_reflects_real_review_data(session):
    user, ul = await _create_user(session)
    uw = await _add_word(session, user=user, word_text="hello")
    good = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.GOOD)
    await apply_review_result(session, uw, good, now=utc_now())
    await session.commit()

    snapshot = await progress_service.build_snapshot(session, user_id=user.id, user_language=ul, timezone="UTC")
    assert snapshot.total_words == 1
    assert snapshot.total_reviews == 1
    assert snapshot.total_correct == 1
    assert snapshot.overall_accuracy == 1.0
    assert snapshot.today.reviews == 1
    assert snapshot.last_7_days.reviews == 1
    assert snapshot.last_30_days.new_words == 1


def test_recent_performance_trend_insufficient_data_below_window():
    assert progress_service.recent_performance_trend([(1, 0)] * 3) == "insufficient_data"


def test_recent_performance_trend_detects_improvement():
    # Most-recent-first: recent half all correct, older half all wrong.
    deltas = [(1, 0)] * 5 + [(0, 1)] * 5
    assert progress_service.recent_performance_trend(deltas) == "improving"


def test_recent_performance_trend_detects_decline():
    deltas = [(0, 1)] * 5 + [(1, 0)] * 5
    assert progress_service.recent_performance_trend(deltas) == "declining"


def test_recent_performance_trend_stable_when_close():
    # Both halves at 80% accuracy (4 correct, 1 wrong each) - no real shift.
    half = [(1, 0)] * 4 + [(0, 1)] * 1
    assert progress_service.recent_performance_trend(half + half) == "stable"


# --------------------------------------------------------------------- #
# services/level_progress_service.py::get_level_progress
# --------------------------------------------------------------------- #

async def test_get_level_progress_zero_when_no_mastered_words(session):
    user, ul = await _create_user(session, level="b1")
    progress = await level_progress_service.get_level_progress(session, user_language=ul)
    assert progress.current_level == "b1"
    assert progress.next_level == "b2"
    assert progress.progress_ratio == 0.0


async def test_get_level_progress_at_max_level_reports_full(session):
    user, ul = await _create_user(session, level="c2")
    progress = await level_progress_service.get_level_progress(session, user_language=ul)
    assert progress.next_level is None
    assert progress.progress_ratio == 1.0


async def test_get_level_progress_never_raises_and_still_returns_a_value(session, monkeypatch):
    user, ul = await _create_user(session, level="b1")

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(level_progress_service, "_count_mastered_at_level", _boom)
    progress = await level_progress_service.get_level_progress(session, user_language=ul)
    assert progress.mastered_count == 0
    assert progress.progress_ratio == 0.0


# --------------------------------------------------------------------- #
# services/learner_profile_service.py
# --------------------------------------------------------------------- #

async def test_build_learner_profile_reflects_active_and_mastered_counts(session):
    user, ul = await _create_user(session)
    await _add_word(session, user=user, word_text="active1", status=WordStatus.LEARNING)
    await _add_word(session, user=user, word_text="active2", status=WordStatus.REVIEW)
    await _add_word(session, user=user, word_text="mastered1", status=WordStatus.MASTERED)
    await session.commit()

    profile = await learner_profile_service.build_learner_profile(session, user_id=user.id, user_language=ul)
    assert profile.active_words == 2
    assert profile.learned_words == 1
    assert profile.current_level == ul.level
    assert profile.recent_performance == "insufficient_data"


# --------------------------------------------------------------------- #
# handlers/progress.py - real session_scope()/real database, same pattern
# as tests/test_settings_handlers.py's handler_db fixture (monkeypatching
# database.database.session_scope wouldn't reach handlers/progress.py's
# own already-imported `session_scope` name).
# --------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")

    import config
    config.get_settings.cache_clear()

    import database.database as db_module
    db_module._engine = None
    db_module._session_factory = None

    from database.database import init_models
    await init_models()

    yield

    await db_module.dispose_engine()
    os.remove(path)


def _update(telegram_id: int):
    msg = AsyncMock()
    return SimpleNamespace(effective_user=SimpleNamespace(id=telegram_id), message=msg), msg


async def test_show_progress_without_language_shows_friendly_message(handler_db):
    from database.database import session_scope
    from database.seed import seed_languages
    from handlers import progress as progress_handler

    async with session_scope() as s:
        await seed_languages(s)
        user, _ = await _create_user(s, telegram_id=8001)
        # Remove the language _create_user gave them, to hit the
        # "no active language" branch.
        from database.models import UserLanguage
        rows = (await s.execute(select(UserLanguage).where(UserLanguage.user_id == user.id))).scalars().all()
        for row in rows:
            await s.delete(row)

    update, msg = _update(telegram_id=8001)
    await progress_handler.show_progress(update, SimpleNamespace(user_data={}))

    msg.reply_text.assert_awaited_once()
    text = msg.reply_text.call_args[0][0]
    assert "choose the language you're learning" in text


async def test_show_progress_empty_shows_empty_message(handler_db):
    from database.database import session_scope
    from database.seed import seed_languages
    from handlers import progress as progress_handler

    async with session_scope() as s:
        await seed_languages(s)
        await _create_user(s, telegram_id=8002)

    update, msg = _update(telegram_id=8002)
    await progress_handler.show_progress(update, SimpleNamespace(user_data={}))

    msg.reply_text.assert_awaited_once()
    text = msg.reply_text.call_args[0][0]
    assert "No stats yet" in text


async def test_show_progress_populated_includes_key_sections(handler_db):
    from database.database import session_scope
    from database.seed import seed_languages
    from handlers import progress as progress_handler

    async with session_scope() as s:
        await seed_languages(s)
        user, _ = await _create_user(s, telegram_id=8003)
        uw = await _add_word(s, user=user, word_text="hello")
        good = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.GOOD)
        await apply_review_result(s, uw, good)

    update, msg = _update(telegram_id=8003)
    await progress_handler.show_progress(update, SimpleNamespace(user_data={}))

    msg.reply_text.assert_awaited_once()
    text = msg.reply_text.call_args[0][0]
    assert "My Progress" in text
    assert "Overall stats" in text
    assert "Level progress" in text


# --------------------------------------------------------------------- #
# word_generation_service: performance_note wiring
# --------------------------------------------------------------------- #

async def test_generate_candidates_passes_performance_note_to_ai(session, monkeypatch):
    from services import ai_models, word_generation_service

    user, ul = await _create_user(session)
    uw = await _add_word(session, user=user, word_text="hello")
    good = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.GOOD)
    await apply_review_result(session, uw, good)
    await session.commit()

    captured = {}

    class _FakeAI:
        async def generate_words(self, **kwargs):
            captured.update(kwargs)
            return ai_models.GenerateWordsResult(words=[])

    monkeypatch.setattr(word_generation_service, "get_ai_service", lambda: _FakeAI())

    await word_generation_service.generate_candidates(session, user=user, user_language=ul, amount=1)

    assert captured.get("performance_note") is not None
    assert "accuracy=" in captured["performance_note"]
