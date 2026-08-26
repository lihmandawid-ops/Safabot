"""Tests for the admin panel (commercial layer, operator-facing):
- services/admin_service.py + database/repositories/admin.py's aggregate
  queries (user counts, active users, payments revenue, user search).
- handlers/admin.py's access control - the single most important
  property here: a non-admin must get nothing back from /admin, any
  "admin:" callback, or admin-mode free text, regardless of how they
  reach it.
"""
from __future__ import annotations

import os
import tempfile
from datetime import time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from database.models import SubscriptionStatus
from database.repositories import admin as admin_repo
from database.repositories import payments as payments_repo
from database.repositories import subscriptions as subscriptions_repo
from database.repositories import user_languages as user_languages_repo
from database.repositories import user_words as user_words_repo
from database.repositories import users as users_repo
from database.repositories.learning import apply_review_result
from services import admin_service, word_service
from services.repetition_service import ReviewGrade, calculate_next_review
from utils.time import utc_now

ADMIN_ID = 111
NON_ADMIN_ID = 222


async def _create_user(session, *, telegram_id, status=SubscriptionStatus.FREE):
    user = await users_repo.create_user(
        session, telegram_id=telegram_id, username=f"user{telegram_id}", first_name="Test",
        interface_language="en", timezone="UTC", level="a1", daily_new_words=4,
        morning_time=time(9, 0), afternoon_time=time(14, 0), evening_time=time(20, 0),
    )
    if status != SubscriptionStatus.FREE:
        await subscriptions_repo.set_subscription_status(session, user, status=status)
    ul = await user_languages_repo.add_language(
        session, user_id=user.id, language_code="en", translation_language="en",
        level="a1", daily_new_words=4,
    )
    return user, ul


# --------------------------------------------------------------------- #
# services/admin_service.py + database/repositories/admin.py
# --------------------------------------------------------------------- #

def test_is_admin_reads_from_config(monkeypatch):
    import config
    monkeypatch.setenv("ADMIN_USER_IDS", f"{ADMIN_ID},999")
    config.get_settings.cache_clear()

    assert admin_service.is_admin(ADMIN_ID) is True
    assert admin_service.is_admin(NON_ADMIN_ID) is False
    config.get_settings.cache_clear()


async def test_user_overview_counts_by_status_and_period(session):
    await _create_user(session, telegram_id=1001, status=SubscriptionStatus.FREE)
    await _create_user(session, telegram_id=1002, status=SubscriptionStatus.PRO)
    await _create_user(session, telegram_id=1003, status=SubscriptionStatus.TRIAL)
    await session.commit()

    overview = await admin_service.build_user_overview(session)
    assert overview.total == 3
    assert overview.by_status["free"] == 1
    assert overview.by_status["pro"] == 1
    assert overview.by_status["trial"] == 1
    assert overview.new_today == 3  # all just created


async def test_active_users_counts_review_or_new_word_activity(session):
    user_active, _ = await _create_user(session, telegram_id=1010)
    user_idle, _ = await _create_user(session, telegram_id=1011)

    word, _ = await word_service.get_or_create_word(session, language_code="en", word="hello")
    uw = await user_words_repo.add_word(session, user_id=user_active.id, word_id=word.id, language_code="en")
    result = calculate_next_review(uw.repetition_stage, uw.interval_days, ReviewGrade.GOOD)
    await apply_review_result(session, uw, result)
    await session.commit()

    since = utc_now() - timedelta(hours=1)
    active_count = await admin_repo.count_active_users_since(session, since=since)
    assert active_count == 1  # only user_active did anything


async def test_payments_overview_sums_revenue(session):
    user, _ = await _create_user(session, telegram_id=1020)
    await payments_repo.create(
        session, user_id=user.id, telegram_charge_id="c1", amount_stars=100, subscription_period_days=30,
    )
    await payments_repo.create(
        session, user_id=user.id, telegram_charge_id="c2", amount_stars=100, subscription_period_days=30,
    )
    await session.commit()

    overview = await admin_service.build_payments_overview(session)
    assert overview.total_count == 2
    assert overview.total_stars == 200
    assert overview.today_count == 2
    assert overview.today_stars == 200


async def test_find_user_detail_returns_stats_for_existing_user(session):
    user, ul = await _create_user(session, telegram_id=1030, status=SubscriptionStatus.PRO)
    word, _ = await word_service.get_or_create_word(session, language_code="en", word="cat")
    await user_words_repo.add_word(session, user_id=user.id, word_id=word.id, language_code="en")
    await session.commit()

    detail = await admin_service.find_user_detail(session, telegram_id=1030)
    assert detail is not None
    assert detail.subscription_status == SubscriptionStatus.PRO
    assert detail.total_words == 1
    assert detail.current_language_code == "en"


async def test_find_user_detail_returns_none_for_unknown_telegram_id(session):
    detail = await admin_service.find_user_detail(session, telegram_id=999999)
    assert detail is None


# --------------------------------------------------------------------- #
# handlers/admin.py - real session_scope()/real database (handler_db
# pattern), access control is the critical property under test.
# --------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("ADMIN_USER_IDS", str(ADMIN_ID))

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
        await _create_user(s, telegram_id=ADMIN_ID)
        await _create_user(s, telegram_id=NON_ADMIN_ID)

    yield

    await db_module.dispose_engine()
    os.remove(path)
    config.get_settings.cache_clear()


def _text_update(telegram_id: int):
    msg = AsyncMock()
    return SimpleNamespace(effective_user=SimpleNamespace(id=telegram_id), message=msg), msg


def _query(data: str, telegram_id: int):
    q = AsyncMock()
    q.data = data
    q.from_user = SimpleNamespace(id=telegram_id)
    return SimpleNamespace(callback_query=q), q


async def test_admin_command_shows_menu_for_admin(handler_db):
    from handlers import admin as admin_handler

    update, msg = _text_update(ADMIN_ID)
    await admin_handler.admin_command(update, SimpleNamespace(user_data={}))

    msg.reply_text.assert_awaited_once()
    text = msg.reply_text.call_args[0][0]
    assert "Admin Panel" in text


async def test_admin_command_silently_ignores_non_admin(handler_db):
    from handlers import admin as admin_handler

    update, msg = _text_update(NON_ADMIN_ID)
    await admin_handler.admin_command(update, SimpleNamespace(user_data={}))

    msg.reply_text.assert_not_awaited()


async def test_admin_callback_blocks_non_admin_even_with_valid_callback_data(handler_db):
    from handlers import admin as admin_handler

    update, q = _query("admin:users", NON_ADMIN_ID)
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.answer.assert_awaited_once()
    q.edit_message_text.assert_not_awaited()


async def test_admin_exit_sends_the_regular_main_menu(handler_db):
    from handlers import admin as admin_handler

    update, q = _query("admin:exit", ADMIN_ID)
    q.message = AsyncMock()
    context = SimpleNamespace(user_data={"mode": admin_handler.MODE, "admin_submode": "search"})
    await admin_handler.handle_admin_callback(update, context)

    q.message.reply_text.assert_awaited_once()
    kwargs = q.message.reply_text.call_args[1]
    assert kwargs["reply_markup"] is not None
    assert "mode" not in context.user_data
    assert "admin_submode" not in context.user_data


async def test_admin_exit_blocks_non_admin(handler_db):
    from handlers import admin as admin_handler

    update, q = _query("admin:exit", NON_ADMIN_ID)
    q.message = AsyncMock()
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.message.reply_text.assert_not_awaited()


async def test_admin_users_screen_shows_counts(handler_db):
    from handlers import admin as admin_handler

    update, q = _query("admin:users", ADMIN_ID)
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.edit_message_text.assert_awaited_once()
    text = q.edit_message_text.call_args[0][0]
    assert "Total: 2" in text


async def test_admin_search_by_id_flow(handler_db):
    from handlers import admin as admin_handler

    context = SimpleNamespace(user_data={})
    update, q = _query("admin:search", ADMIN_ID)
    await admin_handler.handle_admin_callback(update, context)
    assert context.user_data["admin_submode"] == "search"

    text_update, msg = _text_update(ADMIN_ID)
    await admin_handler.handle_text_input(text_update, context, str(NON_ADMIN_ID))

    msg.reply_text.assert_awaited_once()
    text = msg.reply_text.call_args[0][0]
    assert str(NON_ADMIN_ID) in text
    assert "admin_submode" not in context.user_data


async def test_admin_search_rejects_non_admin_text_input(handler_db):
    from handlers import admin as admin_handler

    context = SimpleNamespace(user_data={"mode": admin_handler.MODE, "admin_submode": "search"})
    text_update, msg = _text_update(NON_ADMIN_ID)
    await admin_handler.handle_text_input(text_update, context, str(ADMIN_ID))

    msg.reply_text.assert_not_awaited()
    assert "admin_submode" not in context.user_data


async def test_broadcast_confirm_sends_to_every_user(handler_db):
    from handlers import admin as admin_handler

    context = SimpleNamespace(user_data={}, bot=AsyncMock())
    update, q = _query("admin:broadcast", ADMIN_ID)
    await admin_handler.handle_admin_callback(update, context)

    text_update, msg = _text_update(ADMIN_ID)
    await admin_handler.handle_text_input(text_update, context, "Hello everyone!")
    msg.reply_text.assert_awaited_once()
    preview = msg.reply_text.call_args[0][0]
    assert "Hello everyone!" in preview
    assert "2" in preview  # recipient count

    update2, q2 = _query("admin:broadcast:confirm", ADMIN_ID)
    await admin_handler.handle_admin_callback(update2, context)

    assert context.bot.send_message.await_count == 2
    q2.edit_message_text.assert_awaited_once()
    result_text = q2.edit_message_text.call_args[0][0]
    assert "sent 2" in result_text


async def test_admin_grant_pro_sets_status_and_end_date(handler_db):
    from database.database import session_scope
    from handlers import admin as admin_handler

    update, q = _query(f"admin:grant:{NON_ADMIN_ID}:30", ADMIN_ID)
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.edit_message_text.assert_awaited_once()
    text = q.edit_message_text.call_args[0][0]
    assert "PRO granted" in text
    assert str(NON_ADMIN_ID) in text

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, NON_ADMIN_ID)
        assert user.subscription_status == SubscriptionStatus.PRO
        assert user.subscription_end is not None


async def test_admin_grant_pro_blocks_non_admin(handler_db):
    from database.database import session_scope
    from handlers import admin as admin_handler

    update, q = _query(f"admin:grant:{NON_ADMIN_ID}:30", NON_ADMIN_ID)
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.edit_message_text.assert_not_awaited()
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, NON_ADMIN_ID)
        assert user.subscription_status == SubscriptionStatus.FREE


async def test_admin_grant_pro_reports_unknown_user(handler_db):
    from handlers import admin as admin_handler

    update, q = _query("admin:grant:999999:30", ADMIN_ID)
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.edit_message_text.assert_awaited_once()
    assert "not found" in q.edit_message_text.call_args[0][0]


async def test_admin_revoke_pro_sets_status_to_free(handler_db):
    from database.database import session_scope
    from handlers import admin as admin_handler

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, NON_ADMIN_ID)
        await subscriptions_repo.set_subscription_status(session, user, status=SubscriptionStatus.PRO)

    update, q = _query(f"admin:revoke:{NON_ADMIN_ID}", ADMIN_ID)
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.edit_message_text.assert_awaited_once()
    assert "revoked" in q.edit_message_text.call_args[0][0]
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, NON_ADMIN_ID)
        assert user.subscription_status == SubscriptionStatus.FREE


async def test_admin_revoke_pro_blocks_non_admin(handler_db):
    from database.database import session_scope
    from handlers import admin as admin_handler

    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, NON_ADMIN_ID)
        await subscriptions_repo.set_subscription_status(session, user, status=SubscriptionStatus.PRO)

    update, q = _query(f"admin:revoke:{NON_ADMIN_ID}", NON_ADMIN_ID)
    await admin_handler.handle_admin_callback(update, SimpleNamespace(user_data={}))

    q.edit_message_text.assert_not_awaited()
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, NON_ADMIN_ID)
        assert user.subscription_status == SubscriptionStatus.PRO


async def test_broadcast_cancel_never_sends(handler_db):
    from handlers import admin as admin_handler

    context = SimpleNamespace(user_data={}, bot=AsyncMock())
    update, q = _query("admin:broadcast", ADMIN_ID)
    await admin_handler.handle_admin_callback(update, context)

    text_update, msg = _text_update(ADMIN_ID)
    await admin_handler.handle_text_input(text_update, context, "Never sent")

    update2, q2 = _query("admin:broadcast:cancel", ADMIN_ID)
    await admin_handler.handle_admin_callback(update2, context)

    context.bot.send_message.assert_not_awaited()
    assert "admin_broadcast_text" not in context.user_data
