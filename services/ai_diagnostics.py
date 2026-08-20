"""A safe, minimal connectivity check for the configured AI provider
(DeepSeek by default) - spec section 2: "Создай безопасную функцию
проверки подключения: test_deepseek_connection()".

Never logs the API key. On success logs exactly "DeepSeek connection: OK"
(per spec); on failure logs the precise technical reason (missing key,
invalid key, rate limit, timeout, network error, invalid response) so an
operator can fix the right thing without guessing - and never the key.

Safe to call at bot startup (see bot.py's on_startup) or from an admin
command: it never raises and never blocks anything on failure - a broken
AI connection must not stop the bot from serving the rest of its features.
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

    try:
        raw = await live_provider.complete(system=_TEST_SYSTEM, user=_TEST_USER)
    except AIAuthenticationError:
        # A provider's 401/403 doesn't distinguish "malformed key" from
        # "valid-looking but rejected key" - both spec categories map here.
        logger.warning("DeepSeek connection: FAILED (unauthorized)")
        return ConnectionTestResult(ok=False, reason="unauthorized", detail="provider rejected the API key (401/403)")
    except AIRateLimitedError:
        logger.warning("DeepSeek connection: FAILED (rate_limited)")
        return ConnectionTestResult(ok=False, reason="rate_limited", detail="provider rate-limited this request (429)")
    except AITimeoutError:
        logger.warning("DeepSeek connection: FAILED (timeout)")
        return ConnectionTestResult(
            ok=False, reason="timeout", detail=f"no response within {settings.ai_timeout_seconds}s"
        )
    except AIUnavailableError:
        logger.warning("DeepSeek connection: FAILED (network_error)")
        return ConnectionTestResult(ok=False, reason="network_error", detail="network error or provider 5xx")
    except AIInvalidResponseError:
        logger.warning("DeepSeek connection: FAILED (invalid_response)")
        return ConnectionTestResult(ok=False, reason="invalid_response", detail="provider returned an unexpected response")
    except Exception as exc:  # pragma: no cover - genuinely unexpected
        logger.warning("DeepSeek connection: FAILED (unknown_error)")
        return ConnectionTestResult(ok=False, reason="unknown_error", detail=type(exc).__name__)

    if not raw or not raw.strip():
        logger.warning("DeepSeek connection: FAILED (invalid_response)")
        return ConnectionTestResult(ok=False, reason="invalid_response", detail="empty response body")

    logger.info("DeepSeek connection: OK")
    return ConnectionTestResult(ok=True)
