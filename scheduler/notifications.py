"""Three daily notifications per user, in their own timezone (learning-
core stage, sections 13-19).

Uses python-telegram-bot's built-in JobQueue (APScheduler under the hood,
installed via the `python-telegram-bot[job-queue]` extra) so scheduling
stays inside the same async runtime as the rest of the bot - no separate
process or broker needed.

Design: poll once a minute and ask services/notification_service.py "is
anyone due right now" rather than scheduling one job per user per slot.
A user's morning/afternoon/evening time can change at any moment via
Settings; polling means there is never anything to re-schedule when that
happens - the very next tick just sees the new value on the User row.
This trades a small amount of DB-query overhead every minute for a much
simpler, always-correct design; NotificationLog (spec section 29) is what
keeps a slower or overlapping poll from ever double-sending.
"""
from __future__ import annotations

from telegram.ext import Application, ContextTypes

from services import notification_service
from utils.logging import get_logger

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 60


async def _poll_and_send(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("SCHEDULER_TICK")
    try:
        sent = await notification_service.send_due_notifications(context.bot)
        if sent:
            logger.info("Sent %d notification(s)", sent)
    except Exception:
        logger.exception("Notification poll failed")


def register_notification_jobs(application: Application) -> None:
    """Starts the once-a-minute poll. Call once from bot.py's
    build_application(); requires the `job-queue` extra (already in
    requirements.txt) to be installed."""
    if application.job_queue is None:  # pragma: no cover - defensive, requires the extra to be missing
        raise RuntimeError(
            "JobQueue is not available - install python-telegram-bot[job-queue] (see requirements.txt)"
        )
    application.job_queue.run_repeating(_poll_and_send, interval=POLL_INTERVAL_SECONDS, first=10)
    logger.info("SCHEDULER_STARTED interval=%ds", POLL_INTERVAL_SECONDS)
