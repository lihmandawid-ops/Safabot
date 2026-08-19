"""Spaced-repetition algorithm (learning-core stage, sections 1-2, 4).

This is the ONLY place that turns a review grade into a new stage/
interval/status - handlers and learning_service must never compute this
themselves. calculate_next_review() is a pure function (no DB, no I/O)
so the whole algorithm can be swapped for SM-2/FSRS later by replacing
this one function's body; every caller only ever sees a RepetitionResult.

Stage ladder (stage -> interval in days), matching the spec exactly:
    0 -> today (0)      1 -> 1      2 -> 3       3 -> 7
    4 -> 14             5 -> 30     6 -> 60      7 -> MASTERED (terminal)

Grades, from a 4-button word card:
    AGAIN (😣 Не помню)       - step back one stage, due again soon
    HARD  (😐 С трудом)        - same stage, interval nudged up moderately
    GOOD  (🙂 Помню)           - advance one stage, normal next interval
    EASY  (😎 Очень легко)     - advance two stages, may reach MASTERED
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

from database.models import WordStatus
from utils.time import utc_now


class ReviewGrade(str, enum.Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


# Stage -> interval in days. Stage MASTERED_STAGE itself has no interval:
# a MASTERED word is not scheduled for further review.
STAGE_INTERVALS: dict[int, int] = {0: 0, 1: 1, 2: 3, 3: 7, 4: 14, 5: 30, 6: 60}
MAX_ACTIVE_STAGE = max(STAGE_INTERVALS)  # 6
MASTERED_STAGE = MAX_ACTIVE_STAGE + 1  # 7

DIFFICULTY_MIN = 0.0
DIFFICULTY_MAX = 5.0
_AGAIN_DIFFICULTY_DELTA = 0.2
_HARD_DIFFICULTY_DELTA = 0.1
_EASY_DIFFICULTY_DELTA = -0.1
_HARD_MULTIPLIER = 1.3


@dataclass(frozen=True)
class RepetitionResult:
    new_stage: int
    new_interval_days: int
    next_review_at: datetime | None  # None only when new_status is MASTERED
    new_status: str
    correct_delta: int
    wrong_delta: int
    difficulty_delta: float


def _status_for_stage(stage: int) -> str:
    if stage <= 0:
        return WordStatus.LEARNING
    if stage >= MASTERED_STAGE:
        return WordStatus.MASTERED
    return WordStatus.REVIEW


def _hard_interval(current_interval_days: int) -> int:
    """Moderate bump over the CURRENT interval (not the stage's ladder
    value) - deliberately less than what GOOD would give from the same
    stage, since "hard" is weaker recall than "good", not stronger."""
    if current_interval_days <= 0:
        return 1
    return max(current_interval_days + 1, round(current_interval_days * _HARD_MULTIPLIER))


def calculate_next_review(
    current_stage: int,
    current_interval_days: int,
    grade: ReviewGrade,
    *,
    now: datetime | None = None,
) -> RepetitionResult:
    """Pure: given where a word sits on the ladder and how the user rated
    their recall, compute where it goes next. Never touches the database -
    callers (services/learning_service.py) apply the result to a UserWord row.
    """
    now = now if now is not None else utc_now()
    current_stage = max(0, min(current_stage, MASTERED_STAGE))

    if grade == ReviewGrade.AGAIN:
        new_stage = max(0, current_stage - 1)
        new_interval = STAGE_INTERVALS[new_stage]
        return RepetitionResult(
            new_stage=new_stage,
            new_interval_days=new_interval,
            next_review_at=now + timedelta(days=new_interval),
            new_status=_status_for_stage(new_stage),
            correct_delta=0,
            wrong_delta=1,
            difficulty_delta=_AGAIN_DIFFICULTY_DELTA,
        )

    if grade == ReviewGrade.HARD:
        new_stage = min(current_stage, MAX_ACTIVE_STAGE)  # HARD never operates on an already-MASTERED word's stage
        new_interval = _hard_interval(current_interval_days)
        return RepetitionResult(
            new_stage=new_stage,
            new_interval_days=new_interval,
            next_review_at=now + timedelta(days=new_interval),
            new_status=_status_for_stage(new_stage),
            correct_delta=0,
            wrong_delta=0,
            difficulty_delta=_HARD_DIFFICULTY_DELTA,
        )

    if grade == ReviewGrade.GOOD:
        new_stage = min(current_stage + 1, MASTERED_STAGE)
    elif grade == ReviewGrade.EASY:
        new_stage = min(current_stage + 2, MASTERED_STAGE)
    else:  # pragma: no cover - exhaustive enum guard
        raise ValueError(f"Unknown review grade: {grade!r}")

    if new_stage >= MASTERED_STAGE:
        return RepetitionResult(
            new_stage=MASTERED_STAGE,
            new_interval_days=0,
            next_review_at=None,
            new_status=WordStatus.MASTERED,
            correct_delta=1,
            wrong_delta=0,
            difficulty_delta=_EASY_DIFFICULTY_DELTA if grade == ReviewGrade.EASY else 0.0,
        )

    new_interval = STAGE_INTERVALS[new_stage]
    return RepetitionResult(
        new_stage=new_stage,
        new_interval_days=new_interval,
        next_review_at=now + timedelta(days=new_interval),
        new_status=_status_for_stage(new_stage),
        correct_delta=1,
        wrong_delta=0,
        difficulty_delta=_EASY_DIFFICULTY_DELTA if grade == ReviewGrade.EASY else 0.0,
    )


def clamp_difficulty(value: float) -> float:
    return max(DIFFICULTY_MIN, min(DIFFICULTY_MAX, value))
