"""Orchestrates the daily learning flow (learning-core stage, sections
5-12, 20-27): picking due reviews and today's new words, building/
resuming a LearningSession, recording each answer, and updating streaks.

Handlers call only this module for anything learning-session-shaped -
never database.repositories.learning/sessions directly, and never
services/repetition_service.py directly either (record_review_answer is
the one place that connects a grade to a database mutation).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.models import LearningSession, LearningSessionItem, User, UserLanguage, UserWord
from database.repositories import learning as learning_repo
from database.repositories import sessions as sessions_repo
from services import word_generation_service
from services.repetition_service import ReviewGrade, calculate_next_review
from utils.time import local_day_bounds, local_today, utc_now


@dataclass
class NewWordsResult:
    words: list[UserWord]
    # True when the daily quota couldn't be fully filled even after local
    # pool + AI generation - e.g. AI is unavailable/misconfigured and the
    # local pool alone doesn't cover it. Callers use this to show a
    # friendly heads-up (AI-integration spec section 20) instead of
    # silently handing the user fewer words than expected.
    shortfall: bool


async def get_due_reviews(
    session: AsyncSession, *, user_id: int, language_code: str, now: datetime | None = None
) -> list[UserWord]:
    now = now if now is not None else utc_now()
    return await learning_repo.get_due_for_review(
        session, user_id=user_id, language_code=language_code, limit=get_settings().max_daily_reviews, now=now
    )


async def get_remaining_new_word_quota(
    session: AsyncSession, *, user: User, user_language: UserLanguage, now: datetime | None = None
) -> int:
    """How many more new words `user` can start today, per
    user_language.daily_new_words (section 6) - shared by
    get_new_words_for_today and any caller (e.g. handlers/learning.py's
    intro screen) that needs the number without duplicating the
    day-bounds + count query."""
    now = now if now is not None else utc_now()
    day_start, day_end = local_day_bounds(now, user.timezone)
    already_used = await learning_repo.count_new_words_started_today(
        session, user_id=user.id, language_code=user_language.language_code, day_start=day_start, day_end=day_end
    )
    return max(0, user_language.daily_new_words - already_used)


async def get_new_words_for_today(
    session: AsyncSession, *, user: User, user_language: UserLanguage, now: datetime | None = None
) -> NewWordsResult:
    """Section 6: never exceed user_language.daily_new_words new words
    per LOCAL calendar day, regardless of how many sessions that spans.

    Bugfix spec (root cause #2): if the words the user already has sitting
    as NEW aren't enough to fill today's remaining quota, top up the
    shortfall via word_generation_service before returning - this is the
    one place 📚 Учить слова's "not enough new words" gap gets closed, so
    every caller (build_learning_session, handlers/learning.py's intro
    screen) gets generation for free.
    """
    remaining = await get_remaining_new_word_quota(session, user=user, user_language=user_language, now=now)
    if remaining == 0:
        return NewWordsResult(words=[], shortfall=False)

    existing = await learning_repo.get_new_word_candidates(
        session, user_id=user.id, language_code=user_language.language_code,
        level=user_language.level, limit=remaining,
    )
    shortfall = remaining - len(existing)
    if shortfall <= 0:
        return NewWordsResult(words=existing, shortfall=False)

    try:
        generated = await word_generation_service.generate_new_words(
            session, user=user, user_language=user_language, amount=shortfall
        )
    except Exception:
        # Generation failing must never break the learning flow (bugfix
        # spec) - the user still gets whatever was already available.
        generated = []

    words = existing + generated
    return NewWordsResult(words=words, shortfall=len(words) < remaining)


async def build_learning_session(
    session: AsyncSession,
    *,
    user: User,
    user_language: UserLanguage,
    include_new_words: bool = True,
    now: datetime | None = None,
) -> LearningSession | None:
    """Resumes an in-progress session if one exists (section 25); otherwise
    builds a new one, due reviews first, then new words if the daily limit
    allows and `include_new_words` is set (🔄 Повторить passes False so it
    never hands out new words - section 8's priority order). Returns None
    if there is nothing to do.
    """
    now = now if now is not None else utc_now()

    existing = await sessions_repo.get_active_session(session, user_id=user.id, language_code=user_language.language_code)
    if existing is not None:
        if sessions_repo.next_incomplete_item(existing) is not None:
            return existing
        # Every item was answered but the session was never marked
        # completed (e.g. the process died between the last answer and
        # the completion write) - self-heal instead of leaving it stuck.
        await sessions_repo.complete_session(session, existing, now=now)

    due = await get_due_reviews(session, user_id=user.id, language_code=user_language.language_code, now=now)
    new_words = (
        (await get_new_words_for_today(session, user=user, user_language=user_language, now=now)).words
        if include_new_words
        else []
    )

    if not due and not new_words:
        return None

    learning_session = await sessions_repo.create_session(session, user_id=user.id, language_code=user_language.language_code)
    position = 1
    for user_word in due:
        await sessions_repo.add_session_item(
            session, learning_session=learning_session, user_word_id=user_word.id, position=position, is_new_word=False
        )
        position += 1
    for user_word in new_words:
        await sessions_repo.add_session_item(
            session, learning_session=learning_session, user_word_id=user_word.id, position=position, is_new_word=True
        )
        position += 1

    # The items just created only have user_word_id set (a bare FK), not
    # the .user_word relationship object - re-fetching with
    # get_session_by_id's eager loads is what makes item.user_word.word
    # safe to read afterwards without a lazy-load (unsupported here; see
    # sessions_repo.create_session's docstring for the same MissingGreenlet
    # issue on the .items collection itself).
    return await sessions_repo.get_session_by_id(session, learning_session.id)


async def mark_word_as_seen(
    session: AsyncSession, learning_session: LearningSession, user_word_id: int, *, grade: ReviewGrade, now: datetime | None = None
) -> LearningSessionItem | None:
    """Alias kept for the spec's named method list; see record_review_answer
    for the actual implementation (same function - "marking a word as
    seen" IS recording its answer in this design, there's no separate
    unscored "seen" state)."""
    return await record_review_answer(session, learning_session, user_word_id, grade=grade, now=now)


async def record_review_answer(
    session: AsyncSession,
    learning_session: LearningSession,
    user_word_id: int,
    *,
    grade: ReviewGrade,
    now: datetime | None = None,
) -> LearningSessionItem | None:
    """Applies one rating: computes the new schedule via
    repetition_service, writes it to the UserWord, and marks this
    session's item complete. Returns None if `user_word_id` isn't part of
    THIS session (spec section 36 - never trust the id alone).

    `learning_session` must have come from sessions_repo.get_active_session
    or get_session_by_id, which eager-load item.user_word - the item
    fetched below is the SAME Python object (SQLAlchemy's identity map),
    so item.user_word is already populated and safe to read without
    another await (async SQLAlchemy has no implicit lazy-load)."""
    now = now if now is not None else utc_now()

    item = await sessions_repo.get_item_for_user_word(
        session, learning_session_id=learning_session.id, user_word_id=user_word_id
    )
    if item is None or item.completed:
        return None

    user_word = item.user_word
    result = calculate_next_review(user_word.repetition_stage, user_word.interval_days, grade, now=now)
    await learning_repo.apply_review_result(session, user_word, result, now=now)
    await sessions_repo.complete_item(session, item, rating=grade.value)
    return item


async def finish_session_if_complete(
    session: AsyncSession, user: User, learning_session: LearningSession, *, now: datetime | None = None
) -> bool:
    """Marks the session completed and updates the streak once every item
    has been answered. Returns True if it just completed the session."""
    if sessions_repo.next_incomplete_item(learning_session) is not None:
        return False

    now = now if now is not None else utc_now()
    await sessions_repo.complete_session(session, learning_session, now=now)
    await _update_streak(user, now)
    return True


async def _update_streak(user: User, now: datetime) -> None:
    """Section 22-23: one completed session per LOCAL calendar day counts,
    consecutive local days extend the streak, a gap resets it, and
    finishing a second session on the same local day is a no-op."""
    today = local_today(now, user.timezone)

    if user.last_learning_date == today:
        return

    if user.last_learning_date is not None and (today - user.last_learning_date).days == 1:
        user.current_streak += 1
    else:
        user.current_streak = 1

    user.longest_streak = max(user.longest_streak, user.current_streak)
    user.last_learning_date = today
