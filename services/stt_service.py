"""SpeechToTextService is the ONLY interface anything else may depend on
for voice-to-text (bugfix spec section 18: 🎤 Разбор голосовой записи).
handlers/media.py calls get_stt_service().transcribe_audio(...), never
services/stt_provider.py directly - the same seam services/ai_service.py
provides for AI features, kept as its own, separate module because
speech-to-text is a genuinely different capability the configured AI chat
model does not claim to have.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

from services.media_errors import STTConfigurationError, STTError
from services.stt_provider import HttpSpeechToTextProvider, SpeechToTextProvider
from utils.logging import get_logger

logger = get_logger(__name__)


class SpeechToTextService(ABC):
    @abstractmethod
    async def transcribe_audio(self, audio_bytes: bytes, *, mime_type: str, filename: str, user_id: int) -> str:
        """Recognized text, or "" if nothing was recognized. Raises a
        services.media_errors.STTError subclass on failure - never None,
        never a bare Exception."""


class NotConfiguredSpeechToTextService(SpeechToTextService):
    """No STT_API_KEY set (or STT_ENABLED=false) - the default state,
    since the configured AI chat model does not do audio transcription.
    Fails immediately and clearly (no network attempt) so handlers/
    media.py can show a friendly "not set up yet" message instead of
    pretending to have understood the recording."""

    async def transcribe_audio(self, audio_bytes, *, mime_type, filename, user_id):
        raise STTConfigurationError()


class LiveSpeechToTextService(SpeechToTextService):
    def __init__(self, *, provider: SpeechToTextProvider, provider_label: str) -> None:
        self._provider = provider
        self._provider_label = provider_label

    async def transcribe_audio(self, audio_bytes, *, mime_type, filename, user_id):
        try:
            text = await self._provider.transcribe(audio_bytes, mime_type=mime_type, filename=filename)
        except STTError as exc:
            logger.warning(
                "STT call failed user_id=%s provider=%s error=%s", user_id, self._provider_label, type(exc).__name__
            )
            raise
        logger.info("STT call succeeded user_id=%s provider=%s chars=%d", user_id, self._provider_label, len(text))
        return text


@lru_cache(maxsize=1)
def get_stt_service() -> SpeechToTextService:
    """Factory selecting the configured STT backend. Cached like
    config.get_settings() - call get_stt_service.cache_clear() after
    changing STT-related environment variables mid-process (tests only).

    Gemini takes over 🎤 Разбор голоса whenever it's configured (it
    transcribes audio natively - no separate Whisper-style endpoint
    needed). No DeepSeek fallback here: DeepSeek does not do audio
    transcription at all. The pre-Gemini STT_* config stays fully intact
    as the path for anyone who hasn't set GEMINI_API_KEY - identical
    behavior to every prior release."""
    from config import get_settings
    from services.gemini_provider import GeminiSTTProvider

    settings = get_settings()

    if settings.gemini_enabled and settings.gemini_api_key:
        provider = GeminiSTTProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_multimodal_model or settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout=settings.ai_timeout_seconds,
        )
        return LiveSpeechToTextService(provider=provider, provider_label="gemini")

    if not settings.stt_enabled or not settings.stt_api_key:
        return NotConfiguredSpeechToTextService()

    provider = HttpSpeechToTextProvider(
        api_key=settings.stt_api_key, model=settings.stt_model, base_url=settings.stt_base_url
    )
    return LiveSpeechToTextService(provider=provider, provider_label=settings.stt_provider)
