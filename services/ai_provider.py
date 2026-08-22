"""Talks to an actual AI API and back - nothing else. services/ai_service.py
is the only caller: it builds prompts, decides retries/rate limits, and
parses/validates the result; this module's only job is "send this system
+ user prompt, get raw text back, or raise a typed services.ai_errors
exception". Swappable by design (spec section 2) - AIProvider is the
seam a different backend (Anthropic, a local model, ...) would implement
instead of HttpAIProvider.

Never logs the API key: only sends it as an Authorization header, and any
logging here is limited to status codes/timings, never headers or bodies
that might contain it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from services.ai_errors import (
    AIAuthenticationError,
    AIError,
    AIInvalidResponseError,
    AIRateLimitedError,
    AITimeoutError,
    AIUnavailableError,
)
from utils.logging import get_logger

logger = get_logger(__name__)


class AIProvider(ABC):
    @abstractmethod
    async def complete(self, *, system: str, user: str) -> str:
        """One chat-completion call: `system` is the instruction/context,
        `user` is the actual request. Returns the raw text of the model's
        reply (expected to be a JSON document - parsing/validation is the
        caller's job, not the provider's). Raises a services.ai_errors
        subclass on any failure; never returns None and never raises a
        bare Exception."""


class FallbackAIProvider(AIProvider):
    """Gemini = PRIMARY, DeepSeek (or whatever AI_* is configured to) =
    FALLBACK for text-only tasks (spec: "Gemini недоступен -> text-only
    запрос переходит на DeepSeek. Gemini снова работает -> Safabot
    возвращается к Gemini").

    Composes two existing AIProvider implementations behind the same
    single-provider seam services/ai_service.py already depends on - so
    LiveAIService, its retry loop, and every prompt/parser need zero
    changes to gain a fallback; they just get handed one of these instead
    of a bare HttpAIProvider/GeminiTextProvider.

    ALWAYS tries `primary` first on every call, independent of whether the
    previous call fell back - a Gemini outage is never "sticky" past the
    single request that hit it, so the very next call automatically goes
    back to Gemini the moment it recovers.
    """

    def __init__(self, *, primary: AIProvider, secondary: AIProvider, primary_label: str, secondary_label: str) -> None:
        self._primary = primary
        self._secondary = secondary
        self._primary_label = primary_label
        self._secondary_label = secondary_label

    async def complete(self, *, system: str, user: str) -> str:
        try:
            return await self._primary.complete(system=system, user=user)
        except AIError as exc:
            logger.warning(
                "Primary AI provider (%s) failed (%s), falling back to %s",
                self._primary_label, type(exc).__name__, self._secondary_label,
            )
            return await self._secondary.complete(system=system, user=user)


class HttpAIProvider(AIProvider):
    """OpenAI-compatible Chat Completions API over HTTP (works against
    OpenAI itself, and against any OpenAI-compatible gateway by setting
    AI_BASE_URL - Azure OpenAI, OpenRouter, a self-hosted vLLM/Ollama
    gateway, etc). Requests JSON-mode output so the model is nudged
    toward the structured shape services/ai_models.py expects.
    """

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, *, api_key: str, model: str, base_url: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout

    async def complete(self, *, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            # Explicit, generous cap - relying on a provider's own default
            # risks a silently-truncated (and therefore invalid) JSON
            # response for the larger prompts (8-word generation, a
            # 2000-character text analysis).
            "max_tokens": 4096,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise AITimeoutError("AI request timed out") from exc
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"AI request failed: {type(exc).__name__}") from exc

        logger.debug("AI provider responded model=%s status=%s", self._model, response.status_code)

        if response.status_code in (401, 403):
            raise AIAuthenticationError(f"AI provider rejected the request (HTTP {response.status_code})")
        if response.status_code == 429:
            raise AIRateLimitedError("AI provider rate-limited this request (HTTP 429)")
        if response.status_code >= 500:
            raise AIUnavailableError(f"AI provider returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise AIInvalidResponseError(f"AI provider returned HTTP {response.status_code}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIInvalidResponseError("AI provider returned an unexpected response shape") from exc

        if not isinstance(content, str) or not content.strip():
            raise AIInvalidResponseError("AI provider returned an empty response")
        return content
