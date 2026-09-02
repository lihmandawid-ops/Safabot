"""Tests for services/ai_diagnostics.test_deepseek_connection() (DeepSeek-
integration spec section 2). Never touches the real network - either the
autouse AI_API_KEY="" isolation (tests/conftest.py) exercises the "not
configured" paths, or a MockDeepSeekProvider stands in for the transport.
"""
from __future__ import annotations

import config
from services.ai_diagnostics import test_deepseek_connection
from services.ai_errors import (
    AIAuthenticationError,
    AIInvalidResponseError,
    AIRateLimitedError,
    AITimeoutError,
    AIUnavailableError,
)
from services.ai_provider import AIProvider


class MockDeepSeekProvider(AIProvider):
    """Returns (or raises) one scripted response - never makes a real
    HTTP request to DeepSeek or anywhere else."""

    def __init__(self, response: str | None = None, *, raises: Exception | None = None):
        self._response = response
        self._raises = raises
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._response


def _configure(monkeypatch, *, api_key: str = "sk-fake-test-key", enabled: bool = True):
    monkeypatch.setenv("AI_API_KEY", api_key)
    monkeypatch.setenv("AI_ENABLED", "true" if enabled else "false")
    config.get_settings.cache_clear()


async def test_missing_api_key_reports_missing_api_key(monkeypatch):
    # The autouse fixture already forces AI_API_KEY="" - this is explicit
    # for clarity/robustness against fixture changes.
    monkeypatch.setenv("AI_API_KEY", "")
    config.get_settings.cache_clear()

    result = await test_deepseek_connection()

    assert result.ok is False
    assert result.reason == "missing_api_key"


async def test_disabled_reports_disabled_even_with_a_key_present(monkeypatch):
    _configure(monkeypatch, enabled=False)

    result = await test_deepseek_connection()

    assert result.ok is False
    assert result.reason == "disabled"


async def test_successful_connection_reports_ok(monkeypatch):
    _configure(monkeypatch)
    provider = MockDeepSeekProvider('{"status": "ok"}')

    result = await test_deepseek_connection(provider=provider)

    assert result.ok is True
    assert provider.calls == 1


async def test_unauthorized_key_is_reported(monkeypatch):
    _configure(monkeypatch)
    provider = MockDeepSeekProvider(raises=AIAuthenticationError("bad key"))

    result = await test_deepseek_connection(provider=provider)

    assert result.ok is False
    assert result.reason == "unauthorized"


async def test_rate_limit_is_reported(monkeypatch):
    _configure(monkeypatch)
    provider = MockDeepSeekProvider(raises=AIRateLimitedError("429"))

    result = await test_deepseek_connection(provider=provider)

    assert result.ok is False
    assert result.reason == "rate_limited"


async def test_timeout_is_reported(monkeypatch):
    _configure(monkeypatch)
    provider = MockDeepSeekProvider(raises=AITimeoutError("timed out"))

    result = await test_deepseek_connection(provider=provider)

    assert result.ok is False
    assert result.reason == "timeout"


async def test_network_error_is_reported(monkeypatch):
    _configure(monkeypatch)
    provider = MockDeepSeekProvider(raises=AIUnavailableError("connection refused"))

    result = await test_deepseek_connection(provider=provider)

    assert result.ok is False
    assert result.reason == "network_error"


async def test_invalid_response_shape_is_reported(monkeypatch):
    _configure(monkeypatch)
    provider = MockDeepSeekProvider(raises=AIInvalidResponseError("bad shape"))

    result = await test_deepseek_connection(provider=provider)

    assert result.ok is False
    assert result.reason == "invalid_response"


async def test_empty_response_is_reported_as_invalid(monkeypatch):
    _configure(monkeypatch)
    provider = MockDeepSeekProvider("")

    result = await test_deepseek_connection(provider=provider)

    assert result.ok is False
    assert result.reason == "invalid_response"


async def test_api_key_never_appears_in_result(monkeypatch):
    real_looking_key = "sk-test-0000000000000000000000000000"
    _configure(monkeypatch, api_key=real_looking_key)
    provider = MockDeepSeekProvider(raises=AIAuthenticationError("bad key"))

    result = await test_deepseek_connection(provider=provider)

    assert real_looking_key not in (result.reason or "")
    assert real_looking_key not in (result.detail or "")
