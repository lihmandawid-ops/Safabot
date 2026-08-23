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
from keyboards.review_now import notification_keyboard
from services import learning_service, pronunciation_service, word_generation_service
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

# learning-methodology stage sections 1-3: the automatic morning
# notification always tries for EXACTLY this many new words - a fixed
# constant, deliberately independent of the user's configurable
# daily_new_words (which still governs the manual 🆕 Новые слова flow and
# the old session-based daily quota). Safabot's new default posture is
# "repetition is the daily habit, new words are a small automatic bonus".
MORNING_NEW_WORD_COUNT = 2

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
    """Not currently called by _build_content (learning-methodology stage
    sections 6-7, 13: the notification text no longer spells out due
    words' translations right before offering a quiz on those same
    words - it would hand the learner the answer immediately before
    being "tested" on it). Left defined rather than deleted in case a
    future non-quiz-adjacent surface wants this exact compact word+
    pronunciation+translation list rendering again.

    Global pronunciation rule section 48: each word line gets its own
    cached pronunciation, never a live AI backfill call here - this runs
    in the scheduler's hot path, once per due user per poll tick, and
    must never block on (or fail because of) an AI request. A word with
    nothing cached yet simply keeps its plain "word — translation" line,
    same as before; the 4-8 word count and one-message-per-slot shape are
    both unchanged."""
    lines = [t("notification.review_list.header", language), ""]
    for i, uw in enumerate(words):
        translation = translation_for(uw, translation_language) or ""
        lang = LANGUAGE_BY_CODE.get(uw.word.language_code)
        flag = lang.flag if lang else ""
        emoji = _NUMBER_EMOJI[i] if i < len(_NUMBER_EMOJI) else f"{i + 1}."
        pronunciation = pronunciation_service.format_pronunciation(uw.word)
        word_part = f"{uw.word.word} ({pronunciation})" if pronunciation else uw.word.word
        lines.append(f"{emoji} {flag} {word_part} — {translation}")
    text = "\n".join(lines)
    return NotificationContent(text, notification_keyboard(slot), word_ids=[uw.id for uw in words])


def _new_word_lines(entries, language_code: str, language: str, start_index: int = 0) -> list[str]:
    """Renders AI-generated candidate words (services.word_generation_service.
    GeneratedWord - already in hand, no DB round-trip needed) the same way
    everywhere a fresh new word is shown: word, Latin pronunciation, and
    the translation - never a live AI call from the scheduler's hot path,
    since these entries were already fully generated by the one AI call
    that produced them (learning-methodology stage section 27)."""
    lang = LANGUAGE_BY_CODE.get(language_code)
    flag = lang.flag if lang else ""
    lines: list[str] = []
    for i, entry in enumerate(entries, start=start_index):
        emoji = _NUMBER_EMOJI[i] if i < len(_NUMBER_EMOJI) else f"{i + 1}."
        pronunciation = entry.pronunciation or entry.phonetic
        translation = entry.translations[0].translation if entry.translations else ""
        lines.append("")
        lines.append(f"{emoji} {flag} {entry.word}".strip())
        if pronunciation:
            lines.append(t("card.pronunciation_line", language, pronunciation=pronunciation))
        lines.append(translation)
    return lines


async def _morning_content(session, user, current, language: str, now: datetime) -> NotificationContent:
    """🌅 Learning-methodology stage sections 1-5, 18, 27-28, 32, 34: the
    morning slot is special - unlike afternoon/evening, it ALWAYS tries to
    add MORNING_NEW_WORD_COUNT new words (auto-added, no confirm step -
    section 18) in addition to whatever is due for review, combined into
    ONE message (section 23: never one Telegram message per word). AI
    failure degrades gracefully (section 32) rather than skipping the
    whole morning notification - the greeting and review invite still go
    out."""
    added = await word_generation_service.generate_and_add_morning_words(
        session, user=user, user_language=current, amount=MORNING_NEW_WORD_COUNT,
    )
    due = await _select_review_words(session, user, SLOT_MORNING, current, now)
    logger.debug(
        "SELECTED_WORDS_COUNT=%d NEW_WORDS_ADDED=%d telegram_id=%s slot=morning", len(due), len(added), user.telegram_id,
    )

    lines = [t("notification.morning.greeting", language)]
    if added:
        lines.append("")
        lines.append(t("notification.morning.new_words_header", language, count=len(added)))
        lines.extend(_new_word_lines(added, current.language_code, language))
    else:
        lines.append("")
        lines.append(t("notification.morning.no_new_words", language))

    if due:
        lines.append("")
        lines.append(t("notification.morning.review_intro", language))

    return NotificationContent("\n".join(lines), notification_keyboard(SLOT_MORNING), word_ids=[uw.id for uw in due])


async def _build_content(session, user, slot: str, now: datetime) -> NotificationContent | None:
    """None means there is nothing worth sending at all (learning-
    methodology stage section 14: profile/language not set up yet) - every
    OTHER case now always produces something (sections 6-8: afternoon/
    evening never go silent just because nothing happens to be due right
    now).

    set_current_language(user.interface_language) here, not just passing
    it to t() explicitly, because notification_keyboard() (keyboards/
    review_now.py) reads the language back out of the same ContextVar
    every other screen in the bot uses - settings-improvements
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

    if slot == SLOT_MORNING:
        return await _morning_content(session, user, current, language, now)
    if slot not in (SLOT_AFTERNOON, SLOT_EVENING):
        raise ValueError(f"Unknown notification slot: {slot!r}")  # pragma: no cover - exhaustive guard

    due = await _select_review_words(session, user, slot, current, now)
    logger.debug("SELECTED_WORDS_COUNT=%d telegram_id=%s slot=%s", len(due), user.telegram_id, slot)

    # Learning-methodology stage sections 6-8, 13: afternoon/evening now
    # ALWAYS send this same lightweight review invite, whether or not
    # anything is actually due - two changes from the old design at once:
    #
    # 1. (section 8's root cause) the OLD code `return None`d here
    #    whenever nothing was due right at that exact minute - which is
    #    the ORDINARY case most days (repetition intervals are usually
    #    longer than "since this morning"), not a scheduler malfunction.
    #    That silently skipped the notification entirely, which is
    #    exactly what looked like "the afternoon notification never
    #    arrives". Tapping 🧠 Викторина when there's truly nothing to
    #    review is already handled gracefully by handlers/review_now.py's
    #    empty-state message, so this never risks a broken/empty quiz.
    #
    # 2. (sections 6-7, 13) even when words ARE due, the message no
    #    longer spells them out with their translations right in the
    #    text (the old _review_reminder_content did) - showing "word —
    #    translation" and then immediately offering a quiz on that exact
    #    same word would hand the learner the answer right before being
    #    "tested" on it. The words are still exactly right (word_ids
    #    below), they're just revealed one at a time inside the quiz
    #    itself instead of spoiled in the notification.
    key = "notification.afternoon.invite" if slot == SLOT_AFTERNOON else "notification.evening.invite"
    return NotificationContent(t(key, language), notification_keyboard(slot), word_ids=[uw.id for uw in due])


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

    # learning-methodology stage section 30: a clear, greppable marker
    # for "this slot's check actually ran this tick" - never includes
    # anything sensitive (no telegram_id list, no message content), just
    # which slot and how many notifiable users were considered.
    logger.info("[Scheduler] %s notification check started (candidates=%d)", slot.capitalize(), len(users))

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

        logger.info(
            "[Scheduler] Sending %s notification to user telegram_id=%s (timezone=%s)",
            slot, user.telegram_id, user.timezone,
        )
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
