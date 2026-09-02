"""Bidirectional AI dictionary (bugfix stage sections 1-29, real-Telegram
test scenarios of section 48): the six worked RU<->HE / RU<->DE / RU<->EN
pairs from the spec, plus a verb case, run end-to-end through the REAL
LiveAIService.lookup_word() (prompt build -> parse -> query_language
direction validation) with a scripted MockAIProvider standing in for the
network call - same no-real-AI-request philosophy as tests/test_ai_service.py,
just focused on the direction-correctness worked examples the spec gives
verbatim rather than the validator's edge cases in isolation.

No English/Russian fallback text is asserted anywhere here on purpose -
every translation/pronunciation in these fixtures is deliberately written
in the pair's own native_language, so a test would fail if the production
code silently dropped in an English placeholder somewhere.
"""
from __future__ import annotations

from services import ai_models
from services.ai_provider import AIProvider
from services.ai_service import LiveAIService


class _ScriptedProvider(AIProvider):
    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        return self.script.pop(0)


def _service(script: list[str]) -> LiveAIService:
    return LiveAIService(
        provider=_ScriptedProvider(script), model="test-model", provider_label="mock",
        max_retries=2, requests_per_minute=100, requests_per_day=100,
    )


# --- TEST 1/2: Russian <-> Hebrew ("велосипед" / "אופניים") ---

async def test_russian_to_hebrew_returns_hebrew_headword_with_russian_translation():
    raw = (
        '{"query_language": "ru", "word": "אופניים", "pronunciation": "ofanáyim", '
        '"translations": [{"translation": "велосипед"}]}'
    )
    svc = _service([raw])
    result = await svc.lookup_word("велосипед", language_code="he", translation_language="ru", user_id=1)
    assert result.word == "אופניים"
    assert result.pronunciation == "ofanáyim"
    assert result.translations[0].translation == "велосипед"


async def test_hebrew_to_russian_returns_the_same_card_shape_reversed():
    raw = (
        '{"query_language": "he", "word": "אופניים", "pronunciation": "ofanáyim", '
        '"translations": [{"translation": "велосипед"}]}'
    )
    svc = _service([raw])
    result = await svc.lookup_word("אופניים", language_code="he", translation_language="ru", user_id=1)
    assert result.word == "אופניים"
    assert result.translations[0].translation == "велосипед"


# --- TEST 3/4: Russian <-> German ("велосипед" / "Fahrrad") ---

async def test_russian_to_german_returns_german_headword_with_russian_translation():
    raw = '{"query_language": "ru", "word": "Fahrrad", "translations": [{"translation": "велосипед"}]}'
    svc = _service([raw])
    result = await svc.lookup_word("велосипед", language_code="de", translation_language="ru", user_id=1)
    assert result.word == "Fahrrad"
    assert result.translations[0].translation == "велосипед"


async def test_german_to_russian_returns_the_same_card_shape_reversed():
    raw = '{"query_language": "de", "word": "Fahrrad", "translations": [{"translation": "велосипед"}]}'
    svc = _service([raw])
    result = await svc.lookup_word("Fahrrad", language_code="de", translation_language="ru", user_id=1)
    assert result.word == "Fahrrad"
    assert result.translations[0].translation == "велосипед"


# --- TEST 5/6: Russian <-> English ("велосипед" / "bicycle") ---

async def test_russian_to_english_returns_english_headword_with_russian_translation():
    raw = '{"query_language": "ru", "word": "bicycle", "translations": [{"translation": "велосипед"}]}'
    svc = _service([raw])
    result = await svc.lookup_word("велосипед", language_code="en", translation_language="ru", user_id=1)
    assert result.word == "bicycle"
    assert result.translations[0].translation == "велосипед"


async def test_english_to_russian_returns_the_same_card_shape_reversed():
    raw = '{"query_language": "en", "word": "bicycle", "translations": [{"translation": "велосипед"}]}'
    svc = _service([raw])
    result = await svc.lookup_word("bicycle", language_code="en", translation_language="ru", user_id=1)
    assert result.word == "bicycle"
    assert result.translations[0].translation == "велосипед"


# --- TEST 7: interface_language must never affect direction ---

async def test_lookup_word_never_receives_interface_language_at_all():
    """Spec's explicit worked example: interface_language=he, native_
    language=ru, learning_language=he, query "велосипед" must still
    resolve ru->he exactly like test 1 above - proven structurally here,
    since AIService.lookup_word's signature has no interface_language
    parameter in the first place, so it cannot influence the AI prompt
    even by accident."""
    import inspect

    params = inspect.signature(LiveAIService.lookup_word).parameters
    assert "interface_language" not in params


# --- TEST 8: verb case (translation, pronunciation, example + its own
# translation, usage, verb forms with native-language person labels) ---

async def test_verb_lookup_includes_examples_pronunciation_and_verb_forms():
    raw = (
        '{"query_language": "ru", "word": "learn", "pronunciation": "lurn", '
        '"part_of_speech": "verb", '
        '"translations": [{"translation": "учить", "usage_note": "изучать что-то новое"}], '
        '"examples": [{"text": "I learn Hebrew.", "translation": "Я учу иврит."}], '
        '"verb_forms": {"past": "learned", "gerund": "learning"}}'
    )
    svc = _service([raw])
    result = await svc.lookup_word("учить", language_code="en", translation_language="ru", user_id=1)
    assert result.word == "learn"
    assert result.part_of_speech == "verb"
    assert result.pronunciation == "lurn"
    assert result.translations[0].translation == "учить"
    assert result.translations[0].usage_note == "изучать что-то новое"
    assert result.examples[0].text == "I learn Hebrew."
    assert result.examples[0].translation == "Я учу иврит."
    assert result.verb_forms == {"past": "learned", "gerund": "learning"}


async def test_verb_conjugation_table_has_native_language_person_labels_and_per_form_translation():
    """🔤 Все формы (sections 14-18): each row's person label and
    translation are in native_language (ru here), not the learning
    language and not interface_language."""
    raw = (
        '{"word": "learn", "language": "he", "forms": {"Present": ['
        '{"form": "לומד", "pronunciation": "lomed", "person_label": "Я (м.р.)", "translation": "я учу"}, '
        '{"form": "לומדת", "pronunciation": "lomedet", "person_label": "Я (ж.р.)", "translation": "я учу"}'
        ']}}'
    )
    svc = _service([raw])
    result = await svc.generate_verb_conjugation("learn", language_code="he", translation_language="ru", user_id=1)
    row = result.forms["Present"][0]
    assert row.form == "לומד"
    assert row.person_label == "Я (м.р.)"
    assert row.translation == "я учу"
