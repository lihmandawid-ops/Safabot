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
    return (hour, minute) == (slot_time.hour, slot_time.minute)


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
            return None
        text = t("notification.morning.new_only", language, new_count=len(new_words))
        return NotificationContent(text, start_keyboard())

    if slot == SLOT_AFTERNOON:
        return None

    if slot == SLOT_EVENING:
        if user.last_learning_date == local_today(now, user.timezone):
            return NotificationContent(t("notification.evening.done", language))
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

        try:
            await bot.send_message(chat_id=user.telegram_id, text=content.text, reply_markup=content.reply_markup)
        except Exception:
            logger.exception("Failed to send %s notification to telegram_id=%s", slot, user.telegram_id)
            continue

        async with session_scope() as session:
            await notifications_repo.log_sent(
                session, user_id=user.id, notification_type=slot, scheduled_date=scheduled_date, word_ids=content.word_ids,
            )
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
