"""Tests for services/level_placement_service.py (🤖 Узнать мой уровень,
real user request): the thin translation layer between services.
ai_service's PlacementQuestion/PlacementLevelResult Pydantic shapes and
the plain dicts handlers/settings.py's multi-question flow stores in
context.user_data.
"""
from __future__ import annotations

from datetime import time

from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from services import ai_models, level_placement_service


async def _create_user_and_language(session, *, telegram_id=9200):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username="p", first_name="P",
        interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="ru",
        level="a2", daily_new_words=4,
    )
    return user, ul


async def test_start_placement_test_returns_plain_dicts_in_order(session, monkeypatch):
    user, ul = await _create_user_and_language(session)
    await session.commit()

    questions = [
        ai_models.PlacementQuestion(level="a1", kind="word", prompt="hello"),
        ai_models.PlacementQuestion(level="a2", kind="translate", prompt="I go home."),
    ]

    async def _fake_generate(**kwargs):
        return ai_models.PlacementTestResult(questions=questions)

    fake_ai = type("FakeAI", (), {"generate_placement_test": staticmethod(_fake_generate)})()
    monkeypatch.setattr("services.level_placement_service.get_ai_service", lambda: fake_ai)

    result = await level_placement_service.start_placement_test(ul, user_id=user.id)
    assert result == [
        {"level": "a1", "kind": "word", "prompt": "hello"},
        {"level": "a2", "kind": "translate", "prompt": "I go home."},
    ]


async def test_grade_placement_test_builds_transcript_and_returns_level(session, monkeypatch):
    user, ul = await _create_user_and_language(session)
    await session.commit()

    captured = {}

    async def _fake_grade(*, language_code, translation_language, transcript, user_id):
        captured["transcript"] = transcript
        captured["language_code"] = language_code
        captured["translation_language"] = translation_language
        return ai_models.PlacementLevelResult(level="b1")

    fake_ai = type("FakeAI", (), {"grade_placement_test": staticmethod(_fake_grade)})()
    monkeypatch.setattr("services.level_placement_service.get_ai_service", lambda: fake_ai)

    questions = [
        {"level": "a1", "kind": "word", "prompt": "hello"},
        {"level": "a2", "kind": "translate", "prompt": "I go home."},
    ]
    answers = ["yes", "no"]

    level = await level_placement_service.grade_placement_test(ul, questions, answers, user_id=user.id)

    assert level == "b1"
    assert captured["language_code"] == "en"
    assert captured["translation_language"] == "ru"
    assert captured["transcript"] == [
        {"level": "a1", "kind": "word", "prompt": "hello", "answer": "yes"},
        {"level": "a2", "kind": "translate", "prompt": "I go home.", "answer": "no"},
    ]
