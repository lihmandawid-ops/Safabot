"""Talks to an actual OCR (image -> text) API and back - nothing else.
services/ocr_service.py is the only caller. OCRProvider is the seam a
real vision/OCR backend plugs into; HttpOCRProvider is a generic
OpenAI-compatible vision-chat implementation (works against any provider
whose Chat Completions API accepts an `image_url` content part - e.g.
OpenAI's own gpt-4o-mini, or an OpenAI-compatible gateway in front of one).

Bugfix spec section 17 is explicit: the configured AI chat model
(DeepSeek) is not documented as vision-capable, so that must never be
silently assumed - OCR is its own, independently-configured provider
(OCR_API_KEY/OCR_BASE_URL/OCR_MODEL), completely separate from AI_API_KEY,
so a real OCR backend can be plugged in later without touching
handlers/media.py at all.
"""
from __future__ import annotations

import base64
from abc import ABC, abstractmethod

import httpx

from services.media_errors import (
    OCRAuthenticationError,
    OCRInvalidResponseError,
    OCRTimeoutError,
    OCRUnavailableError,
)
from utils.logging import get_logger

logger = get_logger(__name__)

_OCR_PROMPT = (
    "Extract all readable text from this image, exactly as it appears, preserving line breaks. "
    "Respond with ONLY the extracted text - no commentary, no markdown, no surrounding quotes. "
    "If there is no readable text in the image, respond with an empty string."
)


class OCRProvider(ABC):
    @abstractmethod
    async def extract_text(self, image_bytes: bytes, *, mime_type: str) -> str:
        """Returns the text found in the image (possibly empty string).
        Raises a services.media_errors OCR* subclass on any failure; never
        returns None and never raises a bare Exception."""


class HttpOCRProvider(OCRProvider):
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, *, api_key: str, model: str, base_url: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout

    async def extract_text(self, image_bytes: bytes, *, mime_type: str) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 2048,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise OCRTimeoutError("OCR request timed out") from exc
        except httpx.HTTPError as exc:
            raise OCRUnavailableError(f"OCR request failed: {type(exc).__name__}") from exc

        logger.debug("OCR provider responded model=%s status=%s", self._model, response.status_code)

        if response.status_code in (401, 403):
            raise OCRAuthenticationError(f"OCR provider rejected the request (HTTP {response.status_code})")
        if response.status_code >= 500:
            raise OCRUnavailableError(f"OCR provider returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise OCRInvalidResponseError(f"OCR provider returned HTTP {response.status_code}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise OCRInvalidResponseError("OCR provider returned an unexpected response shape") from exc

        if not isinstance(content, str):
            raise OCRInvalidResponseError("OCR provider returned a non-text response")
        return content.strip()
