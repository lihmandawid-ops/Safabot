"""The structured, numeric learner profile handed to AI word generation
(statistics/progress stage, spec sections 29-30): DeepSeek must receive
actual measured numbers - current level, difficulty, accuracy, recent
review results, active/learned word counts, weak/strong words - rather
than inventing its own opinion of the learner's level from nothing.

Reuses the exact same aggregate queries services/progress_service.py uses
for 📊 Мой прогресс (database/repositories/progress.py) - one source of
truth for "how is this learner doing", read by both the human-facing
screen and the AI prompt.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserLanguage, WordStatus
from database.repositories import progress as progress_repo
from services.level_progress_service import effective_difficulty
from services.progress_service import recent_performance_trend

_RECENT_WINDOW = 20  # spec: "тренд за последние 10-20 результатов"
_WEAK_STRONG_LIMIT = 5


@dataclass(frozen=True)
class LearnerProfile:
    current_level: str
    difficulty: str
    accuracy: float
    review_success_rate: float
    active_words: int
    learned_words: int
    weak_words: list[str] = field(default_factory=list)
    strong_words: list[str] = field(default_factory=list)
    recent_performance: str = "insufficient_data"

    def as_prompt_dict(self) -> dict:
        """A plain dict, safe to serialize into the AI prompt text - never
        includes anything beyond these measured numbers/words."""
        return asdict(self)


async def build_learner_profile(
    session: AsyncSession, *, user_id: int, user_language: UserLanguage
) -> LearnerProfile:
    """Never raises - a broken profile read must not block word
    generation, which already tolerates a missing/failed AI call entirely
    (word_generation_service degrades to 'generated fewer words'). Callers
    that can't build a profile simply generate without one, same as
    before this feature existed."""
    language_code = user_language.language_code

    status_counts = await progress_repo.status_counts(session, user_id=user_id, language_code=language_code)
    active_words = status_counts.get(WordStatus.LEARNING, 0) + status_counts.get(WordStatus.REVIEW, 0)
    learned_words = status_counts.get(WordStatus.MASTERED, 0)

    _, correct, wrong = await progress_repo.lifetime_totals(session, user_id=user_id, language_code=language_code)
    total = correct + wrong
    accuracy = (correct / total) if total > 0 else 0.0

    recent_deltas = await progress_repo.recent_review_deltas(
        session, user_id=user_id, language_code=language_code, limit=_RECENT_WINDOW
    )
    recent_correct = sum(c for c, _ in recent_deltas)
    recent_wrong = sum(w for _, w in recent_deltas)
    recent_total = recent_correct + recent_wrong
    review_success_rate = (recent_correct / recent_total) if recent_total > 0 else accuracy

    weak_words = await progress_repo.weakest_words(
        session, user_id=user_id, language_code=language_code, limit=_WEAK_STRONG_LIMIT
    )
    strong_words = await progress_repo.strongest_words(
        session, user_id=user_id, language_code=language_code, limit=_WEAK_STRONG_LIMIT
    )

    return LearnerProfile(
        current_level=user_language.level,
        difficulty=effective_difficulty(user_language),
        accuracy=round(accuracy, 3),
        review_success_rate=round(review_success_rate, 3),
        active_words=active_words,
        learned_words=learned_words,
        weak_words=weak_words,
        strong_words=strong_words,
        recent_performance=recent_performance_trend(recent_deltas),
    )
