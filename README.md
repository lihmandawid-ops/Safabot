# Safabot

Telegram-бот для изучения иностранных языков с упором на запоминание слов
через интервальное повторение. Поддерживает 8 языков (English, Russian,
German, Hebrew, Spanish, French, Italian, Ukrainian); один пользователь
может изучать несколько языков одновременно.

## Статус проекта

Проект разрабатывается поэтапно (см. [«Этапы разработки»](#этапы-разработки)
ниже). На сегодня реализовано:

- **Этап 1** — структура проекта.
- **Этап 2** — подключение к Telegram (`bot.py`, `config.py`, логирование,
  обработка ошибок).
- **Этап 3** — регистрация и onboarding (`/start`): язык интерфейса → язык
  обучения → язык перевода → уровень → количество новых слов → часовой
  пояс → главное меню. Прогресс онбординга переживает перезапуск бота
  (`PicklePersistence`), а не хранится только в памяти процесса.
- **Этап 4** — база данных полностью реализована: SQLAlchemy 2.x (async) +
  SQLite, модели `Language`, `User`, `UserLanguage` со внешними ключами,
  репозитории (`users`, `languages`, `user_languages`, `subscriptions`),
  миграции Alembic (batch mode для SQLite, с переносом данных при
  переименовании колонок).
- Раздел **⚙️ Настройки** — полноценное inline-меню: смена активного
  изучаемого языка, языка интерфейса, количества новых слов (для текущего
  языка), времени и вкл/выкл уведомлений, уровня; подписка — просмотр.
- 7-дневный **PRO trial** выдаётся автоматически при регистрации
  (`services/subscription_service.py`: `is_trial_active`,
  `is_subscription_active`, `has_pro_access`).
- Минимальная система локализации (`locales/ru.json` + `utils/i18n.t()`) —
  все тексты вынесены из handlers; добавление нового языка интерфейса не
  требует правки кода, только нового файла `locales/<code>.json`.

Остальные разделы главного меню (Учить слова, Повторить, Словарь, Мои
слова, разбор фото/текста/голоса, Прогресс, PRO) отвечают понятным
сообщением «раздел в разработке» — они запланированы на следующие этапы
(см. `handlers/menu.py` и `services/*.py`, где у каждого нереализованного
раздела есть чёткий TODO с номером этапа).

## Требования

- Python 3.12+
- Telegram-бот, зарегистрированный через [@BotFather](https://t.me/BotFather)

## Установка

### 1. Клонируйте репозиторий

```bash
git clone <URL_РЕПОЗИТОРИЯ>
cd Safabot
```

### 2. Создайте виртуальное окружение

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows
```

### 3. Установите зависимости

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Настройте `.env`

```bash
cp .env.example .env
```

Откройте `.env` и заполните:

- `BOT_TOKEN` — токен, полученный от @BotFather (см. ниже).
- Остальные переменные можно оставить по умолчанию для локальной разработки
  (используется SQLite-файл `safabot.db`).

**Никогда не коммитьте `.env` и не вставляйте токен в код** — `.env`
уже добавлен в `.gitignore`.

### 5. Создайте бота через BotFather

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram.
2. Отправьте `/newbot` и следуйте инструкциям (имя и username бота).
3. Скопируйте выданный токен в `BOT_TOKEN` в файле `.env`.

### 6. Примените миграции базы данных

```bash
alembic upgrade head
```

Это создаст `safabot.db` со всеми нужными таблицами. (При обычном запуске
`python bot.py` таблицы также создаются автоматически, если их ещё нет —
но `alembic upgrade head` даёт полный контроль над схемой и обязателен на
проде, см. [«База данных и миграции»](#база-данных-и-миграции).)

## Запуск

```bash
python bot.py
```

Бот запустится в режиме long polling. Найдите его в Telegram по username,
который вы указали в BotFather, и отправьте `/start`.

## Запуск тестов

```bash
pytest
```

Тесты используют собственный временный SQLite-файл на каждый тест и не
трогают ваш рабочий `safabot.db`. Часть тестов (`test_words.py`,
`test_repetition.py`) помечены `skip` — они описывают, что должно быть
проверено на следующих этапах (Слова, Интервальное повторение), и станут
активными, когда соответствующий функционал будет реализован.

## Структура проекта

```
safabot/
│
├── bot.py                  # точка входа: сборка Application, запуск polling
├── config.py                # .env → типизированные настройки, лимиты PRO/FREE
├── requirements.txt
├── alembic.ini               # конфигурация Alembic (URL берётся из config.py)
├── .env.example
├── .gitignore
│
├── handlers/                 # Telegram-хендлеры (тонкий слой, без бизнес-логики)
│   ├── start.py               # /start: онбординг (реализовано)
│   ├── menu.py                 # роутинг главного меню (реализовано)
│   ├── settings.py             # ⚙️ Настройки: просмотр профиля (реализовано)
│   ├── learning.py, review.py, dictionary.py, words.py,
│   │   grammar.py, progress.py, media.py, payments.py   # заглушки со ссылкой на этап
│
├── services/                 # бизнес-логика, независимая от Telegram
│   ├── subscription_service.py   # trial / PRO-статус (реализовано)
│   ├── learning_service.py, repetition_service.py,
│   │   dictionary_service.py, translation_service.py,
│   │   ai_service.py, ocr_service.py, speech_service.py  # интерфейсы для следующих этапов
│
├── database/
│   ├── database.py             # async engine/session (SQLite сейчас, Postgres — смена DATABASE_URL)
│   ├── models.py                # Language, User, UserLanguage (SQLAlchemy 2.x, FK на languages.code)
│   ├── seed.py                  # идемпотентный seed 8 языков
│   └── repositories/
│       ├── users.py, languages.py, user_languages.py, subscriptions.py   # реализовано
│       └── words.py, learning.py         # заглушки (Word/UserWord — Этап 5/7)
│
├── locales/
│   └── ru.json                 # все тексты handlers; utils/i18n.py:t(key, lang)
│
├── keyboards/                 # клавиатуры Telegram
│   ├── main_menu.py, language.py, settings.py   # реализовано
│   └── learning.py, words.py, payments.py # заглушки
│
├── scheduler/
│   └── notifications.py       # интеграционная точка для JobQueue (Этап 10)
│
├── utils/
│   ├── logging.py, languages.py, pagination.py, text.py
│
├── migrations/                # Alembic
│   └── versions/
│
└── tests/
    ├── conftest.py
    ├── test_users.py, test_subscriptions.py    # реализовано
    └── test_words.py, test_repetition.py        # skip-плейсхолдеры для будущих этапов
```

## База данных и миграции

- В разработке используется **SQLite** через async-драйвер `aiosqlite`
  (`DATABASE_URL=sqlite+aiosqlite:///./safabot.db`).
- Переход на **PostgreSQL** не требует переписывания кода — достаточно
  установить `asyncpg` и указать
  `DATABASE_URL=postgresql+asyncpg://user:password@host:5432/safabot`.
  Модели написаны без SQLite-специфичных типов.
- Схема версионируется через **Alembic** (`migrations/`). Основные команды:

  ```bash
  alembic upgrade head              # применить все миграции
  alembic revision --autogenerate -m "описание изменений"   # создать новую миграцию
  alembic downgrade -1              # откатить последнюю миграцию
  ```

- `database/database.py:init_models()` — это удобный способ создать таблицы
  «начисто» при локальной разработке; для реального продакшена и любых
  изменений схемы используйте только Alembic.

## Этапы разработки

Проект разрабатывается по шагам (см. историю коммитов); текущий и
следующие этапы:

1. Структура проекта ✅
2. Подключение Telegram ✅
3. Регистрация и onboarding ✅
4. База данных ✅
5. Слова (Word/UserWord)
6. Обучение (новые слова, 3 сообщения в день)
7. Алгоритм интервального повторения
8. Мои слова (нумерация, фильтры, пагинация)
9. Словарь
10. Уведомления (JobQueue)
11. Прогресс
12. Trial ✅ (реализован досрочно вместе с онбордингом)
13. Платежи (Telegram Stars)
14. AI-разбор
15. OCR (разбор фото)
16. Голос (Speech-to-Text)

Каждый следующий этап не начинается, пока предыдущий не работает и не
покрыт тестами (там, где это применимо).

## Запуск на VPS

### Через systemd (рекомендуется)

1. Склонируйте репозиторий на сервер и выполните шаги установки выше
   (venv, зависимости, `.env`, `alembic upgrade head`).

2. Создайте unit-файл `/etc/systemd/system/safabot.service`:

   ```ini
   [Unit]
   Description=Safabot Telegram Bot
   After=network.target

   [Service]
   Type=simple
   User=safabot
   WorkingDirectory=/opt/safabot
   ExecStart=/opt/safabot/.venv/bin/python /opt/safabot/bot.py
   Restart=on-failure
   RestartSec=5
   EnvironmentFile=/opt/safabot/.env

   [Install]
   WantedBy=multi-user.target
   ```

   Замените пути на реальные (например, `/opt/safabot`) и создайте
   отдельного системного пользователя `safabot` для запуска бота.

3. Примените и запустите:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable safabot
   sudo systemctl start safabot
   ```

4. Проверка статуса и логов:

   ```bash
   sudo systemctl status safabot
   journalctl -u safabot -f
   ```

Бот будет автоматически перезапускаться при сбоях и после перезагрузки
сервера.
