"""Spaced-repetition algorithm (spec section 11).

TODO(stage-7): implement once database.models.UserWord exists.

This module intentionally defines only the interface and the schedule it
must follow, so the algorithm can be swapped for SM-2/FSRS later without
touching callers (handlers/review.py, services/learning_service.py).

Planned interval ladder, in days, ending in MASTERED:
    NEW -> 1 -> 3 -> 7 -> 14 -> 30 -> 60 -> MASTERED

On each review the user answers one of four grades, which the algorithm
below is expected to turn into a new interval:
    "again"  (😣 Не помню)       - reset to an earlier step, shorter interval
    "hard"   (😐 С трудом)        - small increase over the current interval
    "good"   (🙂 Помню)           - normal increase (advance one ladder step)
    "easy"   (😎 Очень легко)     - larger increase (skip ahead on the ladder)
"""
from __future__ import annotations

import enum


class ReviewGrade(str, enum.Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


INTERVAL_LADDER_DAYS: tuple[int, ...] = (1, 3, 7, 14, 30, 60)


def next_interval_days(*, current_step_index: int, grade: ReviewGrade) -> int:
    """Compute the next review interval, in days, given where a word
    currently sits on the ladder and how well the user recalled it.

    TODO(stage-7): implement against a real UserWord.repetitions /
    UserWord.difficulty_score once those exist; wire into
    services/learning_service.py's review flow.
    """
    raise NotImplementedError("Repetition scheduling arrives in Stage 7 (Repetition)")
