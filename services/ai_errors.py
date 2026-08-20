"""Exception hierarchy for the AI layer (services/ai_provider.py,
services/ai_service.py). Every AI-related failure a caller might need to
react to differently is its own subclass; everything else is a generic
AIError.

Callers (DictionaryProvider, WordGenerationService, handlers) catch these
- never a bare `Exception` when they specifically care which failure mode
  it was - and are responsible for the user-facing message (spec section
21: never expose the raw exception, log the technical detail instead).
"""
from __future__ import annotations


class AIError(Exception):
    """Base class for every AI-layer failure."""


class AIConfigurationError(AIError):
    """AI is disabled (AI_ENABLED=false) or has no API key configured.

    Message is written to be shown to the user as-is (spec section 4's
    exact wording): "AI-функции пока не настроены."
    """

    def __init__(self, message: str = "AI-функции пока не настроены.") -> None:
        super().__init__(message)


class AIAuthenticationError(AIError):
    """Provider rejected the API key (401/403). Never retried."""


class AIRateLimitedError(AIError):
    """Either the provider rate-limited us (429), or our own per-user
    in-process limiter (services/ai_service.py's RateLimiter) did."""


class AITimeoutError(AIError):
    """The AI request did not complete within AI_TIMEOUT_SECONDS."""


class AIUnavailableError(AIError):
    """Network failure or the provider returned a server error (5xx)."""


class AIInvalidResponseError(AIError):
    """The provider replied, but the body wasn't valid JSON or didn't
    match the expected schema (services/ai_models.py) - never written to
    the database."""
