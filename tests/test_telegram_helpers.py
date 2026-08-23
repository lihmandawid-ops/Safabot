"""utils/telegram_helpers.py (bugfix: unhandled BadRequest crash report -
"бот слишком долго грузится... иногда вообще не грузится"): Telegram
rejects an edit whose text+markup are byte-identical to what's already on
the message with BadRequest("Message is not modified...") - a common,
harmless case (double-tap, a retry landing on the same content) that must
never crash a callback handler and leave the user's button spinner stuck
forever with no reply ever coming.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from utils.telegram_helpers import safe_edit_message_reply_markup, safe_edit_message_text


async def test_safe_edit_message_text_swallows_not_modified():
    query = AsyncMock()
    query.edit_message_text.side_effect = BadRequest("Message is not modified: specified new message content...")

    await safe_edit_message_text(query, "same text", reply_markup=None)  # must not raise

    query.edit_message_text.assert_awaited_once_with("same text", reply_markup=None)


async def test_safe_edit_message_text_reraises_other_bad_requests():
    query = AsyncMock()
    query.edit_message_text.side_effect = BadRequest("Message to edit not found")

    with pytest.raises(BadRequest, match="Message to edit not found"):
        await safe_edit_message_text(query, "text")


async def test_safe_edit_message_text_passes_through_on_success():
    query = AsyncMock()
    await safe_edit_message_text(query, "hello", reply_markup="kb")
    query.edit_message_text.assert_awaited_once_with("hello", reply_markup="kb")


async def test_safe_edit_message_reply_markup_swallows_not_modified():
    query = AsyncMock()
    query.edit_message_reply_markup.side_effect = BadRequest("Message is not modified: specified new message content...")

    await safe_edit_message_reply_markup(query, reply_markup=None)  # must not raise


async def test_safe_edit_message_reply_markup_reraises_other_bad_requests():
    query = AsyncMock()
    query.edit_message_reply_markup.side_effect = BadRequest("Chat not found")

    with pytest.raises(BadRequest, match="Chat not found"):
        await safe_edit_message_reply_markup(query, reply_markup=None)
