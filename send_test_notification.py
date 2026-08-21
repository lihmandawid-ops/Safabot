"""Manual test trigger for the 3x/day review-reminder notification
(notification-scheduler-fix stage, section 25/28) - sends the compact
word-list message right now for one user, without touching their real
schedule: it bypasses morning_time/afternoon_time/evening_time, the
per-slot enabled toggles, and NotificationLog's once-a-day dedup
entirely, so it can be re-run freely and never affects whether the real
scheduled send for that slot still fires later the same day.

Usage (from the project root, with the venv active and BOT_TOKEN set in
.env exactly like bot.py needs):

    python3 send_test_notification.py <telegram_id> [morning|afternoon|evening]

Example:

    python3 send_test_notification.py 123456789 morning

Prints whether a message was actually sent, and why not when it wasn't
(no such user, or nothing worth sending for that slot right now).
"""
from __future__ import annotations

import asyncio
import sys

from telegram import Bot

from config import get_settings
from database.database import dispose_engine
from services.notification_service import SLOT_AFTERNOON, SLOT_EVENING, SLOT_MORNING, send_review_notification_now
from utils.logging import configure_logging

_VALID_SLOTS = {SLOT_MORNING, SLOT_AFTERNOON, SLOT_EVENING}


async def _main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    telegram_id = int(sys.argv[1])
    slot = sys.argv[2] if len(sys.argv) > 2 else SLOT_MORNING
    if slot not in _VALID_SLOTS:
        print(f"Unknown slot {slot!r} - must be one of {sorted(_VALID_SLOTS)}")
        raise SystemExit(1)

    configure_logging()
    bot = Bot(token=get_settings().bot_token)
    try:
        sent = await send_review_notification_now(bot, telegram_id=telegram_id, slot=slot)
    finally:
        await dispose_engine()

    if sent:
        print(f"Sent a {slot} test notification to telegram_id={telegram_id}.")
    else:
        print(
            f"Nothing sent to telegram_id={telegram_id} for slot={slot} - either that "
            "telegram_id has no account, or there's nothing worth sending right now "
            "(no due words and, for the morning slot, no new words ready either)."
        )


if __name__ == "__main__":
    asyncio.run(_main())
