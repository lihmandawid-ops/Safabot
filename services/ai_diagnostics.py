"""A safe, minimal connectivity check for the configured AI provider(s) -
spec section 2: "Создай безопасную функцию проверки подключения:
test_deepseek_connection()", extended to cover Gemini and Vercel AI
Gateway once they joined as additional provider options (Gemini
integration stage).

Never logs an API key. On success logs exactly "<Provider> connection:
OK" (per spec, for DeepSeek); on failure logs the precise technical
reason (missing key, invalid key, rate limit, timeout, network error,
invalid response) so an operator can fix the right thing without
guessing - and never the key.

Safe to call at bot startup (see bot.py's on_startup) or from an admin
command: none of these functions ever raise or block anything on
failure - a broken AI connection must not stop the bot from serving the
rest of its features.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import get_settings
from services.ai_errors import (
    AIAuthenticationError,
    AIInvalidResponseError,
    AIRateLimitedError,
    AITimeoutError,
    AIUnavailableError,
)
from services.ai_provider import AIProvider, HttpAIProvider
from utils.logging import get_logger

logger = get_logger(__name__)

# Deliberately tiny (spec section 22: cost control) - just enough to prove
# the round trip works, in JSON mode since that's what every real prompt uses.
_TEST_SYSTEM = 'Respond with ONLY this exact JSON object, nothing else: {"status": "ok"}'
_TEST_USER = "ping"


@dataclass
class ConnectionTestResult:
    ok: bool
    # Machine-readable when ok=False: "disabled" | "missing_api_key" |
    # "unauthorized" | "rate_limited" | "timeout" | "network_error" |
    # "invalid_response" | "unknown_error".
    reason: str | None = None
    # Human-readable, always safe to log/display - never contains the key.
    detail: str | None = None


async def _run_round_trip(label: str, provider: AIProvider, *, timeout_seconds: float) -> ConnectionTestResult:
    """Shared round-trip + status-code-to-reason mapping for every
    connection check below - each public function only differs in which
    settings gate it (missing key/disabled) and which provider it builds,
    never in how the actual request or its outcome is handled."""
    try:
        raw = await provider.complete(system=_TEST_SYSTEM, user=_TEST_USER)
    except AIAuthenticationError:
        # A provider's 401/403 doesn't distinguish "malformed key" from
        # "valid-looking but rejected key" - both spec categories map here.
        logger.warning("%s connection: FAILED (unauthorized)", label)
        return ConnectionTestResult(ok=False, reason="unauthorized", detail="provider rejected the API key (401/403)")
    except AIRateLimitedError:
        logger.warning("%s connection: FAILED (rate_limited)", label)
        return ConnectionTestResult(ok=False, reason="rate_limited", detail="provider rate-limited this request (429)")
    except AITimeoutError:
        logger.warning("%s connection: FAILED (timeout)", label)
        return ConnectionTestResult(ok=False, reason="timeout", detail=f"no response within {timeout_seconds}s")
    except AIUnavailableError:
        logger.warning("%s connection: FAILED (network_error)", label)
        return ConnectionTestResult(ok=False, reason="network_error", detail="network error or provider 5xx")
    except AIInvalidResponseError:
        logger.warning("%s connection: FAILED (invalid_response)", label)
        return ConnectionTestResult(ok=False, reason="invalid_response", detail="provider returned an unexpected response")
    except Exception as exc:  # pragma: no cover - genuinely unexpected
        logger.warning("%s connection: FAILED (unknown_error)", label)
        return ConnectionTestResult(ok=False, reason="unknown_error", detail=type(exc).__name__)

    if not raw or not raw.strip():
        logger.warning("%s connection: FAILED (invalid_response)", label)
        return ConnectionTestResult(ok=False, reason="invalid_response", detail="empty response body")

    logger.info("%s connection: OK", label)
    return ConnectionTestResult(ok=True)


async def test_deepseek_connection(*, provider: AIProvider | None = None) -> ConnectionTestResult:
    """Reads the API key from the existing config (services.ai_service /
    config.get_settings - never a new/second key), performs one minimal
    request, and reports whether the provider is actually reachable and
    answering correctly. Pass `provider` in tests to inject a
    MockDeepSeekProvider instead of making a real HTTP call.
    """
    settings = get_settings()

    if not settings.ai_enabled:
        logger.warning("DeepSeek connection: FAILED (disabled)")
        return ConnectionTestResult(ok=False, reason="disabled", detail="AI_ENABLED=false")
    if not settings.ai_api_key:
        logger.warning("DeepSeek connection: FAILED (missing_api_key)")
        return ConnectionTestResult(ok=False, reason="missing_api_key", detail="AI_API_KEY is not set")

    live_provider = provider or HttpAIProvider(
        api_key=settings.ai_api_key, model=settings.ai_model,
        base_url=settings.ai_base_url, timeout=settings.ai_timeout_seconds,
    )
    return await _run_round_trip("DeepSeek", live_provider, timeout_seconds=settings.ai_timeout_seconds)


async def test_gemini_connection(*, provider: AIProvider | None = None) -> ConnectionTestResult:
    """Same minimal round-trip as test_deepseek_connection(), against the
    configured Gemini provider (GEMINI_API_KEY/GEMINI_MODEL). Reads from
    the existing config - never a second/new key. Pass `provider` in
    tests to inject a mock instead of making a real HTTP call."""
    settings = get_settings()

    if not settings.gemini_enabled:
        logger.warning("Gemini connection: FAILED (disabled)")
        return ConnectionTestResult(ok=False, reason="disabled", detail="GEMINI_ENABLED=false")
    if not settings.gemini_api_key:
        logger.warning("Gemini connection: FAILED (missing_api_key)")
        return ConnectionTestResult(ok=False, reason="missing_api_key", detail="GEMINI_API_KEY is not set")

    if provider is None:
        from services.gemini_provider import GeminiTextProvider

        provider = GeminiTextProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_text_model or settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout=settings.ai_timeout_seconds,
            proxy=settings.gemini_proxy_url,
        )
    return await _run_round_trip("Gemini", provider, timeout_seconds=settings.ai_timeout_seconds)


async def test_ai_gateway_connection(*, provider: AIProvider | None = None) -> ConnectionTestResult:
    """Same minimal round-trip, against the configured Vercel AI Gateway
    (AI_GATEWAY_API_KEY/AI_GATEWAY_MODEL) - useful on its own when direct
    Gemini access is blocked for the server's region ("User location is
    not supported for the API use"). Reads from the existing config -
    never a second/new key. Pass `provider` in tests to inject a mock
    instead of making a real HTTP call."""
    settings = get_settings()

    if not settings.ai_gateway_enabled:
        logger.warning("Vercel AI Gateway connection: FAILED (disabled)")
        return ConnectionTestResult(ok=False, reason="disabled", detail="AI_GATEWAY_ENABLED=false")
    if not settings.ai_gateway_api_key:
        logger.warning("Vercel AI Gateway connection: FAILED (missing_api_key)")
        return ConnectionTestResult(ok=False, reason="missing_api_key", detail="AI_GATEWAY_API_KEY is not set")

    live_provider = provider or HttpAIProvider(
        api_key=settings.ai_gateway_api_key, model=settings.ai_gateway_model,
        base_url=settings.ai_gateway_base_url, timeout=settings.ai_timeout_seconds,
    )
    return await _run_round_trip("Vercel AI Gateway", live_provider, timeout_seconds=settings.ai_timeout_seconds)
