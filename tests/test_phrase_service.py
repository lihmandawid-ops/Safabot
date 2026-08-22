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


# --- §18 checklist: one popular phrase per supported learning language ---

@pytest.mark.parametrize("language_code", ["en", "ru", "de", "he", "es", "fr", "it", "uk"])
async def test_popular_phrase_pronunciation_and_translation_are_correctly_separated(session, monkeypatch, language_code):
    """For every supported learning language: phrase != translation,
    pronunciation != translation, pronunciation belongs to the phrase
    (comes straight from the untouched seed data, never AI), and the
    translation follows translation_language (mocked here as a distinct,
    recognizable transform so a mix-up with the phrase or a fixed
    hardcoded value would fail the assertions below)."""
    async def _fake_translate(phrases, *, language_code, translation_language, user_id):
        return [f"[{translation_language}] {p}" for p in phrases]

    fake_ai = type("FakeAI", (), {"translate_phrases": staticmethod(_fake_translate)})()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    result = await phrase_service.get_translated_popular_phrases(
        session, language_code=language_code, translation_language="ru", user_id=1,
    )
    assert len(result) > 0
    for entry in result:
        assert entry.phrase != entry.translation
        assert entry.pronunciation != entry.translation
        assert entry.pronunciation  # every seed entry has one
        assert entry.translation == f"[ru] {entry.phrase}"  # translation is of THIS phrase, into translation_language


async def test_popular_phrase_translation_follows_interface_language_not_a_fixed_one(session, monkeypatch):
    """Same learning_language (Hebrew), two different translation
    languages (section 4's own example) - the translation must differ
    accordingly, never staying fixed to one language."""
    async def _fake_translate(phrases, *, language_code, translation_language, user_id):
        return [f"[{translation_language}] {p}" for p in phrases]

    fake_ai = type("FakeAI", (), {"translate_phrases": staticmethod(_fake_translate)})()
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    ru_view = await phrase_service.get_translated_popular_phrases(
        session, language_code="he", translation_language="ru", user_id=1,
    )
    await session.commit()
    uk_view = await phrase_service.get_translated_popular_phrases(
        session, language_code="he", translation_language="uk", user_id=1,
    )

    assert ru_view[0].phrase == uk_view[0].phrase  # same learning-language phrase
    assert ru_view[0].translation != uk_view[0].translation  # different translation per interface language
    assert ru_view[0].translation.startswith("[ru]")
    assert uk_view[0].translation.startswith("[uk]")


# --- ✨ Сгенерировать ещё: services.phrase_service.generate_more_popular_phrases ---

def _fake_batch_generator(phrases_by_call):
    """phrases_by_call: list of lists of (phrase, translation, pronunciation,
    category) tuples, one list per expected AI call - lets a test script
    a duplicate on the first call and a fresh phrase on the retry."""
    calls = []

    async def _fake_generate(*, language_code, translation_language, level, amount, category=None, industry=None, topics=None, known_phrases=None, user_id):
        calls.append({
            "language_code": language_code, "translation_language": translation_language, "level": level,
            "amount": amount, "category": category, "industry": industry, "topics": topics,
            "known_phrases": list(known_phrases or []),
        })
        batch = phrases_by_call[len(calls) - 1] if len(calls) - 1 < len(phrases_by_call) else []
        return ai_models.PopularPhraseBatchResult(
            phrases=[
                ai_models.GeneratedPopularPhrase(phrase=p, translation=tr, pronunciation=pron, category=cat)
                for p, tr, pron, cat in batch
            ]
        )

    fake_ai = type("FakeAI", (), {"generate_popular_phrases": staticmethod(_fake_generate)})()
    return fake_ai, calls


async def test_generate_more_popular_phrases_saves_and_returns_new_entries(session, monkeypatch):
    user, ul = await _create_user_and_language(session)
    await session.commit()

    fake_ai, calls = _fake_batch_generator([
        [("Could you give me a hand?", "Не могли бы вы мне помочь?", "kud yu giv mi a hand?", "work")],
    ])
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    result = await phrase_service.generate_more_popular_phrases(session, user=user, user_language=ul, amount=1)
    assert len(result) == 1
    assert result[0].phrase == "Could you give me a hand?"
    assert result[0].translation == "Не могли бы вы мне помочь?"
    assert result[0].pronunciation == "kud yu giv mi a hand?"
    assert result[0].situation == "work"
    assert len(calls) == 1  # one AI call for the whole batch (section 33)

    from database.repositories import popular_phrases as popular_phrases_repo

    saved = await popular_phrases_repo.list_by_language(session, language_code="en")
    assert [row.phrase for row in saved] == ["Could you give me a hand?"]


async def test_generate_more_popular_phrases_is_available_on_a_later_independent_query(session, monkeypatch):
    """§36 item 9: after generating, a phrase must be available on a
    fresh read, not just held in memory from the generating call."""
    user, ul = await _create_user_and_language(session)
    await session.commit()

    fake_ai, _ = _fake_batch_generator([[("Good morning.", "Доброе утро.", "gud MOR-ning", "daily_life")]])

    async def _fake_translate(phrases, *, language_code, translation_language, user_id):
        return [f"[{translation_language}] {p}" for p in phrases]

    fake_ai.translate_phrases = _fake_translate  # plain instance attribute - no self-binding to worry about
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    await phrase_service.generate_more_popular_phrases(session, user=user, user_language=ul, amount=1)
    await session.commit()

    later_view = await phrase_service.get_translated_popular_phrases(
        session, language_code="en", translation_language="ru", user_id=user.id,
    )
    assert any(e.phrase == "Good morning." for e in later_view)
    # already-cached translation from the generation call - no extra AI call needed for it
    generated_entry = next(e for e in later_view if e.phrase == "Good morning.")
    assert generated_entry.translation == "Доброе утро."


async def test_generate_more_popular_phrases_skips_duplicates_of_the_static_seed_set(session, monkeypatch):
    """§26: a "new" phrase that turns out to already exist (here, in the
    static seed set itself) must never be saved as a second row."""
    from utils.popular_phrases import get_popular_phrases

    user, ul = await _create_user_and_language(session)
    await session.commit()

    existing_phrase = get_popular_phrases("en")[0].phrase
    fake_ai, calls = _fake_batch_generator([
        [(existing_phrase, "duplicate - must be skipped", "x", None)],
        [("A genuinely new phrase.", "Действительно новая фраза.", "a jen-yoo-in-li nyoo frayz", None)],
    ])
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    result = await phrase_service.generate_more_popular_phrases(session, user=user, user_language=ul, amount=1)
    assert len(result) == 1
    assert result[0].phrase == "A genuinely new phrase."
    assert len(calls) == 2  # the duplicate triggered exactly one bounded retry
    assert existing_phrase in calls[1]["known_phrases"]  # excluded from the retry prompt too


async def test_generate_more_popular_phrases_gives_up_after_max_attempts_of_only_duplicates(session, monkeypatch):
    from utils.popular_phrases import get_popular_phrases

    user, ul = await _create_user_and_language(session)
    await session.commit()

    existing_phrase = get_popular_phrases("en")[0].phrase
    always_duplicate = [[(existing_phrase, "still a duplicate", "x", None)]] * 5
    fake_ai, calls = _fake_batch_generator(always_duplicate)
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    import config

    settings = config.get_settings()
    result = await phrase_service.generate_more_popular_phrases(session, user=user, user_language=ul, amount=3)
    assert result == []  # never got a non-duplicate - a valid, non-crashing outcome
    assert len(calls) == settings.max_generation_attempts  # bounded, never an infinite loop


async def test_generate_more_popular_phrases_passes_personalization(session, monkeypatch):
    user, ul = await _create_user_and_language(
        session, level="advanced", learning_goal="work", work_industry="construction",
        selected_topics=["business"],
    )
    await session.commit()

    fake_ai, calls = _fake_batch_generator([
        [("Can you send me the measurements?", "Можешь прислать мне замеры?", "kan yu send mi", "work")],
    ])
    monkeypatch.setattr("services.phrase_service.get_ai_service", lambda: fake_ai)

    await phrase_service.generate_more_popular_phrases(session, user=user, user_language=ul, amount=1)
    assert calls[0]["level"] == "advanced"
    assert calls[0]["industry"] == "construction"
    assert calls[0]["topics"] == ["business"]
