"""Tests for services/quiz_service.py (quiz-format stage: standardized to
exactly ONE format - a foreign word plus exactly 4 translation options,
one correct, in the user's own translation_language - no flashcard
reveal, no word-choice direction, no fill-in-blank, no difficulty scale).
Wrong answers reuse the real spaced-repetition algorithm (never a second
one)."""
from __future__ import annotations

from datetime import time

from database.models import WordStatus
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.repositories import words as words_repo
from services import quiz_service, word_service


async def _create_user(session, telegram_id=8000):
    return await users_repo.create_user(
        session, telegram_id=telegram_id, username="q", first_name="Q",
        interface_language="ru", timezone="UTC", level="a1", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )


async def _make_word(session, word, translation, *, translation_language="ru", language_code="en"):
    created, _ = await word_service.get_or_create_word(session, language_code=language_code, word=word)
    await words_repo.add_translation(session, word_id=created.id, language_code=translation_language, translation=translation)
    return created


async def _add_words(session, user_id, n, *, prefix="word", translation_language="ru", language_code="en"):
    uws = []
    for i in range(n):
        w = await _make_word(
            session, f"{prefix}{i}", f"перевод{i}", translation_language=translation_language, language_code=language_code
        )
        uw = await user_words_repo.add_word(session, user_id=user_id, word_id=w.id, language_code=language_code)
        uws.append(uw)
    return uws


async def test_build_quiz_returns_empty_when_user_has_no_words(session):
    user = await _create_user(session)
    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru")
    assert questions == []


async def test_build_quiz_returns_empty_below_minimum_pool_size(session):
    """Fewer than 4 words means no question can ever get 4 distinct
    options - the quiz must never pad with fake/duplicate distractors, so
    it must simply produce nothing rather than a broken question."""
    user = await _create_user(session)
    await _add_words(session, user.id, 3)
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru")
    assert questions == []


async def test_quiz_has_one_question_per_word_up_to_count(session):
    user = await _create_user(session)
    await _add_words(session, user.id, 6)
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=1)
    assert len(questions) == 1


async def test_quiz_has_exactly_four_answers(session):
    user = await _create_user(session)
    await _add_words(session, user.id, 6)
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=6)
    assert questions  # sanity: the pool is large enough to produce questions
    for q in questions:
        assert len(q["options"]) == 4


async def test_quiz_has_one_correct_answer(session):
    user = await _create_user(session)
    await _add_words(session, user.id, 6)
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=6)
    for q in questions:
        assert q["options"].count(q["correct_answer"]) == 1
        assert len(set(q["options"])) == 4  # no duplicate options at all


async def test_quiz_answers_are_words_not_sentences(session):
    """Options must be short translations, never long example sentences -
    this also confirms the fill-in-blank format is fully gone."""
    user = await _create_user(session)
    await _add_words(session, user.id, 6)
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=6)
    for q in questions:
        for option in q["options"]:
            assert "___" not in option
            assert " " not in option or len(option.split()) <= 3  # a short translation, not a sentence


async def test_quiz_translation_uses_native_language_never_ru_en_fallback(session):
    """The user's translation_language is German here - options must come
    from German translations only, never silently fall back to Russian or
    English even though those rows also exist for these words."""
    user = await _create_user(session)
    for i in range(5):
        w, _ = await word_service.get_or_create_word(session, language_code="en", word=f"deword{i}")
        await words_repo.add_translation(session, word_id=w.id, language_code="ru", translation=f"ru{i}")
        await words_repo.add_translation(session, word_id=w.id, language_code="en", translation=f"en{i}")
        await words_repo.add_translation(session, word_id=w.id, language_code="de", translation=f"de{i}")
        await user_words_repo.add_word(session, user_id=user.id, word_id=w.id, language_code="en")
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="de", count=5)
    assert questions
    for q in questions:
        for option in q["options"]:
            assert option.startswith("de")


async def test_quiz_uses_user_learning_words_excludes_paused_and_deleted(session):
    user = await _create_user(session)
    active_uws = await _add_words(session, user.id, 5, prefix="active")
    paused = await _make_word(session, "paused", "приостановлен")
    paused_uw = await user_words_repo.add_word(session, user_id=user.id, word_id=paused.id, language_code="en")
    paused_uw.status = WordStatus.PAUSED
    deleted = await _make_word(session, "deleted", "удалён")
    deleted_uw = await user_words_repo.add_word(session, user_id=user.id, word_id=deleted.id, language_code="en")
    deleted_uw.status = WordStatus.DELETED
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=10)
    tested_ids = {q["user_word_id"] for q in questions}
    assert tested_ids.issubset({uw.id for uw in active_uws})
    assert paused_uw.id not in tested_ids
    assert deleted_uw.id not in tested_ids


async def test_build_quiz_only_word_ids_restricts_pool(session):
    user = await _create_user(session)
    uws = await _add_words(session, user.id, 5)
    await session.commit()

    questions = await quiz_service.build_quiz(
        session, user_id=user.id, language_code="en", translation_language="ru", only_word_ids=[uws[0].id]
    )
    assert len(questions) == 1
    assert questions[0]["user_word_id"] == uws[0].id


async def test_quiz_questions_carry_cached_pronunciation(session):
    """Global pronunciation rule section 46: quiz questions carry the
    tested word's cached pronunciation for handlers/quiz.py to show only
    after the answer is graded - never generated live here."""
    user = await _create_user(session)
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="cat", pronunciation="kat")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="кошка")
    await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
    await _add_words(session, user.id, 3, prefix="filler")
    await session.commit()

    questions = await quiz_service.build_quiz(session, user_id=user.id, language_code="en", translation_language="ru", count=10)
    cat_q = next(q for q in questions if q["word"] == "cat")
    assert cat_q["pronunciation"] == "kat"


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
