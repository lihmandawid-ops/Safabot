"""Large test matrix for services/repetition_service.py (learning-core
stage, section 30): every stage (0-6) against every grade, no negative
stages, MASTERED reached, interval math, and midnight crossing.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from database.models import WordStatus
from services.repetition_service import (
    MASTERED_STAGE,
    STAGE_INTERVALS,
    ReviewGrade,
    calculate_next_review,
    clamp_difficulty,
)

NOW = datetime(2026, 6, 15, 12, 0, 0)


def _interval_for(stage: int) -> int:
    return STAGE_INTERVALS[stage]


# ---------------------------------------------------------------------
# NEW word (stage 0) x each grade
# ---------------------------------------------------------------------

def test_new_word_again_stays_at_stage_zero_due_immediately():
    r = calculate_next_review(0, 0, ReviewGrade.AGAIN, now=NOW)
    assert r.new_stage == 0
    assert r.new_interval_days == 0
    assert r.next_review_at == NOW
    assert r.new_status == WordStatus.LEARNING
    assert r.wrong_delta == 1
    assert r.correct_delta == 0


def test_new_word_hard_stays_at_stage_zero_short_interval():
    r = calculate_next_review(0, 0, ReviewGrade.HARD, now=NOW)
    assert r.new_stage == 0
    assert r.new_interval_days >= 1
    assert r.new_status == WordStatus.LEARNING
    assert r.correct_delta == 0
    assert r.wrong_delta == 0


def test_new_word_good_advances_to_stage_one():
    r = calculate_next_review(0, 0, ReviewGrade.GOOD, now=NOW)
    assert r.new_stage == 1
    assert r.new_interval_days == _interval_for(1)
    assert r.next_review_at == NOW + timedelta(days=1)
    assert r.new_status == WordStatus.REVIEW
    assert r.correct_delta == 1


def test_new_word_easy_advances_two_stages():
    r = calculate_next_review(0, 0, ReviewGrade.EASY, now=NOW)
    assert r.new_stage == 2
    assert r.new_interval_days == _interval_for(2)
    assert r.new_status == WordStatus.REVIEW
    assert r.correct_delta == 1


# ---------------------------------------------------------------------
# Full matrix: every active stage (1-6) x every grade
# ---------------------------------------------------------------------

@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5, 6])
class TestEveryActiveStage:
    def test_again_steps_back_one_stage(self, stage):
        r = calculate_next_review(stage, STAGE_INTERVALS[stage], ReviewGrade.AGAIN, now=NOW)
        assert r.new_stage == stage - 1
        assert r.new_interval_days == STAGE_INTERVALS[stage - 1]
        assert r.wrong_delta == 1
        assert r.correct_delta == 0

    def test_hard_keeps_the_same_stage(self, stage):
        r = calculate_next_review(stage, STAGE_INTERVALS[stage], ReviewGrade.HARD, now=NOW)
        assert r.new_stage == stage
        assert r.correct_delta == 0
        assert r.wrong_delta == 0

    def test_hard_interval_is_between_current_and_good(self, stage):
        current_interval = STAGE_INTERVALS[stage]
        hard = calculate_next_review(stage, current_interval, ReviewGrade.HARD, now=NOW)
        good = calculate_next_review(stage, current_interval, ReviewGrade.GOOD, now=NOW)
        # MASTERED (stage 6 + GOOD) has no interval at all - it's the
        # ultimate "longer than anything else", not literally 0 days.
        good_days = good.new_interval_days if good.next_review_at is not None else float("inf")
        assert hard.new_interval_days > current_interval
        assert hard.new_interval_days <= good_days

    def test_good_advances_one_stage_or_masters(self, stage):
        r = calculate_next_review(stage, STAGE_INTERVALS[stage], ReviewGrade.GOOD, now=NOW)
        if stage == 6:
            assert r.new_stage == MASTERED_STAGE
            assert r.new_status == WordStatus.MASTERED
            assert r.next_review_at is None
        else:
            assert r.new_stage == stage + 1
            assert r.new_interval_days == STAGE_INTERVALS[stage + 1]
            assert r.new_status == WordStatus.REVIEW
        assert r.correct_delta == 1

    def test_easy_advances_two_stages_or_masters(self, stage):
        r = calculate_next_review(stage, STAGE_INTERVALS[stage], ReviewGrade.EASY, now=NOW)
        expected_stage = min(stage + 2, MASTERED_STAGE)
        assert r.new_stage == expected_stage
        if expected_stage == MASTERED_STAGE:
            assert r.new_status == WordStatus.MASTERED
            assert r.next_review_at is None
        else:
            assert r.new_interval_days == STAGE_INTERVALS[expected_stage]
        assert r.correct_delta == 1

    def test_easy_interval_is_never_shorter_than_good(self, stage):
        current_interval = STAGE_INTERVALS[stage]
        good = calculate_next_review(stage, current_interval, ReviewGrade.GOOD, now=NOW)
        easy = calculate_next_review(stage, current_interval, ReviewGrade.EASY, now=NOW)
        good_days = good.new_interval_days if good.next_review_at is not None else float("inf")
        easy_days = easy.new_interval_days if easy.next_review_at is not None else float("inf")
        assert easy_days >= good_days


# ---------------------------------------------------------------------
# Never a negative stage
# ---------------------------------------------------------------------

@pytest.mark.parametrize("grade", list(ReviewGrade))
def test_stage_never_goes_negative(grade):
    r = calculate_next_review(0, 0, grade, now=NOW)
    assert r.new_stage >= 0


def test_repeated_again_never_goes_negative():
    stage, interval = 2, STAGE_INTERVALS[2]
    for _ in range(10):
        r = calculate_next_review(stage, interval, ReviewGrade.AGAIN, now=NOW)
        assert r.new_stage >= 0
        stage, interval = r.new_stage, r.new_interval_days


# ---------------------------------------------------------------------
# MASTERED
# ---------------------------------------------------------------------

def test_good_from_stage_six_reaches_mastered():
    r = calculate_next_review(6, STAGE_INTERVALS[6], ReviewGrade.GOOD, now=NOW)
    assert r.new_status == WordStatus.MASTERED
    assert r.new_stage == MASTERED_STAGE
    assert r.next_review_at is None
    assert r.new_interval_days == 0


def test_easy_from_stage_five_reaches_mastered():
    r = calculate_next_review(5, STAGE_INTERVALS[5], ReviewGrade.EASY, now=NOW)
    assert r.new_status == WordStatus.MASTERED
    assert r.next_review_at is None


def test_again_on_a_word_at_mastered_stage_returns_to_the_ladder():
    """A forgotten MASTERED word re-enters near the top, not from scratch."""
    r = calculate_next_review(MASTERED_STAGE, 0, ReviewGrade.AGAIN, now=NOW)
    assert r.new_stage == MASTERED_STAGE - 1
    assert r.new_status == WordStatus.REVIEW


# ---------------------------------------------------------------------
# Interval math sanity
# ---------------------------------------------------------------------

def test_intervals_strictly_increase_along_the_ladder():
    values = [STAGE_INTERVALS[s] for s in sorted(STAGE_INTERVALS)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


@pytest.mark.parametrize("stage", [0, 1, 2, 3, 4, 5, 6])
def test_next_review_at_matches_new_interval_days(stage):
    r = calculate_next_review(stage, STAGE_INTERVALS[stage], ReviewGrade.GOOD, now=NOW)
    if r.next_review_at is not None:
        assert (r.next_review_at - NOW).days == r.new_interval_days


# ---------------------------------------------------------------------
# Midnight crossing: interval math must not depend on time-of-day
# ---------------------------------------------------------------------

@pytest.mark.parametrize("now", [
    datetime(2026, 1, 31, 23, 59, 0),
    datetime(2026, 2, 28, 23, 59, 59),  # crosses into a leap-safe March 1st check below
    datetime(2026, 12, 31, 23, 59, 0),  # crosses into a new year
])
def test_interval_addition_crosses_midnight_correctly(now):
    r = calculate_next_review(1, STAGE_INTERVALS[1], ReviewGrade.GOOD, now=now)
    assert r.next_review_at == now + timedelta(days=STAGE_INTERVALS[2])
    assert r.next_review_at > now


def test_leap_year_day_arithmetic():
    now = datetime(2028, 2, 27, 10, 0, 0)  # 2028 is a leap year
    r = calculate_next_review(2, STAGE_INTERVALS[2], ReviewGrade.GOOD, now=now)
    assert r.next_review_at.date() == datetime(2028, 3, 5).date()  # Feb has 29 days in 2028


# ---------------------------------------------------------------------
# Difficulty clamping
# ---------------------------------------------------------------------

def test_difficulty_clamped_to_range():
    assert clamp_difficulty(-10) == 0.0
    assert clamp_difficulty(10) == 5.0
    assert clamp_difficulty(2.5) == 2.5


def test_unknown_grade_raises():
    with pytest.raises(ValueError):
        calculate_next_review(0, 0, "not-a-grade", now=NOW)  # type: ignore[arg-type]
