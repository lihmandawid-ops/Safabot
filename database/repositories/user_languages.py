"""Data access for UserLanguage (spec sections 4 and 13).

Terminology note, since the spec overloads the word "active":
    - `UserLanguage.active` (bool) = the user hasn't paused/dropped this
      language track. Toggled by set_language_enabled().
    - `UserLanguage.is_current` (bool) = the ONE language shown as ACTIVE
      in the main menu / Settings -> "Мой язык" (section 13). Toggled by
      set_active_language(); at most one row per user is True.
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserLanguage


class DuplicateUserLanguageError(Exception):
    """Raised when a user already has this (learning, translation) pair
    (spec section 4: never allow duplicating the same pair)."""


async def get_user_languages(
    session: AsyncSession, user_id: int, *, active_only: bool = False
) -> list[UserLanguage]:
    stmt = select(UserLanguage).where(UserLanguage.user_id == user_id)
    if active_only:
        stmt = stmt.where(UserLanguage.active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_current_language(session: AsyncSession, user_id: int) -> UserLanguage | None:
    result = await session.execute(
        select(UserLanguage).where(
            UserLanguage.user_id == user_id, UserLanguage.is_current.is_(True)
        )
    )
    return result.scalar_one_or_none()


async def get_by_language_code(session: AsyncSession, *, user_id: int, language_code: str) -> UserLanguage | None:
    """Level-and-difficulty stage: services.learning_service needs "the
    UserLanguage a just-completed LearningSession belongs to", and a
    session only ever stores language_code (not a translation_language) -
    prefers the row marked is_current, falling back to any match, since a
    session is always built against whichever pair was current at the
    time."""
    result = await session.execute(
        select(UserLanguage)
        .where(UserLanguage.user_id == user_id, UserLanguage.language_code == language_code)
        .order_by(UserLanguage.is_current.desc())
    )
    return result.scalars().first()


async def add_language(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    translation_language: str,
    level: str,
    daily_new_words: int,
    learning_goal: str | None = None,
    work_industry: str | None = None,
    selected_topics: list[str] | None = None,
    difficulty_mode: str = "manual",
    learning_difficulty: str | None = None,
) -> UserLanguage:
    existing = await session.execute(
        select(UserLanguage).where(
            UserLanguage.user_id == user_id,
            UserLanguage.language_code == language_code,
            UserLanguage.translation_language == translation_language,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise DuplicateUserLanguageError(
            f"user {user_id} already studies {language_code} -> {translation_language}"
        )

    # The very first language a user adds becomes their current one by
    # default; later additions stay non-current until explicitly switched to.
    has_any = await session.execute(
        select(UserLanguage.id).where(UserLanguage.user_id == user_id).limit(1)
    )
    is_first = has_any.scalar_one_or_none() is None

    user_language = UserLanguage(
        user_id=user_id,
        language_code=language_code,
        translation_language=translation_language,
        level=level,
        daily_new_words=daily_new_words,
        is_current=is_first,
        learning_goal=learning_goal,
        work_industry=work_industry,
        selected_topics=selected_topics or [],
        difficulty_mode=difficulty_mode,
        # learning_difficulty starts out matching the level the learner
        # just picked at onboarding - never the column's own static
        # default, which would silently mismatch whatever CEFR tier they
        # actually chose.
        learning_difficulty=learning_difficulty or level,
    )
    session.add(user_language)
    await session.flush()
    return user_language


async def remove_language(session: AsyncSession, user_language: UserLanguage) -> None:
    """Permanently stop studying this (learning, translation) pair."""
    was_current = user_language.is_current
    user_id = user_language.user_id

    await session.delete(user_language)
    await session.flush()

    if was_current:
        # Promote another language (if any) so the user always has a
        # current one to land on in the main menu.
        remaining = await session.execute(
            select(UserLanguage).where(UserLanguage.user_id == user_id).limit(1)
        )
        next_language = remaining.scalar_one_or_none()
        if next_language is not None:
            next_language.is_current = True
            await session.flush()


async def set_language_enabled(session: AsyncSession, user_language: UserLanguage, enabled: bool) -> UserLanguage:
    user_language.active = enabled
    await session.flush()
    return user_language


async def set_daily_new_words(session: AsyncSession, user_language: UserLanguage, count: int) -> UserLanguage:
    """Section 8: daily new-word count is stored per learning language."""
    user_language.daily_new_words = count
    await session.flush()
    return user_language


async def set_goal(
    session: AsyncSession, user_language: UserLanguage, *, learning_goal: str | None, work_industry: str | None
) -> UserLanguage:
    """Settings-improvements stage section 20: work_industry is only
    meaningful alongside learning_goal == "work" - callers are
    responsible for clearing it when the goal changes away from "work"
    (handlers/settings.py and handlers/start.py both do this explicitly
    rather than this function guessing at the rule)."""
    user_language.learning_goal = learning_goal
    user_language.work_industry = work_industry
    await session.flush()
    return user_language


async def set_topics(session: AsyncSession, user_language: UserLanguage, *, topics: list[str]) -> UserLanguage:
    user_language.selected_topics = topics
    await session.flush()
    return user_language


async def set_manual_difficulty(session: AsyncSession, user_language: UserLanguage, *, level: str) -> UserLanguage:
    """"Уровень сложности изучения языка" manual pick (spec sections 6-9):
    switches to manual mode and stores the chosen CEFR tier - never touches
    `level` (the auto-tracked estimate), which keeps advancing independently
    via services.level_progress_service regardless of this choice."""
    user_language.difficulty_mode = "manual"
    user_language.learning_difficulty = level
    await session.flush()
    return user_language


async def set_automatic_difficulty(session: AsyncSession, user_language: UserLanguage) -> UserLanguage:
    """Switches word generation back onto the auto-tracked estimated level
    (`level`) instead of a fixed manual pick - see effective_difficulty()."""
    user_language.difficulty_mode = "automatic"
    await session.flush()
    return user_language


async def set_translation_language_for_all(session: AsyncSession, *, user_id: int, translation_language: str) -> None:
    """study-flow-rework stage sections 5-6: translation_language must
    always equal interface_language EVERYWHERE - when a user changes their
    interface language in Settings, every existing UserLanguage row's
    translation_language is updated to match, not just newly-added ones."""
    await session.execute(
        update(UserLanguage)
        .where(UserLanguage.user_id == user_id)
        .values(translation_language=translation_language)
    )
    await session.flush()


async def set_active_language(session: AsyncSession, *, user_id: int, user_language_id: int) -> UserLanguage:
    """Mark `user_language_id` as the user's current (menu-visible) language,
    clearing the flag on every other language they study (section 13)."""
    target = await session.get(UserLanguage, user_language_id)
    if target is None or target.user_id != user_id:
        raise ValueError(f"UserLanguage {user_language_id} does not belong to user {user_id}")

    await session.execute(
        update(UserLanguage)
        .where(UserLanguage.user_id == user_id, UserLanguage.id != user_language_id)
        .values(is_current=False)
    )
    target.is_current = True
    await session.flush()
    return target
