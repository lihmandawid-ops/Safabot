"""💎 PRO / Telegram Stars subscription (spec sections 25-26).

TODO(stage-13): implement against services/subscription_service.py and
Telegram's Stars invoice API (telegram.Bot.send_invoice with
currency="XTR"). Routed from handlers/menu.py, which currently shows a
"coming soon" message for the PRO button instead of calling into this
module.
"""
from __future__ import annotations
