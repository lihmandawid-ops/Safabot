"""Tests for the Gemini integration stage: services/gemini_provider.py
(GeminiTextProvider/GeminiOCRProvider/GeminiSTTProvider), services.
ai_provider.FallbackAIProvider (Gemini primary, DeepSeek fallback for
text-only tasks), the get_ai_service()/get_ocr_service()/get_stt_service()
factory wiring, and services.ai_diagnostics.test_gemini_connection().

Never touches the real network - either the autouse GEMINI_API_KEY=""/
AI_API_KEY="" isolation (tests/conftest.py) exercises the "not configured"
paths, or httpx.AsyncClient.post is monkeypatched with a fake response
(same pattern tests/test_ai_service.py's test_api_key_is_never_logged
uses), or a MockAIProvider stands in for the whole provider.
"""
from __future__ import annotations

import logging

import httpx
import pytest

import config
from services.ai_errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIError,
    AIInvalidResponseError,
    AIRateLimitedError,
    AITimeoutError,
    AIUnavailableError,
)
from services.ai_provider import AIProvider, FallbackAIProvider, HttpAIProvider
from services.gemini_provider import GeminiOCRProvider, GeminiSTTProvider, GeminiTextProvider
from services.media_errors import (
    OCRAuthenticationError,
    OCRError,
    OCRInvalidResponseError,
    OCRTimeoutError,
    OCRUnavailableError,
    STTAuthenticationError,
    STTError,
    STTInvalidResponseError,
    STTTimeoutError,
    STTUnavailableError,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _ok_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class MockAIProvider(AIProvider):
    def __init__(self, *, response: str | None = None, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._response


# --- GeminiTextProvider: HTTP-level behavior ---

async def test_gemini_text_provider_sends_expected_request_shape(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse(200, _ok_body('{"status": "ok"}'))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = GeminiTextProvider(api_key="test-gemini-key", model="gemini-flash-latest")
    result = await provider.complete(system="be helpful", user="say hi")

    assert result == '{"status": "ok"}'
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    assert captured["headers"]["x-goog-api-key"] == "test-gemini-key"
    assert captured["json"]["contents"][0]["parts"][0]["text"] == "say hi"
    assert captured["json"]["systemInstruction"]["parts"][0]["text"] == "be helpful"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"


async def test_gemini_text_provider_respects_custom_base_url(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured["url"] = url
        return _FakeResponse(200, _ok_body("ok"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiTextProvider(api_key="k", model="m", base_url="https://my-proxy.example/")
    await provider.complete(system="s", user="u")
    assert captured["url"] == "https://my-proxy.example/v1beta/models/m:generateContent"


async def test_gemini_text_provider_routes_through_gemini_proxy_url_when_set(monkeypatch):
    """Some regions get HTTP 400 "User location is not supported for the
    API use" from Google regardless of key validity - GEMINI_PROXY_URL
    routes ONLY this request through a forward proxy in a supported
    region, by passing `proxy=` straight to httpx.AsyncClient."""
    captured = {}
    real_init = httpx.AsyncClient.__init__

    def spy_init(self, *args, **kwargs):
        captured["proxy"] = kwargs.get("proxy")
        return real_init(self, *args, **kwargs)

    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(200, _ok_body("ok"))

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy_init)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = GeminiTextProvider(api_key="k", model="m", proxy="http://proxyhost:3128")
    await provider.complete(system="s", user="u")
    assert captured["proxy"] == "http://proxyhost:3128"


async def test_gemini_text_provider_no_proxy_by_default(monkeypatch):
    captured = {}
    real_init = httpx.AsyncClient.__init__

    def spy_init(self, *args, **kwargs):
        captured["proxy"] = kwargs.get("proxy")
        return real_init(self, *args, **kwargs)

    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(200, _ok_body("ok"))

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy_init)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = GeminiTextProvider(api_key="k", model="m")
    await provider.complete(system="s", user="u")
    assert captured["proxy"] is None


@pytest.mark.parametrize(
    "status_code,expected_error",
    [
        (401, AIAuthenticationError),
        (403, AIAuthenticationError),
        (429, AIRateLimitedError),
        (500, AIUnavailableError),
        (503, AIUnavailableError),
        (400, AIInvalidResponseError),
        (404, AIInvalidResponseError),
    ],
)
async def test_gemini_text_provider_maps_status_codes(monkeypatch, status_code, expected_error):
    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(status_code, {"error": {"message": "nope"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiTextProvider(api_key="k", model="m")
    with pytest.raises(expected_error):
        await provider.complete(system="s", user="u")


async def test_gemini_text_provider_timeout_maps_to_ai_timeout_error(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiTextProvider(api_key="k", model="m")
    with pytest.raises(AITimeoutError):
        await provider.complete(system="s", user="u")


async def test_gemini_text_provider_network_error_maps_to_ai_unavailable_error(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiTextProvider(api_key="k", model="m")
    with pytest.raises(AIUnavailableError):
        await provider.complete(system="s", user="u")


async def test_gemini_text_provider_malformed_body_is_invalid_response(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(200, {"unexpected": "shape"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiTextProvider(api_key="k", model="m")
    with pytest.raises(AIInvalidResponseError):
        await provider.complete(system="s", user="u")


async def test_gemini_text_provider_empty_text_is_invalid_response(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(200, _ok_body(""))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiTextProvider(api_key="k", model="m")
    with pytest.raises(AIInvalidResponseError):
        await provider.complete(system="s", user="u")


async def test_gemini_api_key_is_never_logged(monkeypatch, caplog):
    async def fake_post(self, url, *, headers, json):
        assert headers["x-goog-api-key"] == "gm-super-secret-value"
        return _FakeResponse(401, {"error": {"message": "invalid api key gm-super-secret-value"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiTextProvider(api_key="gm-super-secret-value", model="m")

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AIAuthenticationError):
            await provider.complete(system="s", user="u")

    assert "gm-super-secret-value" not in caplog.text


# --- GeminiOCRProvider / GeminiSTTProvider ---

async def test_gemini_ocr_provider_returns_extracted_text(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured["json"] = json
        return _FakeResponse(200, _ok_body("Hello world"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiOCRProvider(api_key="k", model="m")
    text = await provider.extract_text(b"fake-jpeg-bytes", mime_type="image/jpeg")

    assert text == "Hello world"
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert "generationConfig" in captured["json"]
    assert "responseMimeType" not in captured["json"]["generationConfig"]


async def test_gemini_ocr_provider_tolerates_empty_extraction(monkeypatch):
    """No text in the image is a VALID answer for OCR - never an error,
    unlike an empty answer from the text provider."""
    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(200, _ok_body(""))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiOCRProvider(api_key="k", model="m")
    text = await provider.extract_text(b"fake", mime_type="image/jpeg")
    assert text == ""


@pytest.mark.parametrize(
    "status_code,expected_error",
    [(401, OCRAuthenticationError), (500, OCRUnavailableError), (400, OCRInvalidResponseError)],
)
async def test_gemini_ocr_provider_maps_status_codes(monkeypatch, status_code, expected_error):
    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(status_code, {"error": "nope"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiOCRProvider(api_key="k", model="m")
    with pytest.raises(expected_error):
        await provider.extract_text(b"fake", mime_type="image/jpeg")


async def test_gemini_ocr_provider_timeout(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiOCRProvider(api_key="k", model="m")
    with pytest.raises(OCRTimeoutError):
        await provider.extract_text(b"fake", mime_type="image/jpeg")


async def test_gemini_stt_provider_returns_transcribed_text(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured["json"] = json
        return _FakeResponse(200, _ok_body("hello there"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiSTTProvider(api_key="k", model="m")
    text = await provider.transcribe(b"fake-ogg-bytes", mime_type="audio/ogg", filename="voice.ogg")

    assert text == "hello there"
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[1]["inlineData"]["mimeType"] == "audio/ogg"


async def test_gemini_stt_provider_tolerates_empty_transcription(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(200, _ok_body(""))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiSTTProvider(api_key="k", model="m")
    text = await provider.transcribe(b"fake", mime_type="audio/ogg", filename="voice.ogg")
    assert text == ""


@pytest.mark.parametrize(
    "status_code,expected_error",
    [(401, STTAuthenticationError), (500, STTUnavailableError), (400, STTInvalidResponseError)],
)
async def test_gemini_stt_provider_maps_status_codes(monkeypatch, status_code, expected_error):
    async def fake_post(self, url, *, headers, json):
        return _FakeResponse(status_code, {"error": "nope"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiSTTProvider(api_key="k", model="m")
    with pytest.raises(expected_error):
        await provider.transcribe(b"fake", mime_type="audio/ogg", filename="voice.ogg")


async def test_gemini_stt_provider_timeout(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = GeminiSTTProvider(api_key="k", model="m")
    with pytest.raises(STTTimeoutError):
        await provider.transcribe(b"fake", mime_type="audio/ogg", filename="voice.ogg")


# --- FallbackAIProvider ---

async def test_fallback_uses_primary_when_it_succeeds():
    primary = MockAIProvider(response="from gemini")
    secondary = MockAIProvider(response="from deepseek")
    provider = FallbackAIProvider(primary=primary, secondary=secondary, primary_label="gemini", secondary_label="deepseek")

    result = await provider.complete(system="s", user="u")

    assert result == "from gemini"
    assert primary.calls == 1
    assert secondary.calls == 0


async def test_fallback_falls_through_to_secondary_on_primary_error():
    primary = MockAIProvider(raises=AIUnavailableError("gemini down"))
    secondary = MockAIProvider(response="from deepseek")
    provider = FallbackAIProvider(primary=primary, secondary=secondary, primary_label="gemini", secondary_label="deepseek")

    result = await provider.complete(system="s", user="u")

    assert result == "from deepseek"
    assert primary.calls == 1
    assert secondary.calls == 1


@pytest.mark.parametrize(
    "error",
    [
        AITimeoutError("timeout"),
        AIUnavailableError("network"),
        AIRateLimitedError("quota"),
        AIAuthenticationError("bad key"),
        AIInvalidResponseError("bad shape"),
    ],
)
async def test_fallback_triggers_on_every_ai_error_kind(error):
    """Spec's explicit fallback trigger list: timeout, temporary error,
    network error, rate limit, quota error, unavailability, invalid
    response - all are AIError subclasses, all must trigger the fallback."""
    primary = MockAIProvider(raises=error)
    secondary = MockAIProvider(response="from deepseek")
    provider = FallbackAIProvider(primary=primary, secondary=secondary, primary_label="gemini", secondary_label="deepseek")

    result = await provider.complete(system="s", user="u")
    assert result == "from deepseek"


async def test_fallback_raises_secondary_error_when_both_fail():
    primary = MockAIProvider(raises=AIUnavailableError("gemini down"))
    secondary = MockAIProvider(raises=AIAuthenticationError("bad deepseek key"))
    provider = FallbackAIProvider(primary=primary, secondary=secondary, primary_label="gemini", secondary_label="deepseek")

    with pytest.raises(AIAuthenticationError):
        await provider.complete(system="s", user="u")


async def test_fallback_always_retries_primary_first_on_the_next_call():
    """Never "sticky" on the fallback - the moment Gemini recovers, the
    very next call goes back to it automatically (spec section 27)."""
    primary = MockAIProvider(raises=AIUnavailableError("gemini down"))
    secondary = MockAIProvider(response="from deepseek")
    provider = FallbackAIProvider(primary=primary, secondary=secondary, primary_label="gemini", secondary_label="deepseek")

    await provider.complete(system="s", user="u")
    assert primary.calls == 1 and secondary.calls == 1

    primary._raises = None
    primary._response = "gemini is back"
    result = await provider.complete(system="s", user="u")

    assert result == "gemini is back"
    assert primary.calls == 2
    assert secondary.calls == 1  # never called again once primary recovered


async def test_fallback_never_leaks_provider_labels_or_keys_into_result():
    primary = MockAIProvider(raises=AIUnavailableError("gemini down"))
    secondary = MockAIProvider(response="clean response")
    provider = FallbackAIProvider(primary=primary, secondary=secondary, primary_label="gemini", secondary_label="deepseek")
    result = await provider.complete(system="s", user="u")
    assert result == "clean response"


# --- Factory wiring: get_ai_service() ---

def _reset_ai_factories():
    from services.ai_service import get_ai_service
    from services.ocr_service import get_ocr_service
    from services.stt_service import get_stt_service

    config.get_settings.cache_clear()
    get_ai_service.cache_clear()
    get_ocr_service.cache_clear()
    get_stt_service.cache_clear()


def test_get_ai_service_uses_gemini_only_when_deepseek_not_configured(monkeypatch):
    from services.ai_service import LiveAIService, get_ai_service

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    monkeypatch.setenv("AI_API_KEY", "")
    _reset_ai_factories()
    try:
        service = get_ai_service()
        assert isinstance(service, LiveAIService)
        assert isinstance(service._provider, GeminiTextProvider)
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        _reset_ai_factories()


def test_get_ai_service_wires_gemini_proxy_url_into_the_provider(monkeypatch):
    from services.ai_service import get_ai_service

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("GEMINI_PROXY_URL", "http://proxyhost:3128")
    _reset_ai_factories()
    try:
        service = get_ai_service()
        assert service._provider._proxy == "http://proxyhost:3128"
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("GEMINI_PROXY_URL", "")
        _reset_ai_factories()


def test_get_ai_service_uses_deepseek_only_when_gemini_not_configured(monkeypatch):
    from services.ai_service import LiveAIService, get_ai_service

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("AI_API_KEY", "sk-test-deepseek-key")
    _reset_ai_factories()
    try:
        service = get_ai_service()
        assert isinstance(service, LiveAIService)
        assert isinstance(service._provider, HttpAIProvider)
    finally:
        monkeypatch.setenv("AI_API_KEY", "")
        _reset_ai_factories()


def test_get_ai_service_uses_fallback_provider_when_both_configured(monkeypatch):
    from services.ai_service import LiveAIService, get_ai_service

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    monkeypatch.setenv("AI_API_KEY", "sk-test-deepseek-key")
    _reset_ai_factories()
    try:
        service = get_ai_service()
        assert isinstance(service, LiveAIService)
        assert isinstance(service._provider, FallbackAIProvider)
        assert isinstance(service._provider._primary, GeminiTextProvider)
        assert isinstance(service._provider._secondary, HttpAIProvider)
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("AI_API_KEY", "")
        _reset_ai_factories()


def test_get_ai_service_returns_not_configured_when_neither_is_set(monkeypatch):
    from services.ai_service import NotConfiguredAIService, get_ai_service

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("AI_API_KEY", "")
    _reset_ai_factories()
    assert isinstance(get_ai_service(), NotConfiguredAIService)


def test_get_ai_service_respects_gemini_enabled_flag(monkeypatch):
    from services.ai_service import LiveAIService, get_ai_service

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    monkeypatch.setenv("GEMINI_ENABLED", "false")
    monkeypatch.setenv("AI_API_KEY", "sk-test-deepseek-key")
    _reset_ai_factories()
    try:
        service = get_ai_service()
        # Gemini disabled -> DeepSeek-only, not a fallback pair.
        assert isinstance(service._provider, HttpAIProvider)
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("GEMINI_ENABLED", "true")
        monkeypatch.setenv("AI_API_KEY", "")
        _reset_ai_factories()


# --- Factory wiring: get_ocr_service() / get_stt_service() (Gemini-only, no DeepSeek fallback) ---

def test_get_ocr_service_prefers_gemini_when_configured(monkeypatch):
    from services.ocr_service import LiveOCRService, get_ocr_service

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    monkeypatch.setenv("OCR_API_KEY", "should-not-be-used")
    _reset_ai_factories()
    try:
        service = get_ocr_service()
        assert isinstance(service, LiveOCRService)
        assert isinstance(service._provider, GeminiOCRProvider)
        assert service._provider_label == "gemini"
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("OCR_API_KEY", "")
        _reset_ai_factories()


def test_get_ocr_service_falls_back_to_http_ocr_provider_without_gemini(monkeypatch):
    from services.ocr_provider import HttpOCRProvider
    from services.ocr_service import LiveOCRService, get_ocr_service

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OCR_API_KEY", "test-vision-key")
    _reset_ai_factories()
    try:
        service = get_ocr_service()
        assert isinstance(service, LiveOCRService)
        assert isinstance(service._provider, HttpOCRProvider)
    finally:
        monkeypatch.setenv("OCR_API_KEY", "")
        _reset_ai_factories()


def test_get_ocr_service_not_configured_when_neither_gemini_nor_ocr_key_set(monkeypatch):
    from services.ocr_service import NotConfiguredOCRService, get_ocr_service

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OCR_API_KEY", "")
    _reset_ai_factories()
    assert isinstance(get_ocr_service(), NotConfiguredOCRService)


def test_get_stt_service_prefers_gemini_when_configured(monkeypatch):
    from services.stt_service import LiveSpeechToTextService, get_stt_service

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    monkeypatch.setenv("STT_API_KEY", "should-not-be-used")
    _reset_ai_factories()
    try:
        service = get_stt_service()
        assert isinstance(service, LiveSpeechToTextService)
        assert isinstance(service._provider, GeminiSTTProvider)
        assert service._provider_label == "gemini"
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("STT_API_KEY", "")
        _reset_ai_factories()


def test_get_stt_service_falls_back_to_http_stt_provider_without_gemini(monkeypatch):
    from services.stt_provider import HttpSpeechToTextProvider
    from services.stt_service import LiveSpeechToTextService, get_stt_service

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("STT_API_KEY", "test-whisper-key")
    _reset_ai_factories()
    try:
        service = get_stt_service()
        assert isinstance(service, LiveSpeechToTextService)
        assert isinstance(service._provider, HttpSpeechToTextProvider)
    finally:
        monkeypatch.setenv("STT_API_KEY", "")
        _reset_ai_factories()


def test_get_stt_service_not_configured_when_neither_gemini_nor_stt_key_set(monkeypatch):
    from services.stt_service import NotConfiguredSpeechToTextService, get_stt_service

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("STT_API_KEY", "")
    _reset_ai_factories()
    assert isinstance(get_stt_service(), NotConfiguredSpeechToTextService)


# --- Language coverage through a real GeminiTextProvider (spec section 25) ---

_REQUIRED_LANGUAGE_PAIRS = [
    ("en", "ru"), ("en", "uk"), ("en", "he"),
    ("de", "ru"), ("he", "uk"), ("es", "de"),
    ("fr", "ru"), ("it", "uk"), ("uk", "de"),
]


@pytest.mark.parametrize("language_code,translation_language", _REQUIRED_LANGUAGE_PAIRS)
async def test_analyze_text_through_gemini_provider_carries_the_right_languages(
    monkeypatch, language_code, translation_language,
):
    """Proves the language-plumbing (learning vs interface language, never
    swapped, never defaulted to Russian) survives the provider swap
    unchanged: the exact same LiveAIService/prompt/Pydantic-parser code
    path runs against a real GeminiTextProvider instead of HttpAIProvider
    - only the transport differs, so this is really a regression guard on
    the wiring, not a re-test of the (untouched) prompt content itself."""
    from services.ai_service import LiveAIService

    captured = {}
    body = _ok_body(
        '{"original_text": "hello", "translation": "hi-there", "pronunciation": "heh-loh", '
        '"key_words": [], "useful_phrases": []}'
    )

    async def fake_post(self, url, *, headers, json):
        captured["json"] = json
        return _FakeResponse(200, body)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = GeminiTextProvider(api_key="k", model="m")
    svc = LiveAIService(
        provider=provider, model="m", provider_label="gemini",
        max_retries=0, requests_per_minute=1000, requests_per_day=1000,
    )

    result = await svc.analyze_text(
        "hello", language_code=language_code, translation_language=translation_language,
        interface_language=translation_language, user_id=1,
    )

    assert result.translation == "hi-there"
    assert result.pronunciation == "heh-loh"
    user_prompt = captured["json"]["contents"][0]["parts"][0]["text"]
    assert language_code in user_prompt
    assert translation_language in user_prompt


# --- services.ai_diagnostics.test_gemini_connection() ---

async def test_gemini_connection_missing_api_key_is_reported(monkeypatch):
    from services.ai_diagnostics import test_gemini_connection

    monkeypatch.setenv("GEMINI_API_KEY", "")
    config.get_settings.cache_clear()

    result = await test_gemini_connection()

    assert result.ok is False
    assert result.reason == "missing_api_key"


async def test_gemini_connection_disabled_is_reported_even_with_key(monkeypatch):
    from services.ai_diagnostics import test_gemini_connection

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    monkeypatch.setenv("GEMINI_ENABLED", "false")
    config.get_settings.cache_clear()
    try:
        result = await test_gemini_connection()
        assert result.ok is False
        assert result.reason == "disabled"
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("GEMINI_ENABLED", "true")
        config.get_settings.cache_clear()


async def test_gemini_connection_success_reports_ok(monkeypatch):
    from services.ai_diagnostics import test_gemini_connection

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    config.get_settings.cache_clear()
    try:
        provider = MockAIProvider(response='{"status": "ok"}')
        result = await test_gemini_connection(provider=provider)
        assert result.ok is True
        assert provider.calls == 1
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        config.get_settings.cache_clear()


async def test_gemini_connection_unauthorized_is_reported(monkeypatch):
    from services.ai_diagnostics import test_gemini_connection

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    config.get_settings.cache_clear()
    try:
        provider = MockAIProvider(raises=AIAuthenticationError("bad key"))
        result = await test_gemini_connection(provider=provider)
        assert result.ok is False
        assert result.reason == "unauthorized"
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        config.get_settings.cache_clear()


async def test_gemini_connection_api_key_never_appears_in_result(monkeypatch):
    from services.ai_diagnostics import test_gemini_connection

    real_looking_key = "gm-test-0000000000000000000000000000"
    monkeypatch.setenv("GEMINI_API_KEY", real_looking_key)
    config.get_settings.cache_clear()
    try:
        provider = MockAIProvider(raises=AIAuthenticationError("bad key"))
        result = await test_gemini_connection(provider=provider)
        assert real_looking_key not in (result.reason or "")
        assert real_looking_key not in (result.detail or "")
    finally:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        config.get_settings.cache_clear()
