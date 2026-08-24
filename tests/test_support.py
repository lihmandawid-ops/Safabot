"""Tests for utils/support.py (real user request: a way to report a bug
straight to the operator) - the shared message both ⚙️ Настройки -> 🆘
Поддержка and /help render.
"""
from __future__ import annotations

import config


def test_support_message_shows_not_configured_when_contact_is_unset(monkeypatch):
    monkeypatch.setenv("SUPPORT_CONTACT", "")
    config.get_settings.cache_clear()

    from utils.support import support_message

    text = support_message("ru")
    assert "не настроена" in text
    assert "@" not in text


def test_support_message_includes_the_configured_contact(monkeypatch):
    monkeypatch.setenv("SUPPORT_CONTACT", "@safabot_support")
    config.get_settings.cache_clear()

    from utils.support import support_message

    text = support_message("ru")
    assert "@safabot_support" in text


def test_support_message_respects_language(monkeypatch):
    monkeypatch.setenv("SUPPORT_CONTACT", "@safabot_support")
    config.get_settings.cache_clear()

    from utils.support import support_message

    assert "Support" in support_message("en")
    assert "Поддержка" in support_message("ru")
