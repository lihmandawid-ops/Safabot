"""Three daily notifications per user, in their own timezone (spec section 23).

Uses python-telegram-bot's built-in JobQueue (APScheduler under the hood,
installed via the `python-telegram-bot[job-queue]` extra) so scheduling
stays inside the same async runtime as the rest of the bot - no separate
process or broker needed.

TODO(stage-10): implement once services/learning_service.py can actually
produce "new words for today" / "words due for review" (Stages 6-7). Until
then this module only documents the integration point; bot.py does not
call it yet.

Planned shape once implemented:
    - One recurring job per (user, morning/afternoon/evening) that fires at
      the user's stored notification time, converted to UTC via
      user.timezone (IANA name) - re-scheduled whenever the user changes
      it in Settings.
    - Skips users with notifications_enabled = False.
    - Morning job -> learning_service.get_new_words_for_today
    - Afternoon/evening jobs -> learning_service.get_words_due_for_review
"""
from __future__ import annotations

from telegram.ext import Application


def register_notification_jobs(application: Application) -> None:
    """Schedule per-user notification jobs on the bot's JobQueue.

    TODO(stage-10): populate from the users table on startup, and
    re-schedule from handlers/settings.py whenever a user edits their
    notification times.
    """
    raise NotImplementedError("Daily notifications arrive in Stage 10 (Notifications)")
