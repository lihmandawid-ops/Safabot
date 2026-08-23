"""Bugfix: Telegram rejects an edit whose text+markup are byte-identical
to what's already showing on the message, with a BadRequest whose message
is "Message is not modified". This is a common, harmless situation (a
double-tap on the same button, a retry that happens to land on the exact
same content) - left unhandled, it crashes the callback handler and the
user's Telegram client is left showing the button's loading spinner with
no reply ever coming ("бот не грузится" reports). Every handler that
edits a message on a callback query goes through one of the two wrappers
below instead of calling query.edit_message_text/edit_message_reply_markup
directly, so this failure mode is closed everywhere at once rather than
per call site.

Any OTHER BadRequest (a genuinely malformed edit, a deleted message, a
message too old to edit, ...) still propagates - only the specific
"nothing actually changed" case is swallowed.
"""
from __future__ import annotations

from telegram.error import BadRequest

_NOT_MODIFIED = "message is not modified"


async def safe_edit_message_text(query, text: str, *, reply_markup=None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        if _NOT_MODIFIED not in str(exc).lower():
            raise


async def safe_edit_message_reply_markup(query, *, reply_markup=None) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=reply_markup)
    except BadRequest as exc:
        if _NOT_MODIFIED not in str(exc).lower():
            raise
