"""Talks to an actual speech-to-text API and back - nothing else.
services/stt_service.py is the only caller. SpeechToTextProvider is the
seam a real STT backend plugs into; HttpSpeechToTextProvider targets the
widely-mirrored OpenAI-compatible `/audio/transcriptions` endpoint
(multipart file upload, Whisper-style) - works against OpenAI itself or
any gateway that mirrors that API shape.

Bugfix spec section 18 is explicit: the configured AI chat model
(DeepSeek) does not do audio transcription, so that must never be
silently assumed - speech-to-text is its own, independently-configured
provider (STT_API_KEY/STT_BASE_URL/STT_MODEL), completely separate from
AI_API_KEY, so a real STT backend can be plugged in later without
touching handlers/media.py at all.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from services.media_errors import (
    STTAuthenticationError,
    STTInvalidResponseError,
    STTTimeoutError,
    STTUnavailableError,
)
from utils.logging import get_logger

logger = get_logger(__name__)


class SpeechToTextProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, *, mime_type: str, filename: str) -> str:
        """Returns the recognized text (possibly empty string). Raises a
        services.media_errors STT* subclass on any failure; never returns
        None and never raises a bare Exception."""


class HttpSpeechToTextProvider(SpeechToTextProvider):
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, *, api_key: str, model: str, base_url: str | None = None, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout

    async def transcribe(self, audio_bytes: bytes, *, mime_type: str, filename: str) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {"file": (filename, audio_bytes, mime_type)}
        data = {"model": self._model}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/audio/transcriptions", headers=headers, files=files, data=data
                )
        except httpx.TimeoutException as exc:
            raise STTTimeoutError("Speech-to-text request timed out") from exc
        except httpx.HTTPError as exc:
            raise STTUnavailableError(f"Speech-to-text request failed: {type(exc).__name__}") from exc

        logger.debug("STT provider responded model=%s status=%s", self._model, response.status_code)

        if response.status_code in (401, 403):
            raise STTAuthenticationError(f"STT provider rejected the request (HTTP {response.status_code})")
        if response.status_code >= 500:
            raise STTUnavailableError(f"STT provider returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise STTInvalidResponseError(f"STT provider returned HTTP {response.status_code}")

        try:
            data = response.json()
            text = data["text"]
        except (ValueError, KeyError, TypeError) as exc:
            raise STTInvalidResponseError("STT provider returned an unexpected response shape") from exc

        if not isinstance(text, str):
            raise STTInvalidResponseError("STT provider returned a non-text response")
        return text.strip()
