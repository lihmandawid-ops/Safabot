"""🆘 Поддержка (real user request): the "report a bug to the operator"
message, shown identically from ⚙️ Настройки and /help - one place so the
two entry points can never drift apart.
"""
from __future__ import annotations

from config import get_settings
from utils.i18n import t


def support_message(language: str) -> str:
    contact = get_settings().support_contact
    if not contact:
        return t("support.not_configured", language)
    return t("support.header", language, contact=contact)
