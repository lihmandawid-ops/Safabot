"""Tests for services/ocr_service.py + services/ocr_provider.py and
services/stt_service.py + services/stt_provider.py (bugfix spec sections
17-18): no real OCR/STT API request is ever made - mock providers stand
in for the real OCRProvider/SpeechToTextProvider ABCs, so these exercise
the actual LiveOCRService/LiveSpeechToTextService wiring and the
NotConfigured gate end-to-end.
"""
from __future__ import annotations

import config
from services.media_errors import (
    OCRConfigurationError,
    OCRError,
    OCRUnavailableError,
    STTConfigurationError,
    STTError,
    STTUnavailableError,
)
from services.ocr_provider import OCRProvider
from services.ocr_service import LiveOCRService, NotConfiguredOCRService, get_ocr_service
from services.stt_provider import SpeechToTextProvider
from services.stt_service import LiveSpeechToTextService, NotConfiguredSpeechToTextService, get_stt_service


class MockOCRProvider(OCRProvider):
    def __init__(self, *, text: str | None = None, raises: Exception | None = None) -> None:
        self._text = text
        self._raises = raises
        self.calls = 0

    async def extract_text(self, image_bytes: bytes, *, mime_type: str) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._text or ""


class MockSTTProvider(SpeechToTextProvider):
    def __init__(self, *, text: str | None = None, raises: Exception | None = None) -> None:
        self._text = text
        self._raises = raises
        self.calls = 0

    async def transcribe(self, audio_bytes: bytes, *, mime_type: str, filename: str) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._text or ""


# --- OCR ---

async def test_not_configured_ocr_service_raises_configuration_error():
    service = NotConfiguredOCRService()
    try:
        await service.extract_text_from_image(b"fake", mime_type="image/jpeg", user_id=1)
        assert False, "expected OCRConfigurationError"
    except OCRConfigurationError:
        pass


async def test_live_ocr_service_returns_provider_text():
    provider = MockOCRProvider(text="Hello world")
    service = LiveOCRService(provider=provider, provider_label="mock")
    text = await service.extract_text_from_image(b"fake", mime_type="image/jpeg", user_id=1)
    assert text == "Hello world"
    assert provider.calls == 1


async def test_live_ocr_service_propagates_provider_errors():
    provider = MockOCRProvider(raises=OCRUnavailableError("down"))
    service = LiveOCRService(provider=provider, provider_label="mock")
    try:
        await service.extract_text_from_image(b"fake", mime_type="image/jpeg", user_id=1)
        assert False, "expected OCRError"
    except OCRError:
        pass


def test_get_ocr_service_falls_back_to_not_configured_without_api_key(monkeypatch):
    monkeypatch.setenv("OCR_API_KEY", "")
    config.get_settings.cache_clear()
    get_ocr_service.cache_clear()
    try:
        assert isinstance(get_ocr_service(), NotConfiguredOCRService)
    finally:
        get_ocr_service.cache_clear()
        config.get_settings.cache_clear()


def test_get_ocr_service_returns_live_service_when_configured(monkeypatch):
    monkeypatch.setenv("OCR_API_KEY", "test-key")
    monkeypatch.setenv("OCR_PROVIDER", "test-vision")
    config.get_settings.cache_clear()
    get_ocr_service.cache_clear()
    try:
        assert isinstance(get_ocr_service(), LiveOCRService)
    finally:
        get_ocr_service.cache_clear()
        config.get_settings.cache_clear()


def test_get_ocr_service_respects_disabled_flag(monkeypatch):
    monkeypatch.setenv("OCR_API_KEY", "test-key")
    monkeypatch.setenv("OCR_ENABLED", "false")
    config.get_settings.cache_clear()
    get_ocr_service.cache_clear()
    try:
        assert isinstance(get_ocr_service(), NotConfiguredOCRService)
    finally:
        get_ocr_service.cache_clear()
        config.get_settings.cache_clear()


# --- STT ---

async def test_not_configured_stt_service_raises_configuration_error():
    service = NotConfiguredSpeechToTextService()
    try:
        await service.transcribe_audio(b"fake", mime_type="audio/ogg", filename="voice.ogg", user_id=1)
        assert False, "expected STTConfigurationError"
    except STTConfigurationError:
        pass


async def test_live_stt_service_returns_provider_text():
    provider = MockSTTProvider(text="hello there")
    service = LiveSpeechToTextService(provider=provider, provider_label="mock")
    text = await service.transcribe_audio(b"fake", mime_type="audio/ogg", filename="voice.ogg", user_id=1)
    assert text == "hello there"
    assert provider.calls == 1


async def test_live_stt_service_propagates_provider_errors():
    provider = MockSTTProvider(raises=STTUnavailableError("down"))
    service = LiveSpeechToTextService(provider=provider, provider_label="mock")
    try:
        await service.transcribe_audio(b"fake", mime_type="audio/ogg", filename="voice.ogg", user_id=1)
        assert False, "expected STTError"
    except STTError:
        pass


def test_get_stt_service_falls_back_to_not_configured_without_api_key(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "")
    config.get_settings.cache_clear()
    get_stt_service.cache_clear()
    try:
        assert isinstance(get_stt_service(), NotConfiguredSpeechToTextService)
    finally:
        get_stt_service.cache_clear()
        config.get_settings.cache_clear()


def test_get_stt_service_returns_live_service_when_configured(monkeypatch):
    monkeypatch.setenv("STT_API_KEY", "test-key")
    monkeypatch.setenv("STT_PROVIDER", "test-whisper")
    config.get_settings.cache_clear()
    get_stt_service.cache_clear()
    try:
        assert isinstance(get_stt_service(), LiveSpeechToTextService)
    finally:
        get_stt_service.cache_clear()
        config.get_settings.cache_clear()
