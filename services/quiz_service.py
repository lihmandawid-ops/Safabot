"""🧠 Викторина (settings-improvements stage sections 10-12; quiz-format
stage: standardized to exactly ONE format - a foreign word plus exactly 4
translation options, one correct). Builds a quiz out of the user's own
words and, for a wrong answer, feeds it back into the SAME spaced-
repetition algorithm the normal 📚/🔄 flow uses - there is deliberately no
second scheduling system and no new AI call here, only a different way of
presenting words the user already has.

Quiz state itself is NOT a database table (unlike LearningSession): it's
a short-lived, disposable list of pre-generated questions that lives in
context.user_data (see handlers/quiz.py), the same pattern already used
for ⭐ Мои слова's page cache and bulk selection - it still survives a
bot restart via PicklePersistence, but doesn't need its own migration or
repository for something this transient.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserWord, WordStatus
from database.repositories import learning as learning_repo
from database.repositories import user_words as user_words_repo
from services import pronunciation_service
from services.repetition_service import ReviewGrade, calculate_next_review
from utils.time import utc_now

DEFAULT_QUIZ_LENGTH = 10
OPTION_COUNT = 4
# Building even one question needs the tested word's own translation plus
# 3 distinct DISTRACTOR translations from other words - never fewer than
# the full option count, and never padded with fake/duplicate options.
MIN_WORDS_FOR_QUESTION = OPTION_COUNT

_QUIZZABLE_STATUSES = [WordStatus.NEW, WordStatus.LEARNING, WordStatus.REVIEW, WordStatus.MASTERED]


@dataclass
class QuizQuestion:
    user_word_id: int
    correct_answer: str
    options: list[str] = field(default_factory=list)
    # The target-language word being tested, and its pronunciation - cache
    # -only (global pronunciation rule section 46): quiz questions are
    # built in a batch, and a live AI backfill call per question here
    # would both slow quiz start down and risk showing the answer away
    # before it's earned.
    word: str = ""
    pronunciation: str | None = None

    def to_dict(self) -> dict:
        return {
            "user_word_id": self.user_word_id,
            "correct_answer": self.correct_answer,
            "options": self.options,
            "word": self.word,
            "pronunciation": self.pronunciation,
        }


def _translation_for(user_word: UserWord, translation_language: str) -> str | None:
    """Only ever a translation into the user's OWN translation_language -
    never a different language's row used as a silent fallback (quiz-
    format stage section 4: no ru/en fallback)."""
    matches = [tr.translation for tr in user_word.word.translations if tr.language_code == translation_language]
    return matches[0] if matches else None


def _distractor_translations(
    target: UserWord, pool: list[UserWord], translation_language: str, n: int, *, exclude: str
) -> list[str]:
    others = [uw for uw in pool if uw.id != target.id]
    random.shuffle(others)
    seen: set[str] = {exclude}
    out: list[str] = []
    for uw in others:
        tr = _translation_for(uw, translation_language)
        if tr and tr not in seen:
            seen.add(tr)
            out.append(tr)
        if len(out) >= n:
            break
    return out


def _build_question(
    user_word: UserWord, translation: str, pool: list[UserWord], translation_language: str
) -> QuizQuestion | None:
    """Foreign word shown, 4 translation options (one correct) - the ONLY
    quiz format (quiz-format stage sections 1-4). Returns None if the pool
    can't yield 3 distinct distractor translations - never pads with fake
    or duplicate options."""
    word_text = user_word.word.word
    distractors = _distractor_translations(
        user_word, pool, translation_language, OPTION_COUNT - 1, exclude=translation
    )
    if len(distractors) < OPTION_COUNT - 1:
        return None

    options = distractors + [translation]
    random.shuffle(options)
    pronunciation = pronunciation_service.format_pronunciation(user_word.word)
    return QuizQuestion(
        user_word.id, correct_answer=translation, options=options, word=word_text, pronunciation=pronunciation
    )


async def build_quiz(
    session: AsyncSession,
    *,
    user_id: int,
    language_code: str,
    translation_language: str,
    count: int = DEFAULT_QUIZ_LENGTH,
    only_word_ids: list[int] | None = None,
) -> list[dict]:
    """Picks up to `count` of the user's own words (excluding
    PAUSED/DELETED - spec: "using only the user's own words") and builds
    one standard-format question per word. `only_word_ids` restricts the
    pool to those ids - used by 🔁 Повторить ошибки to build a quiz out of
    just the words missed last time. A word that can't form 4 distinct
    options (not enough other translated words in the pool) is silently
    skipped - never padded with fake distractors."""
    # `pool` is the FULL quizzable vocabulary - always the distractor
    # source, even for a `only_word_ids`-restricted retry-mistakes quiz
    # (spec section 8: the "🔁 Повторить ошибки" feature must keep
    # working even when only 1-3 words were missed, which alone could
    # never yield 3 distinct distractors on their own).
    pool = await user_words_repo.get_user_words(
        session, user_id=user_id, language_code=language_code, statuses=_QUIZZABLE_STATUSES
    )
    pool = [uw for uw in pool if uw.word.translations]
    if len(pool) < MIN_WORDS_FOR_QUESTION:
        return []

    if only_word_ids is not None:
        wanted = set(only_word_ids)
        to_ask = [uw for uw in pool if uw.id in wanted]
    else:
        shuffled = list(pool)
        random.shuffle(shuffled)
        to_ask = shuffled[: max(count, 0)]

    questions: list[QuizQuestion] = []
    for user_word in to_ask:
        translation = _translation_for(user_word, translation_language)
        if translation is None:
            continue
        question = _build_question(user_word, translation, pool, translation_language)
        if question is not None:
            questions.append(question)

    return [q.to_dict() for q in questions]


async def apply_wrong_answer(session: AsyncSession, user_word: UserWord, *, now=None) -> None:
    """Spec: "wrong answers feed into existing repetition priority (no
    new system)" - reuses the exact same repetition_service +
    apply_review_result path the normal review flow uses, with an AGAIN
    grade, so a missed quiz question moves the word's next_review_at
    sooner exactly like missing it in a real review would. A correct
    quiz answer deliberately does NOT touch the schedule - the quiz is a
    supplementary practice tool, not an alternate way to advance it."""
    now = now if now is not None else utc_now()
    result = calculate_next_review(user_word.repetition_stage, user_word.interval_days, ReviewGrade.AGAIN, now=now)
    await learning_repo.apply_review_result(session, user_word, result, now=now)
