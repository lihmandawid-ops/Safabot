"""Tests for services/ai_service.py + services/ai_provider.py + services/
ai_models.py (AI-integration spec section 29): no real AI API request is
ever made - a MockAIProvider (implementing the real AIProvider ABC)
stands in, so these exercise the REAL LiveAIService prompt/parse/
validate/retry/rate-limit/logging logic end-to-end, just with a scripted
transport underneath.
"""
from __future__ import annotations

import pytest

from services import ai_models
from services.ai_errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIInvalidResponseError,
    AIRateLimitedError,
    AITimeoutError,
    AIUnavailableError,
)
from services.ai_provider import AIProvider
from services.ai_service import LiveAIService, NotConfiguredAIService, get_ai_service


class MockAIProvider(AIProvider):
    """Returns (or raises) each entry of `script` in order, one per call -
    a plain string means "succeed with this raw text", an Exception
    instance means "raise this"."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0
        self.last_system: str | None = None
        self.last_user: str | None = None

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        self.last_system = system
        self.last_user = user
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


GOOD_WORD_JSON = (
    '{"word": "go", "translations": [{"translation": "идти"}], "part_of_speech": "verb", '
    '"difficulty": "beginner", "examples": [{"text": "I go home.", "translation": "Я иду домой."}]}'
)
GOOD_GENERATE_JSON = (
    '{"words": [{"word": "cat", "translations": [{"translation": "кошка"}]}, '
    '{"word": "dog", "translations": [{"translation": "собака"}]}]}'
)
GOOD_EXPLANATION_JSON = '{"explanation": "means to move", "examples": ["I go home."]}'
GOOD_TEXT_ANALYSIS_JSON = (
    '{"original_text": "I go home.", "translation": "Я иду домой.", "pronunciation": "ay goh hohm", '
    '"key_words": [{"word": "go", "translation": "идти", "part_of_speech": "verb", "pronunciation": "goh"}], '
    '"useful_phrases": [{"phrase": "go home", "pronunciation": "goh hohm"}]}'
)


def _service(script, *, max_retries=2, per_minute=100, per_day=100) -> tuple[LiveAIService, MockAIProvider]:
    provider = MockAIProvider(script)
    return LiveAIService(
        provider=provider, model="test-model", provider_label="mock",
        max_retries=max_retries, requests_per_minute=per_minute, requests_per_day=per_day,
    ), provider


# --- 1/3. lookup + response validation ---

async def test_lookup_word_returns_validated_result():
    svc, provider = _service([GOOD_WORD_JSON])
    result = await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    assert isinstance(result, ai_models.WordAIResult)
    assert result.word == "go"
    assert result.translations[0].translation == "идти"
    assert result.part_of_speech == "verb"


async def test_lookup_word_drops_unrecognised_part_of_speech_but_keeps_the_word():
    bad_pos_json = '{"word": "go", "translations": [{"translation": "идти"}], "part_of_speech": "not-a-real-pos"}'
    svc, _ = _service([bad_pos_json])
    result = await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    assert result.word == "go"
    assert result.part_of_speech is None


# --- 4. generate_words ---

async def test_generate_words_returns_all_valid_entries():
    svc, _ = _service([GOOD_GENERATE_JSON])
    result = await svc.generate_words(
        language_code="en", translation_language="ru", level="beginner", amount=2, user_id=1
    )
    assert [w.word for w in result.words] == ["cat", "dog"]


async def test_generate_words_skips_invalid_entries_keeps_valid_ones():
    mixed_json = '{"words": [{"word": "cat", "translations": [{"translation": "кошка"}]}, {"no_word": true}]}'
    svc, _ = _service([mixed_json])
    result = await svc.generate_words(
        language_code="en", translation_language="ru", level="beginner", amount=2, user_id=1
    )
    assert [w.word for w in result.words] == ["cat"]


# --- 6. invalid AI response (malformed JSON / wrong shape), retried then raised ---

async def test_invalid_json_is_retried_then_raises():
    svc, provider = _service(["not json at all", "still not json"], max_retries=1)
    with pytest.raises(AIInvalidResponseError):
        await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    assert provider.calls == 2


async def test_missing_required_field_is_invalid_response():
    svc, _ = _service(['{"word": "go"}'], max_retries=0)  # no translations at all
    with pytest.raises(AIInvalidResponseError):
        await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)


# --- 7/8. timeout / unavailable ---

async def test_timeout_is_retried_then_raises():
    svc, provider = _service([AITimeoutError("t"), AITimeoutError("t")], max_retries=1)
    with pytest.raises(AITimeoutError):
        await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    assert provider.calls == 2


async def test_unavailable_is_retried_then_raises():
    svc, provider = _service([AIUnavailableError("down"), AIUnavailableError("down")], max_retries=1)
    with pytest.raises(AIUnavailableError):
        await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    assert provider.calls == 2


# --- 9. retry succeeds on a later attempt ---

async def test_retry_recovers_on_second_attempt():
    svc, provider = _service([AIUnavailableError("blip"), GOOD_WORD_JSON], max_retries=2)
    result = await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    assert result.word == "go"
    assert provider.calls == 2


async def test_authentication_error_is_never_retried():
    svc, provider = _service([AIAuthenticationError("bad key"), GOOD_WORD_JSON], max_retries=3)
    with pytest.raises(AIAuthenticationError):
        await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    assert provider.calls == 1


# --- 10. rate limit ---

async def test_rate_limit_per_minute_blocks_excess_calls():
    svc, provider = _service([GOOD_WORD_JSON] * 5, max_retries=0, per_minute=2, per_day=100)
    await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=7)
    await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=7)
    with pytest.raises(AIRateLimitedError):
        await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=7)
    assert provider.calls == 2


async def test_rate_limit_is_per_user():
    svc, provider = _service([GOOD_WORD_JSON] * 5, max_retries=0, per_minute=1, per_day=100)
    await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    # A different user must not be blocked by user 1's limit.
    await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=2)
    assert provider.calls == 2


# --- 11. explain_word ---

async def test_explain_word_returns_formatted_string():
    svc, _ = _service([GOOD_EXPLANATION_JSON])
    text = await svc.explain_word(
        "go", language_code="en", translation_language="ru", level="beginner",
        interface_language="ru", user_id=1,
    )
    assert "means to move" in text
    assert "I go home." in text


# --- 12. analyze_text ---

async def test_analyze_text_returns_validated_result():
    svc, _ = _service([GOOD_TEXT_ANALYSIS_JSON])
    result = await svc.analyze_text(
        "I go home.", language_code="en", translation_language="ru", interface_language="ru", user_id=1,
    )
    assert result.translation == "Я иду домой."
    assert result.pronunciation == "ay goh hohm"
    assert result.key_words[0].word == "go"
    assert result.key_words[0].pronunciation == "goh"
    assert result.useful_phrases[0].phrase == "go home"
    assert result.useful_phrases[0].pronunciation == "goh hohm"


async def test_explain_grammar_returns_formatted_string():
    svc, _ = _service([GOOD_EXPLANATION_JSON])
    text = await svc.explain_grammar(
        "why went?", language_code="en", level="beginner", interface_language="ru", user_id=1,
    )
    assert "means to move" in text


async def test_extract_learning_words_returns_word_list():
    svc, _ = _service(['{"words": ["go", "home", ""]}'])
    words = await svc.extract_learning_words("I go home.", language_code="en", user_id=1)
    assert words == ["go", "home"]


# --- repetition-system stage: generate_verb_conjugation ---

GOOD_VERB_CONJUGATION_JSON = (
    '{"word": "go", "language": "en", "forms": {'
    '"present": [{"form": "I go", "pronunciation": "ay goh"}, {"form": "You go", "pronunciation": "yoo goh"}, '
    '{"form": "He/She/It goes", "pronunciation": "hee gohz"}, {"form": "We go", "pronunciation": "wee goh"}, '
    '{"form": "You go", "pronunciation": "yoo goh"}, {"form": "They go", "pronunciation": "thay goh"}], '
    '"past": [{"form": "I went", "pronunciation": null}, {"form": "You went", "pronunciation": null}, '
    '{"form": "He/She/It went", "pronunciation": null}, {"form": "We went", "pronunciation": null}, '
    '{"form": "You went", "pronunciation": null}, {"form": "They went", "pronunciation": null}]}}'
)


async def test_generate_verb_conjugation_returns_validated_result():
    svc, provider = _service([GOOD_VERB_CONJUGATION_JSON])
    result = await svc.generate_verb_conjugation("go", language_code="en", user_id=1)
    assert isinstance(result, ai_models.VerbConjugationResult)
    assert result.word == "go"
    assert result.forms["present"][0].form == "I go"
    assert result.forms["present"][0].pronunciation == "ay goh"
    assert result.forms["past"][2].form == "He/She/It went"
    assert result.forms["past"][2].pronunciation is None
    assert "go" in provider.last_user
    assert "en" in provider.last_user


async def test_generate_verb_conjugation_tolerates_a_plain_string_forms_shape():
    """The forms validator also accepts a bare list[str] per tense (an
    older/pre-pronunciation AI response shape) - each string becomes a
    form with pronunciation=None rather than failing validation."""
    raw = (
        '{"word": "go", "language": "en", "forms": {"present": ["I go", "You go"]}}'
    )
    svc, _ = _service([raw])
    result = await svc.generate_verb_conjugation("go", language_code="en", user_id=1)
    assert result.forms["present"][0].form == "I go"
    assert result.forms["present"][0].pronunciation is None


async def test_generate_verb_conjugation_never_forces_english_tense_names():
    """The AI is free to name tenses however that language's own grammar
    does (repetition-system stage section 22) - German's Präteritum/
    Perfekt here, not present/past/future/perfect."""
    german_json = (
        '{"word": "gehen", "language": "de", "forms": {'
        '"Präsens": ["ich gehe", "du gehst", "er/sie/es geht", "wir gehen", "ihr geht", "sie gehen"], '
        '"Präteritum": ["ich ging", "du gingst", "er/sie/es ging", "wir gingen", "ihr gingt", "sie gingen"]}}'
    )
    svc, _ = _service([german_json])
    result = await svc.generate_verb_conjugation("gehen", language_code="de", user_id=1)
    assert set(result.forms) == {"Präsens", "Präteritum"}


async def test_generate_verb_conjugation_rejects_empty_forms():
    svc, _ = _service(['{"word": "go", "language": "en", "forms": {}}'], max_retries=0)
    with pytest.raises(AIInvalidResponseError):
        await svc.generate_verb_conjugation("go", language_code="en", user_id=1)


# --- 14. generate_native_phrase (💬 Полезные фразы) ---

GOOD_NATIVE_PHRASE_JSON = (
    '{"language": "en", "phrase": "Could you give me a hand with this?", '
    '"translation": "Не мог бы ты мне с этим помочь?", "pronunciation": "kud yu giv mi a hand with this", '
    '"register": "casual", "naturalness": "native", "situation": "work", '
    '"explanation": "Natural informal phrase commonly used when asking someone for help.", '
    '"alternative": "Can you give me a hand with this?"}'
)


async def test_generate_native_phrase_returns_validated_result():
    svc, provider = _service([GOOD_NATIVE_PHRASE_JSON])
    result = await svc.generate_native_phrase(
        language_code="en", translation_language="ru", level="intermediate",
        situation="asking a colleague for help", user_id=1,
    )
    assert isinstance(result, ai_models.NativePhraseResult)
    assert result.phrase == "Could you give me a hand with this?"
    assert result.translation == "Не мог бы ты мне с этим помочь?"
    assert result.pronunciation == "kud yu giv mi a hand with this"
    assert result.register_type == "casual"
    assert result.alternative == "Can you give me a hand with this?"
    assert "native speaker" in provider.last_system.lower()
    assert "literal" in provider.last_system.lower()


async def test_generate_native_phrase_retries_when_language_does_not_match():
    """Section 14: never trust the AI blindly - a phrase in the wrong
    language must be rejected and retried, not shown to the learner."""
    wrong_language_json = GOOD_NATIVE_PHRASE_JSON.replace('"language": "en"', '"language": "ru"')
    svc, provider = _service([wrong_language_json, GOOD_NATIVE_PHRASE_JSON])
    result = await svc.generate_native_phrase(
        language_code="en", translation_language="ru", level="intermediate",
        situation="asking a colleague for help", user_id=1,
    )
    assert result.language == "en"
    assert provider.calls == 2


async def test_generate_native_phrase_gives_up_after_repeated_wrong_language():
    wrong_language_json = GOOD_NATIVE_PHRASE_JSON.replace('"language": "en"', '"language": "ru"')
    svc, _ = _service([wrong_language_json, wrong_language_json], max_retries=1)
    with pytest.raises(AIInvalidResponseError):
        await svc.generate_native_phrase(
            language_code="en", translation_language="ru", level="beginner", situation="shopping", user_id=1,
        )


async def test_generate_native_phrase_prompt_includes_industry_topics_and_exclusions():
    svc, provider = _service([GOOD_NATIVE_PHRASE_JSON])
    await svc.generate_native_phrase(
        language_code="en", translation_language="ru", level="advanced", situation="at work",
        industry="construction", topics=["business", "travel"],
        exclude_phrases=["Can you help me?"], user_id=1,
    )
    assert "construction" in provider.last_user
    assert "business" in provider.last_user and "travel" in provider.last_user
    assert "Can you help me?" in provider.last_user


# --- 13. AI disabled / not configured ---

async def test_not_configured_service_raises_configuration_error_for_every_method():
    svc = NotConfiguredAIService()
    with pytest.raises(AIConfigurationError):
        await svc.lookup_word("go", language_code="en", translation_language="ru", user_id=1)
    with pytest.raises(AIConfigurationError):
        await svc.generate_words(language_code="en", translation_language="ru", level="beginner", amount=1, user_id=1)
    with pytest.raises(AIConfigurationError):
        await svc.explain_word("go", language_code="en", translation_language="ru", level="beginner", interface_language="ru", user_id=1)
    with pytest.raises(AIConfigurationError):
        await svc.analyze_text("hi", language_code="en", translation_language="ru", interface_language="ru", user_id=1)
    with pytest.raises(AIConfigurationError):
        await svc.explain_grammar("why?", language_code="en", level="beginner", interface_language="ru", user_id=1)
    with pytest.raises(AIConfigurationError):
        await svc.extract_learning_words("hi", language_code="en", user_id=1)
    with pytest.raises(AIConfigurationError):
        await svc.generate_verb_conjugation("go", language_code="en", user_id=1)
    with pytest.raises(AIConfigurationError):
        await svc.generate_native_phrase(
            language_code="en", translation_language="ru", level="beginner", situation="work", user_id=1,
        )


def test_get_ai_service_factory_respects_ai_enabled_and_api_key(monkeypatch):
    import config
    from services import ai_service as ai_service_module

    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("AI_ENABLED", "true")
    config.get_settings.cache_clear()
    ai_service_module.get_ai_service.cache_clear()
    assert isinstance(ai_service_module.get_ai_service(), NotConfiguredAIService)

    monkeypatch.setenv("AI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("AI_ENABLED", "false")
    config.get_settings.cache_clear()
    ai_service_module.get_ai_service.cache_clear()
    assert isinstance(ai_service_module.get_ai_service(), NotConfiguredAIService)

    monkeypatch.setenv("AI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("AI_ENABLED", "true")
    config.get_settings.cache_clear()
    ai_service_module.get_ai_service.cache_clear()
    assert isinstance(ai_service_module.get_ai_service(), LiveAIService)

    # Leave the environment/cache as we found it for other tests.
    monkeypatch.setenv("AI_API_KEY", "")
    config.get_settings.cache_clear()
    ai_service_module.get_ai_service.cache_clear()


async def test_api_key_is_never_logged(monkeypatch, caplog):
    """Spec section 21/25: never show the API key, in logs or anywhere
    else - exercised through a real (failing) HttpAIProvider.complete()
    call, checking the actual log output it produces."""
    import logging

    import httpx

    from services.ai_provider import HttpAIProvider

    class _FakeResponse:
        status_code = 401

        def json(self):
            return {"error": "invalid api key sk-super-secret-value"}

    async def fake_post(self, url, *, headers, json):
        assert headers["Authorization"] == "Bearer sk-super-secret-value"
        return _FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = HttpAIProvider(api_key="sk-super-secret-value", model="test-model")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AIAuthenticationError):
            await provider.complete(system="s", user="u")

    assert "sk-super-secret-value" not in caplog.text
