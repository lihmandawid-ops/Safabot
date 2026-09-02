"""Google Gemini integration (spec: "Gemini = PRIMARY AI").

Implements the EXISTING provider seam unchanged - services.ai_provider.
AIProvider (text) - against Gemini's `generateContent` REST endpoint, so
nothing above the provider layer (AIService, and everything built on top
of it) needs to know Gemini exists. Callers never talk to this module
directly; only the get_ai_service() factory constructs this class.

Never logs the API key: it is sent only via the `x-goog-api-key` header
(Google's own recommended alternative to the `?key=` query parameter,
specifically because a query parameter can end up in proxy/access logs -
see https://ai.google.dev/gemini-api - never a header, never any log line
this module writes).
"""
from __future__ import annotations

import httpx

from services.ai_errors import (
    AIAuthenticationError,
    AIInvalidResponseError,
    AIRateLimitedError,
    AITimeoutError,
    AIUnavailableError,
)
from services.ai_provider import AIProvider
from utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


class _GeminiTransportError(Exception):
    """Internal only - carries the outcome of one generateContent HTTP
    call so all three provider classes below can share `_generate_content`
    instead of triplicating request/response/status-code handling, while
    still each raising THEIR OWN domain's typed exception (never this
    class) to their actual caller."""

    def __init__(self, kind: str, detail: str) -> None:
        # kind: "timeout" | "network" | "auth" | "rate_limited" | "unavailable" | "invalid"
        self.kind = kind
        self.detail = detail
        super().__init__(detail)


async def _generate_content(
    *, api_key: str, model: str, base_url: str | None, timeout: float,
    parts: list[dict], system_instruction: str | None = None, response_mime_type: str | None = None,
    proxy: str | None = None,
) -> str:
    """One Gemini `models/{model}:generateContent` call. `parts` can mix a
    text part with an inlineData (base64 image/audio) part for multimodal
    input. Returns the raw text of the first candidate - possibly an
    EMPTY string, which is a valid answer for OCR ("no text in the
    image")/STT ("no speech in the audio") and is the caller's job to
    interpret; only a genuinely malformed/absent response raises here.

    `proxy`: some regions get HTTP 400 "User location is not supported
    for the API use" from Google regardless of API key validity - this
    routes ONLY this Gemini request through a forward proxy in a
    supported region when set (GEMINI_PROXY_URL), leaving DeepSeek/
    Telegram/OCR-legacy traffic (their own separate httpx clients)
    completely untouched.
    """
    url_base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{url_base}/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    generation_config: dict = {"temperature": 0.3, "maxOutputTokens": 4096}
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type

    payload: dict = {"contents": [{"role": "user", "parts": parts}], "generationConfig": generation_config}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise _GeminiTransportError("timeout", "Gemini request timed out") from exc
    except httpx.HTTPError as exc:
        raise _GeminiTransportError("network", f"Gemini request failed: {type(exc).__name__}") from exc

    logger.debug("Gemini responded model=%s status=%s", model, response.status_code)

    if response.status_code in (401, 403):
        raise _GeminiTransportError("auth", f"Gemini rejected the request (HTTP {response.status_code})")
    if response.status_code == 429:
        raise _GeminiTransportError("rate_limited", "Gemini rate-limited this request (HTTP 429)")
    if response.status_code >= 500:
        raise _GeminiTransportError("unavailable", f"Gemini returned HTTP {response.status_code}")
    if response.status_code >= 400:
        raise _GeminiTransportError("invalid", f"Gemini returned HTTP {response.status_code}")

    try:
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        # Covers a malformed body AND a safety-blocked response (no
        # "content"/"parts" on the candidate) - both are "nothing usable
        # came back", never a crash.
        raise _GeminiTransportError("invalid", "Gemini returned an unexpected response shape") from exc

    if not isinstance(text, str):
        raise _GeminiTransportError("invalid", "Gemini returned a non-text response")
    return text


def _inline_data_part(data: bytes, *, mime_type: str) -> dict:
    return {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(data).decode("ascii")}}


_AI_ERROR_MAP = {
    "timeout": AITimeoutError,
    "network": AIUnavailableError,
    "auth": AIAuthenticationError,
    "rate_limited": AIRateLimitedError,
    "unavailable": AIUnavailableError,
    "invalid": AIInvalidResponseError,
}
class GeminiTextProvider(AIProvider):
    """Primary AIProvider implementation. Same system+user -> raw-JSON-text
    contract as services.ai_provider.HttpAIProvider, so every existing
    prompt and Pydantic parser in services/ai_service.py works completely
    unchanged - only the transport differs."""

    def __init__(
        self, *, api_key: str, model: str, base_url: str | None = None, timeout: float = 30.0,
        proxy: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout = timeout
        self._proxy = proxy

    async def complete(self, *, system: str, user: str) -> str:
        try:
            text = await _generate_content(
                api_key=self._api_key, model=self._model, base_url=self._base_url, timeout=self._timeout,
                parts=[{"text": user}], system_instruction=system, response_mime_type="application/json",
                proxy=self._proxy,
            )
        except _GeminiTransportError as exc:
            raise _AI_ERROR_MAP[exc.kind](exc.detail) from exc

        if not text.strip():
            raise AIInvalidResponseError("Gemini returned an empty response")
        return text
