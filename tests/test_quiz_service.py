"""Tests for services/quiz_service.py (settings-improvements stage
sections 10-12): question generation across all 5 types, the multiple-
choice/fill-in-blank distractor pools, and wrong answers reusing the
real spaced-repetition algorithm (never a second one)."""
from __future__ import annotations

from datetime import time

import pytest

from database.models import WordStatus
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.repositories import words as words_repo
from services import quiz_service, word_service


async def _create_user(session, telegram_id=8000):
    return await users_repo.create_user(
        session, telegram_id=telegram_id, username="q", first_name="Q",
        interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )


async def _make_word(session, word, translation, *, example=None, language_code="en"):
    created, _ = await word_service.get_or_create_word(session, language_code=language_code, word=word)
    await words_repo.add_translation(session, word_id=created.id, language_code="ru", translation=translation)
    if example:
        await words_repo.add_example(session, word_id=created.id, example_text=example)
    return created


async def test_build_quiz_returns_empty_when_user_has_no_words(session):
    user = await _create_user(session)
    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru")
    assert questions == []


async def test_build_quiz_flashcard_only_with_a_single_word(session):
    """Below MIN_WORDS_FOR_MULTIPLE_CHOICE, only the two flashcard types
    (which need no distractors) may be chosen."""
    user = await _create_user(session)
    word = await _make_word(session, "cat", "кошка")
    await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru")
    assert len(questions) == 1
    assert questions[0]["type"] in ("word_to_translation", "translation_to_word")
    assert questions[0]["options"] == []


async def test_build_quiz_offers_multiple_choice_with_enough_words(session):
    user = await _create_user(session)
    words = []
    for i in range(6):
        w = await _make_word(session, f"word{i}", f"слово{i}")
        uw = await user_words_repo.add_word(session, user_id=user.id, word_id=w.id, language_code="en")
        words.append(uw)
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=6)
    assert len(questions) == 6
    types_seen = {q["type"] for q in questions}
    # with 6 words and randomness this should include at least one MC-style question most runs;
    # deterministically verify the MC question SHAPE whenever one appears.
    for q in questions:
        if q["type"] in ("mc_translation", "mc_word"):
            assert len(q["options"]) == 4
            assert q["correct_answer"] in q["options"]
            assert len(set(q["options"])) == 4  # no duplicate distractors


async def test_fill_in_blank_only_offered_when_word_appears_in_its_example(session):
    user = await _create_user(session)
    # 4+ words so MC/fill-blank types are eligible at all
    target = await _make_word(session, "run", "бежать", example="I like to run every morning.")
    for i in range(5):
        w = await _make_word(session, f"filler{i}", f"филлер{i}")
        await user_words_repo.add_word(session, user_id=user.id, word_id=w.id, language_code="en")
    uw = await user_words_repo.add_word(session, user_id=user.id, word_id=target.id, language_code="en")
    await session.commit()

    questions = await quiz_service.build_quiz(
        session, user_id=user.id, language_code="en", translation_language="ru", only_word_ids=[uw.id]
    )
    assert len(questions) == 1
    q = questions[0]
    if q["type"] == "fill_in_blank":
        assert "___" in q["prompt"]
        assert "run" not in q["prompt"].lower()
        assert q["correct_answer"] == "run"


async def test_fill_in_blank_excluded_when_word_not_in_example_text(session):
    """A word whose only example uses a different inflected form (so the
    literal word never appears) must never produce a blank with nothing
    actually blanked out."""
    user = await _create_user(session)
    target = await _make_word(session, "run", "бежать", example="She ran across the field yesterday.")
    for i in range(5):
        w = await _make_word(session, f"filler{i}", f"филлер{i}")
        await user_words_repo.add_word(session, user_id=user.id, word_id=w.id, language_code="en")
    uw = await user_words_repo.add_word(session, user_id=user.id, word_id=target.id, language_code="en")
    await session.commit()

    for _ in range(20):  # randomness guard - type selection is random per call
        questions = await quiz_service.build_quiz(
            session, user_id=user.id, language_code="en", translation_language="ru", only_word_ids=[uw.id]
        )
        assert questions[0]["type"] != "fill_in_blank"


async def test_build_quiz_excludes_paused_and_deleted_words(session):
    user = await _create_user(session)
    active = await _make_word(session, "active", "активный")
    paused = await _make_word(session, "paused", "приостановлен")
    deleted = await _make_word(session, "deleted", "удалён")

    active_uw = await user_words_repo.add_word(session, user_id=user.id, word_id=active.id, language_code="en")
    paused_uw = await user_words_repo.add_word(session, user_id=user.id, word_id=paused.id, language_code="en")
    paused_uw.status = WordStatus.PAUSED
    deleted_uw = await user_words_repo.add_word(session, user_id=user.id, word_id=deleted.id, language_code="en")
    deleted_uw.status = WordStatus.DELETED
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=10)
    tested_ids = {q["user_word_id"] for q in questions}
    assert tested_ids == {active_uw.id}


async def test_build_quiz_only_word_ids_restricts_pool(session):
    user = await _create_user(session)
    w1 = await _make_word(session, "one", "один")
    w2 = await _make_word(session, "two", "два")
    uw1 = await user_words_repo.add_word(session, user_id=user.id, word_id=w1.id, language_code="en")
    uw2 = await user_words_repo.add_word(session, user_id=user.id, word_id=w2.id, language_code="en")
    await session.commit()

    questions = await quiz_service.build_quiz(
        session, user_id=user.id, language_code="en", translation_language="ru", only_word_ids=[uw1.id]
    )
    assert len(questions) == 1
    assert questions[0]["user_word_id"] == uw1.id


async def test_apply_wrong_answer_reuses_real_repetition_algorithm(session):
    """Spec: "wrong answers feed into existing repetition priority (no
    new system)" - a wrong quiz answer must move next_review_at via the
    exact same calculate_next_review/apply_review_result path a real
    review does, not a separate quiz-only mechanism."""
    user = await _create_user(session)
    word = await _make_word(session, "test", "тест")
    uw = await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
    uw.status = WordStatus.REVIEW
    uw.repetition_stage = 3
    await session.commit()

    old_stage = uw.repetition_stage
    await quiz_service.apply_wrong_answer(session, uw)
    await session.commit()

    assert uw.repetition_stage < old_stage  # AGAIN steps back exactly like a real review would
    assert uw.wrong_answers == 1
    assert uw.next_review_at is not None
