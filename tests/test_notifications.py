"""Scheduler/notification tests (spec section 32): correct slot timing,
timezone handling, disabled users skipped, no duplicate sends, no
notification when there is nothing to say, and the evening
"done for today" message. No real Telegram calls - `bot` is an
AsyncMock throughout.

Unlike the rest of the suite, these tests can't use the shared `session`
fixture: services/notification_service.py deliberately manages its own
short-lived session_scope() blocks per user (so a DB transaction is never
held open across the network call to Telegram - see its docstring), which
means it always goes through database.database's module-level engine
rather than a session handed to it. The `notif_db` fixture below points
that global engine at the same temp file the test itself uses, then both
sides talk to the same database.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, time
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import WordStatus


@pytest_asyncio.fixture
async def notif_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")

    import config
    config.get_settings.cache_clear()

    import database.database as db_module
    db_module._engine = None
    db_module._session_factory = None

    from database.database import init_models, session_scope
    from database.seed import seed_languages

    await init_models()
    async with session_scope() as s:
        await seed_languages(s)

    yield

    await db_module.dispose_engine()
    config.get_settings.cache_clear()
    os.remove(path)


# 09:00 UTC, which is also 09:00 for a "UTC" timezone user - keeps the
# arithmetic simple for tests that don't specifically exercise timezones.
MORNING_UTC = datetime(2026, 6, 15, 9, 0, 0)


async def _create_user(
    db_session, *, telegram_id=5000, timezone="UTC", notifications_enabled=True,
    morning=time(9, 0), afternoon=time(14, 0), evening=time(20, 0), interface_language="ru",
):
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo

    user = await users_repo.create_user(
        db_session, telegram_id=telegram_id, username=None, first_name="T",
        interface_language=interface_language, timezone=timezone, level="beginner", daily_new_words=4,
        morning_time=morning, afternoon_time=afternoon, evening_time=evening,
    )
    if not notifications_enabled:
        await users_repo.update_user(db_session, user, notifications_enabled=False)
    ul = await user_languages_repo.add_language(
        db_session, user_id=user.id, language_code="en", translation_language="ru", level="beginner", daily_new_words=4
    )
    return user, ul


async def _add_due_word(db_session, user_id, word="go"):
    from database.repositories import user_words as user_words_repo
    from services import word_service

    w, _ = await word_service.get_or_create_word(db_session, language_code="en", word=word)
    uw = await user_words_repo.add_word(db_session, user_id=user_id, word_id=w.id, language_code="en")
    uw.status = WordStatus.REVIEW
    # Fixed, far-past date rather than "an hour before MORNING_UTC" - this
    # word must already be due no matter which slot/timezone a given test
    # checks against.
    uw.next_review_at = datetime(2020, 1, 1)
    return uw


async def test_morning_notification_sent_when_due_words_exist(notif_db):
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    sent = await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    assert sent == 1
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == user.telegram_id
    assert "Быстрое повторение" in kwargs["text"]
    assert "go" in kwargs["text"]
    assert "1️⃣" in kwargs["text"]


async def test_morning_notification_shows_cached_pronunciation_per_word(notif_db):
    """Global pronunciation rule section 48: each word line gets its own
    cached pronunciation - never a live AI call from the scheduler's hot
    path, so this must come from an already-cached Word.pronunciation."""
    from database.database import session_scope
    from database.repositories import words as words_repo
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        await _add_due_word(s, user.id)
        word = await words_repo.find_exact(s, language_code="en", normalized_word="go")
        await words_repo.set_pronunciation(s, word, pronunciation="goh", phonetic=None)

    bot = AsyncMock()
    await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    text = bot.send_message.await_args.kwargs["text"]
    assert "go (goh)" in text


async def test_morning_notification_word_line_plain_when_pronunciation_not_cached(notif_db):
    """No cached pronunciation must never crash or block the send - the
    line simply stays plain, exactly like before this feature."""
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    text = bot.send_message.await_args.kwargs["text"]
    assert "go —" in text
    assert "go (" not in text


async def test_no_notification_when_nothing_is_due(notif_db):
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        await _create_user(s)

    bot = AsyncMock()
    sent = await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    assert sent == 0
    bot.send_message.assert_not_awaited()


async def test_disabled_notifications_are_never_sent(notif_db):
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s, notifications_enabled=False)
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    sent = await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    assert sent == 0
    bot.send_message.assert_not_awaited()


async def test_notification_not_sent_far_outside_its_scheduled_minute(notif_db):
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s, morning=time(9, 0))
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    off_time = datetime(2026, 6, 15, 9, 30, 0)  # well past the grace window
    sent = await notification_service.send_for_slot(bot, "morning", now=off_time)

    assert sent == 0


async def test_notification_still_sent_within_grace_period_after_a_missed_exact_minute(notif_db):
    """Notification-scheduler-fix stage section 9: a short restart or a
    delayed poll tick around the scheduled minute must not silently skip
    the whole day - real incident: a startup crash-loop ate several
    users' scheduled sends because the old exact-minute match had zero
    tolerance."""
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s, morning=time(9, 0))
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    off_time = datetime(2026, 6, 15, 9, 5, 0)  # 5 minutes late, inside NOTIFICATION_GRACE_MINUTES
    sent = await notification_service.send_for_slot(bot, "morning", now=off_time)

    assert sent == 1


async def test_repeated_poll_does_not_send_twice(notif_db):
    """Spec section 29: re-running the scheduler for the same slot/day
    must not duplicate a send, even across separate calls (simulating a
    process restart mid-day)."""
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    first = await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)
    second = await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    assert first == 1
    assert second == 0
    assert bot.send_message.await_count == 1


async def test_notification_log_recorded_only_after_send_attempt(notif_db):
    from database.database import session_scope
    from database.repositories import notifications as notifications_repo
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    async with session_scope() as s:
        was_sent = await notifications_repo.was_sent(
            s, user_id=user.id, notification_type="morning", scheduled_date=MORNING_UTC.date()
        )
    assert was_sent is True


async def test_timezone_is_respected_not_server_time(notif_db):
    """A user in a timezone ahead of UTC should be notified when it's
    their local 09:00, not the server's."""
    from database.database import session_scope
    from services import notification_service

    # Asia/Tokyo is UTC+9, so local 09:00 there is 00:00 UTC.
    async with session_scope() as s:
        user, _ = await _create_user(s, telegram_id=5100, timezone="Asia/Tokyo", morning=time(9, 0))
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    midnight_utc = datetime(2026, 6, 15, 0, 0, 0)
    sent_at_midnight_utc = await notification_service.send_for_slot(bot, "morning", now=midnight_utc)
    assert sent_at_midnight_utc == 1

    bot2 = AsyncMock()
    nine_am_utc = datetime(2026, 6, 16, 9, 0, 0)
    sent_at_9am_utc = await notification_service.send_for_slot(bot2, "morning", now=nine_am_utc)
    assert sent_at_9am_utc == 0  # that's 18:00 in Tokyo, not their morning slot


async def test_timezone_respected_across_several_real_zones(notif_db):
    """Notification-scheduler-fix stage section 26: local 09:00 must mean
    09:00 in the user's OWN zone for a representative spread of real IANA
    names (not a fixed UTC offset, which would be wrong for at least one
    of these on the test date since they don't all share the same DST
    rules) - computed via zoneinfo itself rather than hardcoded offsets,
    so this doesn't silently rot if a rule changes."""
    from datetime import date, time as dtime
    from zoneinfo import ZoneInfo

    from database.database import session_scope
    from services import notification_service

    for i, tz_name in enumerate(("Asia/Jerusalem", "Europe/Moscow", "Europe/Berlin", "America/New_York")):
        telegram_id = 5300 + i
        async with session_scope() as s:
            user, _ = await _create_user(s, telegram_id=telegram_id, timezone=tz_name, morning=time(9, 0))
            await _add_due_word(s, user.id, word=f"tzword{i}")

        local_nine_am = datetime.combine(date(2026, 6, 15), dtime(9, 0), tzinfo=ZoneInfo(tz_name))
        now_utc = local_nine_am.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

        bot = AsyncMock()
        sent = await notification_service.send_for_slot(bot, "morning", now=now_utc)
        assert sent == 1, f"expected a send for {tz_name} at its local 09:00"


async def test_afternoon_notification_reviews_wording(notif_db):
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s, afternoon=time(14, 0))
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    afternoon_utc = datetime(2026, 6, 15, 14, 0, 0)
    sent = await notification_service.send_for_slot(bot, "afternoon", now=afternoon_utc)

    assert sent == 1
    text = bot.send_message.await_args.kwargs["text"]
    assert "Быстрое повторение" in text


async def test_evening_shows_completion_message_when_daily_session_done(notif_db):
    from database.database import session_scope
    from database.repositories import user_languages as user_languages_repo
    from database.repositories import users as users_repo
    from database.repositories import user_words as user_words_repo
    from services import learning_service, notification_service, word_service
    from services.repetition_service import ReviewGrade

    async with session_scope() as s:
        user, ul = await _create_user(s, evening=time(20, 0))
        w, _ = await word_service.get_or_create_word(s, language_code="en", word="go")
        await user_words_repo.add_word(s, user_id=user.id, word_id=w.id, language_code="en")

    morning = datetime(2026, 6, 15, 8, 0, 0)
    async with session_scope() as s:
        user = await users_repo.get_by_telegram_id(s, 5000)
        ul = (await user_languages_repo.get_user_languages(s, user.id))[0]
        learning_session = await learning_service.build_learning_session(s, user=user, user_language=ul, now=morning)
        await learning_service.record_review_answer(
            s, learning_session, learning_session.items[0].user_word_id, grade=ReviewGrade.GOOD, now=morning
        )
        await learning_service.finish_session_if_complete(s, user, learning_session, now=morning)

    bot = AsyncMock()
    evening_utc = datetime(2026, 6, 15, 20, 0, 0)
    sent = await notification_service.send_for_slot(bot, "evening", now=evening_utc)

    assert sent == 1
    text = bot.send_message.await_args.kwargs["text"]
    assert "выполнено" in text


async def test_evening_silent_when_nothing_due_and_nothing_done_today(notif_db):
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        await _create_user(s, evening=time(20, 0))

    bot = AsyncMock()
    evening_utc = datetime(2026, 6, 15, 20, 0, 0)
    sent = await notification_service.send_for_slot(bot, "evening", now=evening_utc)

    assert sent == 0
    bot.send_message.assert_not_awaited()


async def test_send_due_notifications_checks_all_three_slots(notif_db):
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s, morning=time(9, 0), afternoon=time(15, 0), evening=time(21, 0))
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    # Only the morning slot's HH:MM matches "now" - proving each slot is
    # checked independently rather than firing all three at once.
    sent = await notification_service.send_due_notifications(bot, now=MORNING_UTC)
    assert sent == 1


async def test_notification_follows_users_interface_language(notif_db):
    """settings-improvements stage section 26: a notification's text AND
    its inline keyboard button must follow the recipient's own
    interface_language, not always render in Russian - the same class
    of bug fixed everywhere else in this stage (utils/word_display.py,
    keyboards/main_menu.py, ...) had also been missed here."""
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s, interface_language="en")
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    kwargs = bot.send_message.await_args.kwargs
    assert "Quick review" in kwargs["text"]
    assert "Быстрое повторение" not in kwargs["text"]
    button_text = kwargs["reply_markup"].inline_keyboard[0][0].text
    assert button_text == "▶️ Start review"


async def test_notification_word_count_caps_the_word_list(notif_db):
    """Repetition-system stage section 9: notification_word_count (4/6/8,
    default 4) caps how many due words go into one automatic reminder,
    even when more are actually due."""
    from database.database import session_scope
    from database.repositories import users as users_repo
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        for i in range(6):
            await _add_due_word(s, user.id, word=f"word{i}")
        await users_repo.update_user(s, user, notification_word_count=6)

    bot = AsyncMock()
    await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    text = bot.send_message.await_args.kwargs["text"]
    assert text.count("️⃣") == 6  # 6 numbered-emoji lines, not all 6 due words unbounded


async def test_slot_can_be_individually_disabled(notif_db):
    """Repetition-system stage section 13: morning/afternoon/evening can
    each be toggled independently of the master notifications_enabled
    switch."""
    from database.database import session_scope
    from database.repositories import users as users_repo
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        await _add_due_word(s, user.id)
        await users_repo.update_user(s, user, morning_enabled=False)

    bot = AsyncMock()
    sent = await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    assert sent == 0
    bot.send_message.assert_not_awaited()


async def test_paused_and_mastered_words_never_appear_in_reminder(notif_db):
    from database.database import session_scope
    from database.models import WordStatus
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s)
        due = await _add_due_word(s, user.id, word="reviewme")
        paused = await _add_due_word(s, user.id, word="pausedword")
        paused.status = WordStatus.PAUSED
        mastered = await _add_due_word(s, user.id, word="masteredword")
        mastered.status = WordStatus.MASTERED

    bot = AsyncMock()
    await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    text = bot.send_message.await_args.kwargs["text"]
    assert "reviewme" in text
    assert "pausedword" not in text
    assert "masteredword" not in text


async def test_tapping_start_review_on_notification_reviews_the_exact_words_shown(notif_db, monkeypatch):
    """Repetition-system stage sections 15-17: the "▶️ Начать повторение"
    button on a notification must launch a review of exactly the words
    the notification listed (via NotificationLog.word_ids), not a fresh
    re-selection that could land on a different set."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock as _AsyncMock

    from database.database import session_scope
    from services import notification_service

    from database.repositories import words as words_repo

    async with session_scope() as s:
        user, _ = await _create_user(s, telegram_id=5200)
        uw = await _add_due_word(s, user.id, word="notifyme")
        await words_repo.add_translation(s, word_id=uw.word_id, language_code="ru", translation="уведомление")

    bot = AsyncMock()
    await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)
    reply_markup = bot.send_message.await_args.kwargs["reply_markup"]
    callback_data = reply_markup.inline_keyboard[0][0].callback_data
    assert callback_data == "revnow:notif:morning:flashcard"

    import handlers.review_now as review_now_handler

    # The notification above was logged against MORNING_UTC's calendar
    # day, not whatever day this test happens to run on - simulates the
    # user tapping the button minutes later, on the same day it was sent.
    monkeypatch.setattr(review_now_handler, "utc_now", lambda: MORNING_UTC)

    q = _AsyncMock()
    q.data = callback_data
    q.message = _AsyncMock()
    q.from_user = SimpleNamespace(id=5200)
    context = SimpleNamespace(user_data={})
    await review_now_handler.handle_review_now_callback(SimpleNamespace(callback_query=q), context)

    state = context.user_data["revnow"]
    assert [item["user_word_id"] for item in state["items"]] == [uw.id]


async def test_one_users_corrupted_timezone_does_not_block_other_users(notif_db):
    """A stale/invalid timezone string on one user's row (e.g. leftover
    from before real IANA validation existed) must never take the whole
    poll tick down for everyone else - ZoneInfo() raises for an unknown
    name, and this loop has no other guard between it and
    scheduler/notifications.py's broad except."""
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        broken_user, _ = await _create_user(s, telegram_id=5100, timezone="Not/A_Real_Zone")
        await _add_due_word(s, broken_user.id, word="broken")
        good_user, _ = await _create_user(s, telegram_id=5101, timezone="UTC")
        await _add_due_word(s, good_user.id, word="good")

    bot = AsyncMock()
    sent = await notification_service.send_for_slot(bot, "morning", now=MORNING_UTC)

    assert sent == 1
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == good_user.telegram_id


async def test_send_review_notification_now_sends_regardless_of_scheduled_time(notif_db):
    """Notification-scheduler-fix stage section 25: the manual test
    trigger must work at any moment, not just the user's actual
    morning_time/afternoon_time/evening_time - that's the whole point of
    a way to test without waiting for real time."""
    from database.database import session_scope
    from services import notification_service

    async with session_scope() as s:
        user, _ = await _create_user(s, morning=time(23, 59))  # nowhere near "now"
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    sent = await notification_service.send_review_notification_now(bot, telegram_id=user.telegram_id, slot="morning")

    assert sent is True
    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs["text"]
    assert "Быстрое повторение" in text


async def test_send_review_notification_now_does_not_touch_notification_log(notif_db):
    """Must never affect whether the REAL scheduled send for that slot
    still fires later the same day - so it must not write (or even
    check) NotificationLog."""
    from database.database import session_scope
    from database.repositories import notifications as notifications_repo
    from services import notification_service
    from utils.time import local_today, utc_now

    async with session_scope() as s:
        user, _ = await _create_user(s, morning=time(9, 0))
        await _add_due_word(s, user.id)

    bot = AsyncMock()
    await notification_service.send_review_notification_now(bot, telegram_id=user.telegram_id, slot="morning")

    async with session_scope() as s:
        was_sent = await notifications_repo.was_sent(
            s, user_id=user.id, notification_type="morning", scheduled_date=local_today(utc_now(), user.timezone),
        )
    assert was_sent is False

    # The real scheduled send for today must still go through afterward.
    bot2 = AsyncMock()
    sent = await notification_service.send_for_slot(bot2, "morning", now=MORNING_UTC)
    assert sent == 1


async def test_send_review_notification_now_returns_false_for_unknown_user(notif_db):
    from services import notification_service

    bot = AsyncMock()
    sent = await notification_service.send_review_notification_now(bot, telegram_id=999999, slot="morning")
    assert sent is False
    bot.send_message.assert_not_awaited()


async def test_send_review_notification_now_returns_false_when_nothing_to_send(notif_db):
    from database.database import session_scope
    from database.repositories import users as users_repo
    from services import notification_service

    async with session_scope() as s:
        await _create_user(s, telegram_id=5400)

    bot = AsyncMock()
    sent = await notification_service.send_review_notification_now(bot, telegram_id=5400, slot="afternoon")
    assert sent is False
    bot.send_message.assert_not_awaited()
