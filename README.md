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
- **Слова**: общий словарь (`Word` + переводы/примеры/формы), личный
  словарь пользователя (`UserWord`), раздел **📖 Словарь** (поиск: точное
  совпадение → нормализованное → частичное, в рамках одного языка) и
  раздел **⭐ Мои слова** (фильтры, постраничный нумерованный список,
  управление словом по номеру, массовый выбор `2,5,7` / `2 5 7`,
  пауза/возврат в повторение, удаление с подтверждением, поиск по
  личному словарю). Небольшой seed-набор из 28 слов (en/de) для разработки.
- **Ядро обучения** — интервальное повторение (`services/repetition_service.py`),
  раздел **📚 Учить слова** и **🔄 Повторить** (карточка → показать перевод
  → 4 оценки → следующее слово → экран результатов, всё в одном
  сообщении), учебные сессии переживают перезапуск бота
  (`LearningSession`/`LearningSessionItem`), дневной лимит новых слов и
  лимит повторений в день, серия дней (`current_streak`/`longest_streak`),
  и три ежедневных уведомления по часовому поясу пользователя
  (`scheduler/notifications.py` + `services/notification_service.py`,
  без дублей — `NotificationLog`). Подробности — в разделе
  [«Ядро обучения»](#ядро-обучения-интервальное-повторение--уведомления) ниже.

Разделы «Мой прогресс», разбор фото/текста/голоса и PRO отвечают понятным
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

Большинство тестов используют собственный временный SQLite-файл на
каждый тест и не трогают ваш рабочий `safabot.db`. Исключение —
`test_notifications.py`: `services/notification_service.py` намеренно
управляет своими собственными короткими транзакциями (см. его docstring —
это чтобы никогда не держать транзакцию БД открытой во время сетевого
вызова к Telegram), поэтому его тесты используют отдельную фикстуру
(`notif_db`), которая на время теста указывает глобальный движок
`database/database.py` на тот же временный файл.

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
│   ├── menu.py                 # роутинг главного меню + режимы (dictionary/my_words) (реализовано)
│   ├── settings.py             # ⚙️ Настройки (реализовано)
│   ├── dictionary.py           # 📖 Словарь: поиск + добавление в обучение (реализовано)
│   ├── words.py                 # ⭐ Мои слова: фильтры/страницы/номера/bulk (реализовано)
│   ├── learning.py              # 📚 Учить слова: сессия, карточка, 4 оценки (реализовано)
│   ├── review.py                 # 🔄 Повторить: тот же цикл, только due-слова (реализовано)
│   └── grammar.py, progress.py, media.py, payments.py   # заглушки со ссылкой на этап
│
├── services/                 # бизнес-логика, независимая от Telegram
│   ├── subscription_service.py   # trial / PRO-статус (реализовано)
│   ├── word_service.py            # поиск, get_or_create, карточка слова (реализовано)
│   ├── user_word_service.py       # add/pause/resume/delete, фильтры, поиск (реализовано)
│   ├── dictionary_service.py      # фасад над word_service (реализовано)
│   ├── repetition_service.py      # чистый алгоритм интервального повторения (реализовано)
│   ├── learning_service.py        # сессии, дневной лимит, due-очередь, серия дней (реализовано)
│   ├── notification_service.py    # что и кому слать, идемпотентно (реализовано)
│   └── translation_service.py, ai_service.py, ocr_service.py, speech_service.py  # заглушки
│
├── database/
│   ├── database.py             # async engine/session (SQLite сейчас, Postgres — смена DATABASE_URL)
│   ├── models.py                # Language, User, UserLanguage, Word, WordTranslation,
│   │                             # WordExample, WordForm, UserWord, LearningSession,
│   │                             # LearningSessionItem, NotificationLog (SQLAlchemy 2.x, FK-и)
│   ├── seed.py                  # идемпотентный seed 8 языков
│   ├── seed_words.py            # идемпотентный dev-набор из 28 слов (en/de)
│   └── repositories/
│       ├── users.py, languages.py, user_languages.py, subscriptions.py,
│       │   words.py, user_words.py, learning.py, sessions.py, notifications.py   # реализовано
│
├── locales/
│   └── ru.json                 # все тексты handlers; utils/i18n.py:t(key, lang)
│
├── keyboards/                 # клавиатуры Telegram
│   ├── main_menu.py, language.py, settings.py, dictionary.py, words.py, learning.py   # реализовано
│   └── payments.py             # заглушка
│
├── scheduler/
│   └── notifications.py       # once-a-minute JobQueue-поллер (реализовано)
│
├── utils/
│   ├── logging.py, languages.py, pagination.py, text.py, i18n.py,
│   │   levels.py, timezones.py, word_display.py, time.py
│
├── migrations/                # Alembic
│   └── versions/
│
└── tests/
    ├── conftest.py
    ├── test_users.py, test_subscriptions.py, test_languages.py,
    │   test_user_languages.py, test_settings.py, test_words.py,
    │   test_user_words.py, test_word_list_utils.py,
    │   test_repetition_service.py, test_learning_service.py,
    │   test_sessions.py, test_notifications.py    # реализовано
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
- SQLite-внешние ключи включены явно (`PRAGMA foreign_keys=ON` при каждом
  подключении) — без этого SQLite молча игнорирует нарушения FK.

## Слова: как добавить новый язык или новое слово

**Новый язык интерфейса/изучения** уже поддерживается архитектурно —
языки сами по себе не привязаны к коду. Чтобы добавить N-й язык сверх
исходных 8: добавьте запись в `database/seed_words.py`-подобный seed или
таблицу `languages` (code/name/native_name), добавьте его в
`utils/languages.SUPPORTED_LANGUAGES` (флаг + русское название для
клавиатур) и, для полноценной локализации интерфейса, создайте
`locales/<code>.json` — `utils/i18n.t()` подхватит его без правок кода.

**Новое слово в общий словарь** — через `services/word_service.py`:

```python
word, created = await word_service.get_or_create_word(
    session, language_code="en", word="achieve",
    part_of_speech="verb", is_verb=True, difficulty="intermediate",
)
await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="достигать")
await words_repo.add_example(session, word_id=word.id, example_text="She achieved her goal.", translation="Она достигла своей цели.")
await words_repo.add_form(session, word_id=word.id, form_type="past", form="achieved")
```

`(language_code, normalized_word)` уникален, так что повторный вызов с
тем же словом не создаёт дубликат — `created` будет `False`, а `word` —
существующей записью. Небольшой готовый набор для разработки (28 слов,
en/de) лежит в `database/seed_words.py` и подгружается автоматически при
каждом запуске бота (идемпотентно).

## Ядро обучения: интервальное повторение + уведомления

### Алгоритм интервального повторения

Вся логика — в `services/repetition_service.py`, единственном месте, где
оценка пользователя превращается в новый `stage`/`interval`/`status`.
Ни handlers, ни `learning_service` сами ничего не считают — только зовут
`calculate_next_review(current_stage, current_interval_days, grade, now=...)`,
получают обратно неизменяемый `RepetitionResult` и применяют его к
`UserWord` через `database/repositories/learning.py:apply_review_result()`.
Это чистая функция без обращений к базе — при желании alгоритм можно
целиком заменить на SM-2/FSRS, не трогая ни handlers, ни схему БД.

Лестница этапов (в днях), из спецификации:

| Stage | 0     | 1 | 2 | 3 | 4  | 5  | 6  | 7 (MASTERED) |
|-------|-------|---|---|---|----|----|----|--------------|
| Days  | 0     | 1 | 3 | 7 | 14 | 30 | 60 | — (без повторений) |

Четыре оценки под карточкой слова во время обучения:

- 😣 **Не помню** — `wrong_answers += 1`, этап уменьшается на 1 (но
  никогда не уходит в минус), слово снова становится «due» почти сразу.
- 😐 **С трудом** — этап не меняется, интервал увеличивается умеренно
  (от текущего интервала, не от лестницы), `difficulty_score` растёт.
- 🙂 **Помню** — `correct_answers += 1`, этап +1, обычный следующий интервал.
- 😎 **Очень легко** — `correct_answers += 1`, этап +2 (может сразу
  привести к MASTERED), интервал растёт сильнее.

`review:<user_word_id>:<grade>` — весь callback_data, без текста слова
(спецификация раздела 35). Каждый разбор такого callback проверяет, что
`user_word_id` действительно принадлежит активной `LearningSession`
текущего пользователя (раздел 36) — иначе тихо игнорируется.

### Учебная сессия

`LearningSession` + `LearningSessionItem` — это персистентное состояние
текущего занятия (📚 Учить слова / 🔄 Повторить), а не что-то, что живёт
только в `context.user_data`. Если бот перезапустится посреди занятия,
пользователь ничего не теряет: следующий тап на «📚 Учить слова» находит
незавершённую сессию по `(user_id, language_code, status="in_progress")`
и предлагает `▶️ Продолжить`.

- `LearningSessionItem.is_new_word` фиксирует, было ли слово «новым» в
  момент составления сессии — именно по этому полю считается дневной
  лимит новых слов (`get_new_words_for_today`), а не по отдельному
  счётчику, так что брошенная и пересозданная сессия не даёт обойти лимит.
- Порядок в сессии: сначала просроченные повторения (самые просроченные
  и с наибольшим числом ошибок — впереди), затем новые слова, если
  дневной лимit ещё не исчерпан (раздел 8). `🔄 Повторить` строит сессию
  с `include_new_words=False` — то же самое ядро, без новых слов.
  Число повторений в сессии ограничено `MAX_DAILY_REVIEWS`
  (`services/learning_service.get_due_reviews`).
- Серия дней (`User.current_streak`/`longest_streak`/`last_learning_date`)
  обновляется в `finish_session_if_complete()`, по **локальному**
  календарному дню пользователя (`utils/time.py`), а не по серверному
  времени — несколько сессий в один день не увеличивают серию дважды,
  пропущенный день её сбрасывает.

### Ежедневные уведомления

`scheduler/notifications.py` регистрирует один повторяющийся `JobQueue`-джоб
(раз в 60 секунд), который на каждом тике зовёт
`services/notification_service.send_due_notifications(bot)`. Вместо того
чтобы планировать отдельную задачу на каждого пользователя и время (и
пересоздавать её при каждом изменении настроек), бот просто спрашивает:
«у кого сейчас совпадает локальное HH:MM с одним из трёх слотов?» —
изменение времени в Настройках подхватывается на следующем тике само
собой, ничего не нужно перепланировать.

- **Утро** — новые слова + повторения (или только повторения, если
  дневной лимит новых слов исчерпан); если и того, и другого нет —
  сообщение не отправляется вовсе.
- **День** — только повторения; ничего не шлётся, если нечего повторять.
- **Вечер** — повторения, если они остались; если повторений нет, но
  пользователь **уже позанимался сегодня** (`last_learning_date` совпадает
  с текущим локальным днём) — поздравление; если не позанимался и
  повторять нечего — тишина (раздел 16: не спамить).

Часовой пояс каждого пользователя (`User.timezone`, IANA-имя) учитывается
через `utils/time.local_hour_minute()` — сравнение идёт по локальному
времени пользователя, не по времени сервера.

`NotificationLog` (уникальность по `user_id + notification_type +
scheduled_date`) не даёт отправить один и тот же слот дважды за один
день, даже если поллер сработал повторно или процесс перезапустился
посреди дня — перед отправкой всегда проверяется `was_sent()`, запись
`log_sent()` делается только **после** успешной отправки.

### Как изменить время и дневной лимит

- **Время обучения** — ⚙️ Настройки → ⏰ Время уведомлений → выбрать
  утро/день/вечер → выбрать время из готового списка (это исключает
  некорректный ввод по конструкции, без ручной проверки формата HH:MM).
- **Уведомления вкл/выкл** — ⚙️ Настройки → 🔔 Уведомления.
- **Дневной лимит новых слов** (2 / 4 / 8) — ⚙️ Настройки → 📚 Количество
  слов; хранится в `UserLanguage.daily_new_words`, отдельно для каждого
  изучаемого языка.
- **`MAX_DAILY_REVIEWS`** (максимум повторений за одну сессию, по
  умолчанию 30) — переменная окружения в `.env`, см. `.env.example`.

### Запуск

Планировщик не требует отдельного процесса — он стартует автоматически
вместе с ботом (`register_notification_jobs()` в `bot.py`, вызывается из
`build_application()`). Просто `python bot.py`.

## Этапы разработки

Проект разрабатывается по шагам (см. историю коммитов); текущий и
следующие этапы:

1. Структура проекта ✅
2. Подключение Telegram ✅
3. Регистрация и onboarding ✅
4. База данных ✅
5. Слова (Word/UserWord) ✅
6. Обучение (новые слова, 3 сообщения в день) ✅
7. Алгоритм интервального повторения ✅
8. Мои слова (нумерация, фильтры, пагинация) ✅ (реализовано вместе с Этапом 5)
9. Словарь ✅ (реализовано вместе с Этапом 5)
10. Уведомления (JobQueue) ✅
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
