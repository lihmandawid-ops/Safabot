"""Tests for services/phrase_service.py and database/repositories/phrases.py
(native-speaker phrasebook stage): situation-hint resolution, industry
gating (learning_goal must be "work"), save/dedup, and generate_phrase's
argument wiring into AIService.generate_native_phrase.
"""
from __future__ import annotations

from datetime import time

import pytest

from database.repositories import phrases as phrases_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from services import ai_models, phrase_service


async def _create_user_and_language(session, *, telegram_id=9100, **ul_kwargs):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username="p", first_name="P",
        interface_language="ru", timezone="UTC", level="beginner", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    defaults = dict(language_code="en", translation_language="ru", level="intermediate", daily_new_words=4)
    defaults.update(ul_kwargs)
    ul = await user_languages_repo.add_language(session, user_id=user.id, **defaults)
    return user, ul


def test_situation_hint_returns_english_description_for_preset_code():
    hint = phrase_service.situation_hint("restaurant")
    assert "restaurant" in hint.lower()


def test_situation_hint_returns_the_text_itself_for_a_custom_situation():
    custom = "Мне нужно попросить начальника разрешить прийти завтра позже."
    assert phrase_service.situation_hint(custom) == custom


def test_industry_hint_is_none_unless_goal_is_work():
    from types import SimpleNamespace

    not_work = SimpleNamespace(learning_goal="travel", work_industry="construction")
    assert phrase_service.industry_hint(not_work) is None

    no_industry_set = SimpleNamespace(learning_goal="work", work_industry=None)
    assert phrase_service.industry_hint(no_industry_set) is None

    work_with_industry = SimpleNamespace(learning_goal="work", work_industry="construction")
    assert phrase_service.industry_hint(work_with_industry) == "construction"


async def test_generate_phrase_passes_level_industry_topics_to_ai_service(session, monkeypatch):
    user, ul = await _create_user_and_language(
        session, level="advanced", learning_goal="work", work_industry="construction",
        selected_topics=["business", "travel"],
    )
    await session.commit()

    captured = {}

    async def _fake_generate_native_phrase(**kwargs):
        captured.update(kwargs)
        return ai_models.NativePhraseResult(
            language="en", phrase="Can you send me the measurements?",
            translation="Можешь прислать мне замеры?", pronunciation="kan yu send mi",
        )

    fake_ai = type("FakeAI", (), {"generate_native_phrase": staticmethod(_fake_generate_native_phrase)})()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    result = await phrase_service.generate_phrase(
        user=user, user_language=ul, situation_code="work", situation_text="",
    )
    assert result.phrase == "Can you send me the measurements?"
    assert captured["language_code"] == "en"
    assert captured["translation_language"] == "ru"
    assert captured["level"] == "advanced"
    assert captured["industry"] == "construction"
    assert captured["topics"] == ["business", "travel"]
    assert "work" in captured["situation"].lower()


async def test_generate_phrase_uses_custom_text_for_non_preset_situation(session, monkeypatch):
    user, ul = await _create_user_and_language(session)
    await session.commit()

    captured = {}

    async def _fake_generate_native_phrase(**kwargs):
        captured.update(kwargs)
        return ai_models.NativePhraseResult(language="en", phrase="x", translation="y")

    fake_ai = type("FakeAI", (), {"generate_native_phrase": staticmethod(_fake_generate_native_phrase)})()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    custom_text = "I need to ask my boss to let me come in later tomorrow."
    await phrase_service.generate_phrase(
        user=user, user_language=ul, situation_code="custom", situation_text=custom_text,
    )
    assert captured["situation"] == custom_text


async def test_save_phrase_persists_all_fields(session):
    user, ul = await _create_user_and_language(session)
    await session.commit()

    result = ai_models.NativePhraseResult(
        language="en", phrase="Could you give me a hand?", translation="Не мог бы ты помочь?",
        pronunciation="kud yu giv mi a hand", register_type="casual", situation="work",
        explanation="informal help request",
    )
    saved = await phrase_service.save_phrase(session, user_id=user.id, language_code="en", result=result)
    assert saved.created is True
    assert saved.phrase.translation == "Не мог бы ты помочь?"
    assert saved.phrase.pronunciation == "kud yu giv mi a hand"
    assert saved.phrase.register == "casual"


async def test_save_phrase_is_case_insensitive_dedup(session):
    user, ul = await _create_user_and_language(session)
    await session.commit()

    result = ai_models.NativePhraseResult(language="en", phrase="How are you doing?", translation="Как дела?")
    first = await phrase_service.save_phrase(session, user_id=user.id, language_code="en", result=result)
    assert first.created is True

    same_but_different_case = ai_models.NativePhraseResult(
        language="en", phrase="HOW ARE YOU DOING?", translation="Как поживаешь?"
    )
    second = await phrase_service.save_phrase(session, user_id=user.id, language_code="en", result=same_but_different_case)
    assert second.created is False
    assert second.phrase.id == first.phrase.id

    all_phrases = await phrases_repo.list_phrases(session, user_id=user.id, language_code="en")
    assert len(all_phrases) == 1


# --- 🔥 Популярные фразы: cached-translation pagination source ---

async def test_get_translated_popular_phrases_never_touches_pronunciation_via_ai(session, monkeypatch):
    """Root-cause regression: popular-phrase pronunciation must come ONLY
    from the static Latin seed data - never from a live AI call, which is
    what caused the original bug (pronunciation looking like a copy of
    the translation)."""
    # translate_phrases IS allowed to be called (for the translation only) -
    # the point of this test is that pronunciation never changes from the
    # static seed value, regardless of what the AI mock returns.
    async def _fake_translate(phrases, *, language_code, translation_language, user_id):
        return [f"[{p}]" for p in phrases]

    fake_ai = type("FakeAI", (), {"translate_phrases": staticmethod(_fake_translate)})()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    from utils.popular_phrases import get_popular_phrases

    seed = get_popular_phrases("en")
    result = await phrase_service.get_translated_popular_phrases(
        session, language_code="en", translation_language="ru", user_id=1,
    )
    assert len(result) == len(seed)
    for entry, seed_entry in zip(result, seed):
        assert entry.pronunciation == seed_entry.pronunciation  # untouched, straight from seed data
        assert entry.phrase == seed_entry.phrase
        assert entry.translation == f"[{seed_entry.phrase}]"


async def test_get_translated_popular_phrases_calls_ai_at_most_once_per_language_pair(session, monkeypatch):
    calls = []

    async def _fake_translate(phrases, *, language_code, translation_language, user_id):
        calls.append(list(phrases))
        return [f"tr-{p}" for p in phrases]

    fake_ai = type("FakeAI", (), {"translate_phrases": staticmethod(_fake_translate)})()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    first = await phrase_service.get_translated_popular_phrases(
        session, language_code="en", translation_language="ru", user_id=1,
    )
    await session.commit()
    second = await phrase_service.get_translated_popular_phrases(
        session, language_code="en", translation_language="ru", user_id=2,
    )

    assert len(calls) == 1  # cached after the first fill - the second call reused the DB
    assert [e.translation for e in first] == [e.translation for e in second]


async def test_get_translated_popular_phrases_uses_a_single_batch_call_not_one_per_phrase(session, monkeypatch):
    calls = []

    async def _fake_translate(phrases, *, language_code, translation_language, user_id):
        calls.append(list(phrases))
        return [f"tr-{p}" for p in phrases]

    fake_ai = type("FakeAI", (), {"translate_phrases": staticmethod(_fake_translate)})()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    from utils.popular_phrases import get_popular_phrases

    seed = get_popular_phrases("en")
    await phrase_service.get_translated_popular_phrases(
        session, language_code="en", translation_language="ru", user_id=1,
    )
    assert len(calls) == 1
    assert len(calls[0]) == len(seed)  # the WHOLE set in one call, not one call per phrase


async def test_get_translated_popular_phrases_degrades_gracefully_when_ai_unconfigured(session):
    """Default test environment has AI forced unconfigured - the phrase
    list must still render, with an empty (not crashing) translation."""
    result = await phrase_service.get_translated_popular_phrases(
        session, language_code="en", translation_language="ru", user_id=1,
    )
    assert len(result) > 0
    assert all(e.translation == "" for e in result)
    assert all(e.pronunciation for e in result)  # pronunciation is unaffected, always present
