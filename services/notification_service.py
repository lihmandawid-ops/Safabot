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
from database.models import UserWord
from database.repositories import notifications as notifications_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from keyboards.learning import start_keyboard
from keyboards.review_now import notification_keyboard
from services import learning_service
from utils.i18n import set_current_language, t
from utils.languages import LANGUAGE_BY_CODE
from utils.logging import get_logger
from utils.time import local_hour_minute, local_today, utc_now
from utils.word_display import translation_for

logger = get_logger(__name__)

SLOT_MORNING = "morning"
SLOT_AFTERNOON = "afternoon"
SLOT_EVENING = "evening"
SLOTS = (SLOT_MORNING, SLOT_AFTERNOON, SLOT_EVENING)

# repetition-system stage section 9: at most 8 words in one automatic
# reminder - matches keyboards.review_now's count picker's own cap so a
# numbered emoji is always available.
_NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣")

# repetition-system stage section 26: the ⚙️ Настройки → 📚 Настройки
# повторения word-count picker's choices - default 4.
NOTIFICATION_WORD_COUNT_OPTIONS: tuple[int, ...] = (4, 6, 8)

_SLOT_ENABLED_FIELD = {
    SLOT_MORNING: "morning_enabled",
    SLOT_AFTERNOON: "afternoon_enabled",
    SLOT_EVENING: "evening_enabled",
}

# Notification-scheduler-fix stage section 9: a user's exact scheduled
# minute is easy to miss entirely if the bot happens to be mid-restart
# right then (real incident: a startup crash-loop silently ate that day's
# sends for anyone whose slot fell inside the outage). A short grace
# window means the very next poll tick after a restart still catches a
# recently-missed slot, while NotificationLog's once-a-day dedup (checked
# separately, in send_for_slot) guarantees only one message ever goes out
# for it - and once the window fully passes with the bot down, that day's
# send for this slot is skipped for good rather than firing hours later.
NOTIFICATION_GRACE_MINUTES = 10


@dataclass(frozen=True)
class NotificationContent:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None
    word_ids: list[int] | None = None


def _slot_time(user, slot: str):
    return {"morning": user.morning_time, "afternoon": user.afternoon_time, "evening": user.evening_time}[slot]


def _is_due_now(user, slot: str, now: datetime) -> bool:
    if not getattr(user, _SLOT_ENABLED_FIELD[slot]):
        return False
    slot_time = _slot_time(user, slot)
    hour, minute = local_hour_minute(now, user.timezone)
    now_minutes = hour * 60 + minute
    slot_minutes = slot_time.hour * 60 + slot_time.minute
    return slot_minutes <= now_minutes < slot_minutes + NOTIFICATION_GRACE_MINUTES


async def _select_review_words(session, user, slot: str, current, now: datetime) -> list[UserWord]:
    """Repetition-system stage sections 9, 14, 15: up to
    user.notification_word_count due words (LEARNING/REVIEW only - the
    same status filter every other review path uses, so PAUSED/DELETED/
    MASTERED/NEW never appear here), preferring words that were not in
    the last reminder of this same slot when there is enough variety to
    avoid repeating the exact same set."""
    due = await learning_service.get_due_reviews(session, user_id=user.id, language_code=current.language_code, now=now)
    count = user.notification_word_count
    if len(due) <= count:
        return due

    recent = await notifications_repo.get_recent_word_ids(session, user_id=user.id, notification_type=slot, limit=1)
    recent_ids = set(recent[0]) if recent else set()
    fresh = [uw for uw in due if uw.id not in recent_ids]
    if len(fresh) >= count:
        return fresh[:count]
    chosen_ids = {uw.id for uw in fresh}
    filler = [uw for uw in due if uw.id not in chosen_ids]
    return (fresh + filler)[:count]


def _review_reminder_content(words: list[UserWord], translation_language: str, language: str, slot: str) -> NotificationContent:
    lines = [t("notification.review_list.header", language), ""]
    for i, uw in enumerate(words):
        translation = translation_for(uw, translation_language) or ""
        lang = LANGUAGE_BY_CODE.get(uw.word.language_code)
        flag = lang.flag if lang else ""
        emoji = _NUMBER_EMOJI[i] if i < len(_NUMBER_EMOJI) else f"{i + 1}."
        lines.append(f"{emoji} {flag} {uw.word.word} — {translation}")
    text = "\n".join(lines)
    return NotificationContent(text, notification_keyboard(slot), word_ids=[uw.id for uw in words])


async def _build_content(session, user, slot: str, now: datetime) -> NotificationContent | None:
    """None means there is nothing worth sending (spec sections 14-16,
    32: never send a meaningless notification).

    set_current_language(user.interface_language) here, not just passing
    it to t() explicitly, because start_keyboard() (keyboards/learning.py)
    and notification_keyboard() (keyboards/review_now.py) read the
    language back out of the same ContextVar every other screen in the
    bot uses - settings-improvements
    stage section 2's "every part of the UI must follow interface_language"
    applies to a notification's buttons exactly as much as its text.
    Safe to call per-iteration here even though this is a batch loop over
    many users: each poll tick runs in its own asyncio task, so nothing
    from a concurrent request-handling task can leak in, and the next
    user in this same loop simply overwrites it again before their own
    text/keyboard is built."""
    set_current_language(user.interface_language)
    language = user.interface_language

    current = await user_languages_repo.get_current_language(session, user.id)
    if current is None:
        return None

    due = await _select_review_words(session, user, slot, current, now)
    logger.debug("SELECTED_WORDS_COUNT=%d telegram_id=%s slot=%s", len(due), user.telegram_id, slot)

    # Repetition-system stage sections 10-11: whenever there is anything
    # due, always use the compact per-word reminder - never the old
    # "N words are due" phrasing, and never the full 📚 Учить слова flow -
    # so the automatic ping stays a quick reminder in every slot, not a
    # teaching session in disguise. A slot with nothing due keeps its own
    # older behavior below (new-words announcement / silence / "done").
    if due:
        return _review_reminder_content(due, current.translation_language, language, slot)

    if slot == SLOT_MORNING:
        new_words = (await learning_service.get_new_words_for_today(session, user=user, user_language=current, now=now)).words
        if not new_words:
            logger.info("REVIEW_NOTIFICATION_SKIPPED telegram_id=%s slot=%s REASON=NO_ACTIVE_WORDS", user.telegram_id, slot)
            return None
        text = t("notification.morning.new_only", language, new_count=len(new_words))
        return NotificationContent(text, start_keyboard())

    if slot == SLOT_AFTERNOON:
        logger.info("REVIEW_NOTIFICATION_SKIPPED telegram_id=%s slot=%s REASON=NO_ACTIVE_WORDS", user.telegram_id, slot)
        return None

    if slot == SLOT_EVENING:
        if user.last_learning_date == local_today(now, user.timezone):
            return NotificationContent(t("notification.evening.done", language))
        logger.info("REVIEW_NOTIFICATION_SKIPPED telegram_id=%s slot=%s REASON=NO_ACTIVE_WORDS", user.telegram_id, slot)
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
        try:
            hour, minute = local_hour_minute(now, user.timezone)
            due_now = _is_due_now(user, slot, now)
        except Exception:
            # A single user with an unrecognized/corrupted timezone value
            # (stale data from before real IANA validation existed, or a
            # bad manual edit) must never take the whole poll tick down -
            # ZoneInfo() raises for an unknown name, and this loop has no
            # other guard between here and scheduler/notifications.py's
            # broad except, which would otherwise skip sending to EVERY
            # user for the rest of this tick, not just this one.
            logger.exception(
                "Could not evaluate %s notification due-check for telegram_id=%s (timezone=%r) - skipping this user",
                slot, user.telegram_id, user.timezone,
            )
            continue
        logger.debug(
            "CHECKING_REVIEWS telegram_id=%s slot=%s USER_TIMEZONE=%s CURRENT_LOCAL_TIME=%02d:%02d %s_NOTIFICATION_DUE=%s",
            user.telegram_id, slot, user.timezone, hour, minute, slot.upper(), due_now,
        )
        if not due_now:
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

        logger.info("SENDING_REVIEW_NOTIFICATION telegram_id=%s slot=%s", user.telegram_id, slot)
        try:
            await bot.send_message(chat_id=user.telegram_id, text=content.text, reply_markup=content.reply_markup)
        except Exception:
            # Covers a blocked/deleted Telegram account (Forbidden, "bot
            # was blocked", "chat not found") the exact same way as any
            # other send failure - one user's account state must never
            # stop the loop for anyone else (sections 18-19).
            logger.exception("Failed to send %s notification to telegram_id=%s", slot, user.telegram_id)
            continue

        async with session_scope() as session:
            await notifications_repo.log_sent(
                session, user_id=user.id, notification_type=slot, scheduled_date=scheduled_date, word_ids=content.word_ids,
            )
        logger.info("REVIEW_NOTIFICATION_SENT telegram_id=%s slot=%s", user.telegram_id, slot)
        sent_count += 1

    return sent_count


async def send_due_notifications(bot, *, now: datetime | None = None) -> int:
    """Checks all three slots in one pass - what scheduler/notifications.py's
    poller calls on each tick."""
    now = now if now is not None else utc_now()
    logger.debug("NOTIFICATION_CHECK_STARTED")
    total = 0
    for slot in SLOTS:
        total += await send_for_slot(bot, slot, now=now)
    logger.debug("NOTIFICATION_CHECK_FINISHED sent=%d", total)
    return total


async def send_review_notification_now(bot, *, telegram_id: int, slot: str = SLOT_MORNING) -> bool:
    """Manual test trigger (notification-scheduler-fix stage section 25):
    builds and sends `slot`'s compact review reminder for `telegram_id`
    right now, using the exact same word-selection/content logic a real
    scheduled send uses - but bypasses morning_time/afternoon_time/
    evening_time, the per-slot enabled toggles, AND the NotificationLog
    once-a-day dedup entirely (it neither checks nor writes it), so
    calling this can never change whether the REAL scheduled send for
    `slot` still fires later the same day, and can be re-run freely while
    testing. Returns True only if a message was actually sent."""
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, telegram_id)
        if user is None:
            logger.warning("send_review_notification_now: no user with telegram_id=%s", telegram_id)
            return False
        content = await _build_content(session, user, slot, utc_now())

    if content is None:
        logger.info("send_review_notification_now: nothing to send telegram_id=%s slot=%s", telegram_id, slot)
        return False

    await bot.send_message(chat_id=telegram_id, text=content.text, reply_markup=content.reply_markup)
    logger.info("send_review_notification_now: sent telegram_id=%s slot=%s", telegram_id, slot)
    return True
