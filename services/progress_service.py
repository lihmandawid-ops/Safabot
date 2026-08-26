"""📊 Мой прогресс (statistics/progress stage): composes existing,
already-tracked numbers into one screen. Adds no new scoring system - every
figure here is either read straight off UserWord's own cumulative counters
(spec: "проверить, какие из этих данных уже существуют"), or off ReviewLog
(the one genuinely new, minimal, additive table this stage introduces - see
its docstring in database/models.py for why period-based stats needed it).

Never raises: a broken stats read must not break anything else (spec:
"статистика - дополнительный слой, не должна ломать базовый функционал
если упадёт"). Callers should still guard with try/except at the handler
boundary for defense in depth, but every query here is a plain aggregate
with no external calls, so failure is only ever a DB-layer issue.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserLanguage, WordStatus
from database.repositories import progress as progress_repo
from services.level_progress_service import LevelProgress, get_level_progress
from utils.time import local_day_bounds, utc_now

_TREND_WINDOW = 10  # spec sections 26-28: never judge a trend on fewer than this many results


@dataclass(frozen=True)
class PeriodStats:
    new_words: int
    reviews: int
    correct: int
    wrong: int

    @property
    def accuracy(self) -> float:
        total = self.correct + self.wrong
        return (self.correct / total) if total > 0 else 0.0


@dataclass(frozen=True)
class ProgressSnapshot:
    status_counts: dict[str, int]
    well_consolidated: int
    in_progress: int
    difficult: int
    total_reviews: int
    total_correct: int
    total_wrong: int
    today: PeriodStats
    last_7_days: PeriodStats
    last_30_days: PeriodStats
    level_progress: LevelProgress

    @property
    def total_words(self) -> int:
        return sum(count for status, count in self.status_counts.items() if status != WordStatus.DELETED)

    @property
    def mastered_count(self) -> int:
        return self.status_counts.get(WordStatus.MASTERED, 0)

    @property
    def overall_accuracy(self) -> float:
        total = self.total_correct + self.total_wrong
        return (self.total_correct / total) if total > 0 else 0.0


async def build_snapshot(
    session: AsyncSession, *, user_id: int, user_language: UserLanguage, timezone: str, now=None
) -> ProgressSnapshot:
    now = now if now is not None else utc_now()
    language_code = user_language.language_code

    status_counts = await progress_repo.status_counts(session, user_id=user_id, language_code=language_code)
    buckets = await progress_repo.consolidation_buckets(session, user_id=user_id, language_code=language_code)
    total_reviews, total_correct, total_wrong = await progress_repo.lifetime_totals(
        session, user_id=user_id, language_code=language_code
    )

    today_start, _ = local_day_bounds(now, timezone)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    today = await _period_stats(session, user_id=user_id, language_code=language_code, since=today_start)
    last_7 = await _period_stats(session, user_id=user_id, language_code=language_code, since=week_start)
    last_30 = await _period_stats(session, user_id=user_id, language_code=language_code, since=month_start)

    level_progress = await get_level_progress(session, user_language=user_language)

    return ProgressSnapshot(
        status_counts=status_counts,
        well_consolidated=buckets["well_consolidated"],
        in_progress=buckets["in_progress"],
        difficult=buckets["difficult"],
        total_reviews=total_reviews,
        total_correct=total_correct,
        total_wrong=total_wrong,
        today=today,
        last_7_days=last_7,
        last_30_days=last_30,
        level_progress=level_progress,
    )


async def _period_stats(session: AsyncSession, *, user_id: int, language_code: str, since) -> PeriodStats:
    new_words = await progress_repo.new_words_since(
        session, user_id=user_id, language_code=language_code, since=since
    )
    reviews, correct, wrong = await progress_repo.review_totals_since(
        session, user_id=user_id, language_code=language_code, since=since
    )
    return PeriodStats(new_words=new_words, reviews=reviews, correct=correct, wrong=wrong)


def recent_performance_trend(deltas: list[tuple[int, int]]) -> str:
    """"improving" / "declining" / "stable" / "insufficient_data" - spec
    sections 26-28: adaptive difficulty must never react to a single good
    or bad result, only a trend over the last 10-20 results. `deltas` is
    most-recent-first (progress_repo.recent_review_deltas's own order);
    splits the window in half and compares accuracy between the two
    halves rather than reacting to any individual result."""
    if len(deltas) < _TREND_WINDOW:
        return "insufficient_data"

    half = len(deltas) // 2
    recent_half = deltas[:half]
    older_half = deltas[half:]

    def _accuracy(rows: list[tuple[int, int]]) -> float | None:
        correct = sum(c for c, _ in rows)
        wrong = sum(w for _, w in rows)
        total = correct + wrong
        return (correct / total) if total > 0 else None

    recent_acc = _accuracy(recent_half)
    older_acc = _accuracy(older_half)
    if recent_acc is None or older_acc is None:
        return "insufficient_data"

    delta = recent_acc - older_acc
    if delta >= 0.15:
        return "improving"
    if delta <= -0.15:
        return "declining"
    return "stable"
