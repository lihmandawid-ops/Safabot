"""Tests for services/word_service.report_wrong_translation ("⚠️ Неверный
перевод" - real-user report on the Hebrew shared dictionary: אבנט
mistranslated as "window shutter" instead of "belt/sash", מתקן as
"microscope" instead of "device/facility"). A shared-dictionary Word's AI
translation was otherwise permanent - search_words/
find_unknown_words_for_generation only ever call AI when no local row
exists yet, so one bad response for a real word was never retried.
"""
from __future__ import annotations

from services import ai_models, dictionary_service, word_service
from database.repositories import words as words_repo


class _FakeProvider(dictionary_service.DictionaryProvider):
    def __init__(self, data: ai_models.GeneratedWord | None):
        self._data = data
        self.calls: list[str] = []

    async def lookup(self, raw_word, *, language_code, translation_language, user_level, user_id):
        self.calls.append(raw_word)
        return self._data


def _word(word: str, translation: str, **kwargs) -> ai_models.GeneratedWord:
    kwargs.setdefault("translations", [ai_models.TranslationResult(translation=translation)])
    return ai_models.GeneratedWord(word=word, **kwargs)


async def test_report_wrong_translation_replaces_the_bad_translation(session, monkeypatch):
    word, _ = await word_service.get_or_create_word(session, language_code="he", word="אבנט")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="оконная створка")
    await session.commit()

    provider = _FakeProvider(_word("אבנט", "пояс"))
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    updated = await word_service.report_wrong_translation(session, word, translation_language="ru", user_id=1)

    assert updated is True
    assert provider.calls == ["אבנט"]
    refreshed = await words_repo.get_by_id(session, word.id)
    ru_translations = [t.translation for t in refreshed.translations if t.language_code == "ru"]
    assert ru_translations == ["пояс"]  # old "оконная створка" is gone, not just appended


async def test_report_wrong_translation_never_touches_other_languages(session, monkeypatch):
    word, _ = await word_service.get_or_create_word(session, language_code="he", word="מתקן")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="микроскоп")
    await words_repo.add_translation(session, word_id=word.id, language_code="en", translation="microscope")
    await session.commit()

    provider = _FakeProvider(_word("מתקן", "устройство"))
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    await word_service.report_wrong_translation(session, word, translation_language="ru", user_id=1)

    refreshed = await words_repo.get_by_id(session, word.id)
    by_language = {t.language_code: t.translation for t in refreshed.translations}
    assert by_language == {"ru": "устройство", "en": "microscope"}  # "en" untouched


async def test_report_wrong_translation_keeps_the_same_word_row(session, monkeypatch):
    """The Word row itself (and therefore every learner's UserWord
    progress on it, which cascades on Word deletion) must never be
    replaced - only its WordTranslation rows for the reported language."""
    word, _ = await word_service.get_or_create_word(session, language_code="he", word="אבנט", pronunciation="avnet")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="оконная створка")
    await session.commit()
    original_id = word.id

    provider = _FakeProvider(_word("אבנט", "пояс"))
    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: provider)

    await word_service.report_wrong_translation(session, word, translation_language="ru", user_id=1)

    refreshed = await words_repo.get_by_id(session, original_id)
    assert refreshed is not None
    assert refreshed.pronunciation == "avnet"  # untouched, report is about translations only


async def test_report_wrong_translation_returns_false_when_ai_has_nothing(session, monkeypatch):
    word, _ = await word_service.get_or_create_word(session, language_code="he", word="אבנט")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="оконная створка")
    await session.commit()

    monkeypatch.setattr(dictionary_service, "get_dictionary_provider", lambda: _FakeProvider(None))

    updated = await word_service.report_wrong_translation(session, word, translation_language="ru", user_id=1)

    assert updated is False
    refreshed = await words_repo.get_by_id(session, word.id)
    ru_translations = [t.translation for t in refreshed.translations if t.language_code == "ru"]
    assert ru_translations == ["оконная створка"]  # nothing changed - never delete without a replacement


async def test_report_wrong_translation_gracefully_noop_when_ai_unconfigured(session):
    """Default test environment has AI forced unconfigured (conftest.py's
    autouse fixture) - must degrade to False, not raise."""
    word, _ = await word_service.get_or_create_word(session, language_code="he", word="אבנט")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="оконная створка")
    await session.commit()

    updated = await word_service.report_wrong_translation(session, word, translation_language="ru", user_id=1)
    assert updated is False
