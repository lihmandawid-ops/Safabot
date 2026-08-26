"""📊 Мой прогресс (statistics/progress stage): a read-only summary built
entirely from services/progress_service.py's snapshot - overall stats,
today/7-day/30-day period stats, and a level-progress bar that reuses
services/level_progress_service.get_level_progress (the same thresholds
that gate a REAL level-up, never a separate "looks close" heuristic).

Reached from the main menu's persistent "📊 Мой прогресс" button
(handlers/menu.py) - a plain text reply, same as every other main-menu
screen that isn't an interactive flow; no new keyboard needed since the
persistent main menu is already on screen.

Never lets a broken stats read take down the button: any exception here
is caught and degrades to a short "couldn't load your stats" message
(spec: "статистика - дополнительный слой, не должна ломать базовый
функционал").
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from database.database import session_scope
from database.repositories import user_languages as user_languages_repo
from database.repositories import users as users_repo
from services.progress_service import ProgressSnapshot, build_snapshot
from utils.i18n import get_current_language, set_current_language, t
from utils.logging import get_logger

logger = get_logger(__name__)

_BAR_SEGMENTS = 10


async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as session:
        user = await users_repo.get_by_telegram_id(session, update.effective_user.id)
        if user is None:
            return
        set_current_language(user.interface_language)
        current = await user_languages_repo.get_current_language(session, user.id)
        if current is None:
            await update.message.reply_text(t("card.no_language", get_current_language()))
            return

        try:
            snapshot = await build_snapshot(
                session, user_id=user.id, user_language=current, timezone=user.timezone
            )
        except Exception:
            logger.exception("Progress snapshot failed user_id=%s", user.id)
            await update.message.reply_text(t("progress.error", get_current_language()))
            return

    await update.message.reply_text(_render_text(snapshot, language=get_current_language()))


def _bar(ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * _BAR_SEGMENTS)
    return "█" * filled + "░" * (_BAR_SEGMENTS - filled)


def _percent(value: float) -> str:
    return f"{value:.0%}"


def _word_list(words: list[str]) -> str:
    return ", ".join(words)


def _render_text(snapshot: ProgressSnapshot, *, language: str) -> str:
    lines = [t("progress.title", language), ""]

    if snapshot.total_words == 0:
        lines.append(t("progress.empty", language))
        return "\n".join(lines)

    lines.append(t("progress.section.overall", language))
    lines.append(t("progress.overall.total_words", language, count=snapshot.total_words))
    lines.append(
        t(
            "progress.overall.buckets", language,
            well=snapshot.well_consolidated, progress=snapshot.in_progress, difficult=snapshot.difficult,
        )
    )
    lines.append(t("progress.overall.mastered", language, count=snapshot.mastered_count))
    lines.append(t("progress.overall.reviews", language, count=snapshot.total_reviews))
    lines.append(t("progress.overall.accuracy", language, percent=_percent(snapshot.overall_accuracy)))
    lines.append("")

    lines.append(t("progress.section.periods", language))
    for period_key, stats in (
        ("progress.period.today", snapshot.today),
        ("progress.period.week", snapshot.last_7_days),
        ("progress.period.month", snapshot.last_30_days),
    ):
        lines.append(
            t(
                "progress.period.line", language,
                label=t(period_key, language), new_words=stats.new_words,
                reviews=stats.reviews, accuracy=_percent(stats.accuracy),
            )
        )
    lines.append("")

    lp = snapshot.level_progress
    lines.append(t("progress.section.level", language))
    lines.append(t("progress.level.current", language, level=t(f"level.{lp.current_level}", language)))
    if lp.next_level is None:
        lines.append(t("progress.level.max", language))
    else:
        lines.append(f"{_bar(lp.progress_ratio)} {_percent(lp.progress_ratio)}")
        lines.append(
            t(
                "progress.level.next", language,
                level=t(f"level.{lp.next_level}", language),
                mastered=lp.mastered_count, required=lp.mastered_required,
                accuracy=_percent(lp.accuracy), required_accuracy=_percent(lp.accuracy_required),
            )
        )
    lines.append("")

    if snapshot.weak_words or snapshot.strong_words:
        lines.append(t("progress.section.words", language))
        if snapshot.weak_words:
            lines.append(t("progress.words.weak", language, words=_word_list(snapshot.weak_words)))
        if snapshot.strong_words:
            lines.append(t("progress.words.strong", language, words=_word_list(snapshot.strong_words)))

    return "\n".join(lines).strip()
