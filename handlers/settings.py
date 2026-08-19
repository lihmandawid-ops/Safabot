"""⚙️ Настройки (spec section 9/23).

For now this shows a real, read-only snapshot of the user's profile and
notification settings pulled straight from the database - editing any of
these values (changing notification times, daily word count, etc.) is a
later-stage refinement.

TODO(stage-10+): add inline "change" buttons for notification times once
scheduler/notifications.py exists to reschedule jobs when they change.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from database.database import session_scope
from database.repositories import users as users_repo
from services import subscription_service
from utils.languages import LANGUAGE_BY_CODE

_LEVEL_LABELS = {"beginner": "Начинающий", "intermediate": "Средний", "advanced": "Продвинутый"}
_STATUS_LABELS = {"trial": "Пробный период", "free": "Бесплатный", "pro": "PRO", "expired": "Истёк"}


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user = update.effective_user

    async with session_scope() as session:
        user = await users_repo.get_user_by_telegram_id(session, telegram_user.id)
        if user is None:
            await update.message.reply_text("Профиль не найден. Отправьте /start, чтобы зарегистрироваться.")
            return

        user = await subscription_service.refresh_expired_trial(session, user)
        languages = await users_repo.get_active_languages(session, user.id)

    interface_lang = LANGUAGE_BY_CODE.get(user.interface_language)
    lines = [
        "⚙️ *Ваши настройки*",
        "",
        f"Язык интерфейса: {interface_lang.flag if interface_lang else ''} {interface_lang.name_ru if interface_lang else user.interface_language}",
        f"Уровень: {_LEVEL_LABELS.get(user.current_level, user.current_level)}",
        f"Новых слов в день: {user.daily_new_words_limit}",
        f"Часовой пояс: {user.timezone}",
        "",
        "Уведомления: "
        + ("включены ✅" if user.notifications_enabled else "выключены ❌"),
        f"  Утро: {user.morning_notification_time.strftime('%H:%M')}",
        f"  День: {user.afternoon_notification_time.strftime('%H:%M')}",
        f"  Вечер: {user.evening_notification_time.strftime('%H:%M')}",
        "",
        f"Подписка: {_STATUS_LABELS.get(user.subscription_status, user.subscription_status)}",
    ]
    if user.trial_end_date:
        lines.append(f"Пробный период до: {user.trial_end_date.isoformat()}")

    if languages:
        lines.append("")
        lines.append("Изучаемые языки:")
        for lang in languages:
            code_info = LANGUAGE_BY_CODE.get(lang.language_code)
            name = code_info.name_ru if code_info else lang.language_code
            flag = code_info.flag if code_info else ""
            lines.append(f"  {flag} {name} — {_LEVEL_LABELS.get(lang.level, lang.level)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
