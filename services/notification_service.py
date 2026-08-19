"""Decides what (if anything) to send each user for a given notification
slot, and does the sending + idempotent logging (learning-core stage,
sections 13-19, 29).

scheduler/notifications.py is a thin timer; all the "what does this
message say, and should it be sent at all" logic lives here so it can be
unit-tested with a mocked `bot` and without a real Telegram connection
(spec section 32) or real wall-clock waiting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from telegram import InlineKeyboardMarkup

from database.database import session_scope
from database.repositories import notifications as notifications_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from keyboards.learning import start_keyboard, start_review_keyboard
from services import learning_service
from utils.i18n import t
from utils.logging import get_logger
from utils.time import local_hour_minute, local_today, utc_now

logger = get_logger(__name__)
_LANG = "ru"

SLOT_MORNING = "morning"
SLOT_AFTERNOON = "afternoon"
SLOT_EVENING = "evening"
SLOTS = (SLOT_MORNING, SLOT_AFTERNOON, SLOT_EVENING)


@dataclass(frozen=True)
class NotificationContent:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None


def _slot_time(user, slot: str):
    return {"morning": user.morning_time, "afternoon": user.afternoon_time, "evening": user.evening_time}[slot]


def _is_due_now(user, slot: str, now: datetime) -> bool:
    slot_time = _slot_time(user, slot)
    hour, minute = local_hour_minute(now, user.timezone)
    return (hour, minute) == (slot_time.hour, slot_time.minute)


async def _build_content(session, user, slot: str, now: datetime) -> NotificationContent | None:
    """None means there is nothing worth sending (spec sections 14-16,
    32: never send a meaningless notification)."""
    current = await user_languages_repo.get_current_language(session, user.id)
    if current is None:
        return None

    due = await learning_service.get_due_reviews(
        session, user_id=user.id, language_code=current.language_code, now=now
    )

    if slot == SLOT_MORNING:
        new_words = await learning_service.get_new_words_for_today(session, user=user, user_language=current, now=now)
        if not due and not new_words:
            return None
        if new_words:
            text = t("notification.morning.with_new", _LANG, new_count=len(new_words), due_count=len(due))
        else:
            text = t("notification.morning.reviews_only", _LANG, due_count=len(due))
        return NotificationContent(text, start_keyboard())

    if slot == SLOT_AFTERNOON:
        if not due:
            return None
        return NotificationContent(t("notification.afternoon.text", _LANG, due_count=len(due)), start_review_keyboard())

    if slot == SLOT_EVENING:
        if due:
            return NotificationContent(t("notification.evening.due", _LANG, due_count=len(due)), start_review_keyboard())
        if user.last_learning_date == local_today(now, user.timezone):
            return NotificationContent(t("notification.evening.done", _LANG))
        return None

    raise ValueError(f"Unknown notification slot: {slot!r}")  # pragma: no cover - exhaustive guard


async def send_for_slot(bot, slot: str, *, now: datetime | None = None) -> int:
    """Checks every notifications-enabled user against `slot`, sends (via
    `bot.send_message`) whatever's due, and logs it - safe to call more
    than once for the same slot/day since NotificationLog is checked
    before every send (spec section 29). A DB transaction is never held
    open across the network call to Telegram: check -> send -> log are
    three separate session_scope() blocks.
    """
    now = now if now is not None else utc_now()
    sent_count = 0

    async with session_scope() as session:
        users = await users_repo.get_notifiable_users(session)

    for user in users:
        if not _is_due_now(user, slot, now):
            continue

        scheduled_date = local_today(now, user.timezone)

        async with session_scope() as session:
            already_sent = await notifications_repo.was_sent(
                session, user_id=user.id, notification_type=slot, scheduled_date=scheduled_date
            )
            if already_sent:
                continue
            content = await _build_content(session, user, slot, now)

        if content is None:
            continue

        try:
            await bot.send_message(chat_id=user.telegram_id, text=content.text, reply_markup=content.reply_markup)
        except Exception:
            logger.exception("Failed to send %s notification to telegram_id=%s", slot, user.telegram_id)
            continue

        async with session_scope() as session:
            await notifications_repo.log_sent(session, user_id=user.id, notification_type=slot, scheduled_date=scheduled_date)
        sent_count += 1

    return sent_count


async def send_due_notifications(bot, *, now: datetime | None = None) -> int:
    """Checks all three slots in one pass - what scheduler/notifications.py's
    poller calls on each tick."""
    now = now if now is not None else utc_now()
    total = 0
    for slot in SLOTS:
        total += await send_for_slot(bot, slot, now=now)
    return total
