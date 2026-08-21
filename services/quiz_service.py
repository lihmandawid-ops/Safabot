"""🏆 Викторина (settings-improvements stage sections 10-12): builds a
quiz out of the user's own words and, for a wrong answer, feeds it back
into the SAME spaced-repetition algorithm the normal 📚/🔄 flow uses -
there is deliberately no second scheduling system and no new AI call
here, only a different way of presenting words the user already has.

Quiz state itself is NOT a database table (unlike LearningSession): it's
a short-lived, disposable list of pre-generated questions that lives in
context.user_data (see handlers/quiz.py), the same pattern already used
for ⭐ Мои слова's page cache and bulk selection - it still survives a
bot restart via PicklePersistence, but doesn't need its own migration or
repository for something this transient.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserWord, WordStatus
from database.repositories import learning as learning_repo
from database.repositories import user_words as user_words_repo
from services.repetition_service import ReviewGrade, calculate_next_review
from utils.time import utc_now

DEFAULT_QUIZ_LENGTH = 10
MIN_WORDS_FOR_MULTIPLE_CHOICE = 4
_OPTION_COUNT = 4

# Flashcard-style types are self-assessed (word/translation -> reveal ->
# "did I know it?") and work with as few as 1 word. The other three need
# distractors from other words, so they're only offered once the user's
# pool is big enough to build real wrong options from - never fake ones.
_FLASHCARD_TYPES = ("word_to_translation", "translation_to_word")
_CHOICE_TYPES = ("mc_translation", "mc_word", "fill_in_blank")

_QUIZZABLE_STATUSES = [WordStatus.NEW, WordStatus.LEARNING, WordStatus.REVIEW, WordStatus.MASTERED]


@dataclass
class QuizQuestion:
    user_word_id: int
    type: str
    prompt: str
    correct_answer: str
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "user_word_id": self.user_word_id,
            "type": self.type,
            "prompt": self.prompt,
            "correct_answer": self.correct_answer,
            "options": self.options,
        }


def _translation_for(user_word: UserWord, translation_language: str) -> str | None:
    matches = [tr.translation for tr in user_word.word.translations if tr.language_code == translation_language]
    if matches:
        return matches[0]
    return user_word.word.translations[0].translation if user_word.word.translations else None


def _blank_out(example_text: str, word: str) -> str | None:
    """Replaces the first whole-word, case-insensitive occurrence of
    `word` in `example_text` with "___". Returns None if the word doesn't
    literally appear (e.g. the example only uses an inflected form) - a
    fill-in-blank question with nothing actually blanked would be
    useless, so callers must skip that type for this word instead."""
    pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    if not pattern.search(example_text):
        return None
    return pattern.sub("___", example_text, count=1)


def _distractor_translations(target: UserWord, pool: list[UserWord], translation_language: str, n: int) -> list[str]:
    others = [uw for uw in pool if uw.id != target.id]
    random.shuffle(others)
    seen: set[str] = set()
    out: list[str] = []
    for uw in others:
        tr = _translation_for(uw, translation_language)
        if tr and tr not in seen:
            seen.add(tr)
            out.append(tr)
        if len(out) >= n:
            break
    return out


def _distractor_words(target: UserWord, pool: list[UserWord], n: int) -> list[str]:
    others = [uw for uw in pool if uw.id != target.id]
    random.shuffle(others)
    seen: set[str] = set()
    out: list[str] = []
    for uw in others:
        w = uw.word.word
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= n:
            break
    return out


def _available_types(user_word: UserWord, pool_size: int, has_fill_blank_example: bool) -> list[str]:
    types = list(_FLASHCARD_TYPES)
    if pool_size >= MIN_WORDS_FOR_MULTIPLE_CHOICE:
        types.append("mc_translation")
        types.append("mc_word")
        if has_fill_blank_example:
            types.append("fill_in_blank")
    return types


def _build_question(
    user_word: UserWord, translation: str, qtype: str, pool: list[UserWord], translation_language: str
) -> QuizQuestion:
    word_text = user_word.word.word

    if qtype == "word_to_translation":
        return QuizQuestion(user_word.id, qtype, prompt=word_text, correct_answer=translation)
    if qtype == "translation_to_word":
        return QuizQuestion(user_word.id, qtype, prompt=translation, correct_answer=word_text)

    if qtype == "mc_translation":
        distractors = _distractor_translations(user_word, pool, translation_language, _OPTION_COUNT - 1)
        options = distractors + [translation]
        random.shuffle(options)
        return QuizQuestion(user_word.id, qtype, prompt=word_text, correct_answer=translation, options=options)

    if qtype == "mc_word":
        distractors = _distractor_words(user_word, pool, _OPTION_COUNT - 1)
        options = distractors + [word_text]
        random.shuffle(options)
        return QuizQuestion(user_word.id, qtype, prompt=translation, correct_answer=word_text, options=options)

    # fill_in_blank
    blanked = _blank_out(user_word.word.examples[0].example_text, word_text)
    distractors = _distractor_words(user_word, pool, _OPTION_COUNT - 1)
    options = distractors + [word_text]
    random.shuffle(options)
    return QuizQuestion(user_word.id, qtype, prompt=blanked, correct_answer=word_text, options=options)


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
    PAUSED/DELETED - spec: "using only the user's own words") and gives
    each one a randomly chosen question type. `only_word_ids` restricts
    the pool to those ids - used by 🔁 Повторить ошибки to build a
    quiz out of just the words missed last time."""
    pool = await user_words_repo.get_user_words(
        session, user_id=user_id, language_code=language_code, statuses=_QUIZZABLE_STATUSES
    )
    pool = [uw for uw in pool if uw.word.translations]
    if only_word_ids is not None:
        wanted = set(only_word_ids)
        pool = [uw for uw in pool if uw.id in wanted]
    if not pool:
        return []

    random.shuffle(pool)
    selected = pool[: max(count, 0)] if only_word_ids is None else pool

    questions: list[QuizQuestion] = []
    for user_word in selected:
        translation = _translation_for(user_word, translation_language)
        if translation is None:
            continue
        has_example = bool(user_word.word.examples) and _blank_out(user_word.word.examples[0].example_text, user_word.word.word) is not None
        qtype = random.choice(_available_types(user_word, len(pool), has_example))
        questions.append(_build_question(user_word, translation, qtype, pool, translation_language))

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
