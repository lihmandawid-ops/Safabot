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
  совпадение → нормализованное → частичное → `DictionaryProvider` как
  запасной вариант, в рамках одного языка) и раздел **⭐ Мои слова**
  (фильтры, постраничный нумерованный список, управление словом по
  номеру, массовый выбор `2,5,7` / `2 5 7`, пауза/возврат в повторение,
  удаление с подтверждением, поиск по личному словарю, а также
  **➕ Добавить слово** — ручное добавление одного или нескольких слов
  сразу). Seed-набор для разработки — 171 слово, ≥20 на каждый из 8
  языков (`database/seed_words.py`). Подробности — в разделе
  [«Слова: словарь, ручное добавление, автогенерация»](#слова-словарь-ручное-добавление-автогенерация)
  ниже.
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
- **AI** подключён как необязательный интеллектуальный слой
  (`services/ai_service.py` + `services/ai_provider.py`, OpenAI-совместимый
  Chat Completions API, по умолчанию — DeepSeek): поиск незнакомых слов в
  📖 Словарь/➕ Добавить слово, автогенерация новых слов в 📚 Учить слова,
  `💡 Как использовать?` и раздел **📝 Разобрать текст**. Работает
  полностью на локальной базе без ключа (`AI_API_KEY` пуст) — бот не
  падает и не зависает, просто AI-функции показывают понятное сообщение.
  Подробности — в разделе
  [«AI: как это устроено и как подключить»](#ai-как-это-устроено-и-как-подключить) ниже.
- **Этап исправления функций (bugfix stage)**:
  **➕ Ещё новые слова** — после дневной порции можно запросить
  дополнительные слова (+2/+4/+8) сверх обычного дневного лимита, под
  отдельным лимитом `MAX_EXTRA_WORDS_PER_DAY`; **🤔 Я это уже знаю** —
  на карточке нового (ещё не изученного) слова можно сразу отметить его
  выученным и получить замену; **📷 Разобрать фото** и **🎤 Разобрать
  голос** теперь по-настоящему скачивают файл из Telegram, распознают его
  через отдельные `OCRService`/`SpeechToTextService` (архитектурно
  независимые от AI-провайдера — см.
  [«Распознавание фото и голоса (OCR/STT)»](#распознавание-фото-и-голоса-ocrstt)
  ниже) и прогоняют результат через тот же пайплайн, что и
  📝 Разбор текста.

Разделы «Мой прогресс» и PRO отвечают понятным сообщением «раздел в
разработке» — они запланированы на следующие этапы (см. `handlers/menu.py`,
где у каждого нереализованного раздела есть чёткий TODO с номером этапа).

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
- `AI_API_KEY` — необязательно; оставьте пустым, чтобы бот работал только
  на локальной базе слов (без AI-функций, но без ошибок). Как получить
  ключ и что означают остальные `AI_*` переменные — в разделе
  [«AI: как это устроено и как подключить»](#ai-как-это-устроено-и-как-подключить).
- Остальные переменные можно оставить по умолчанию для локальной разработки
  (используется SQLite-файл `safabot.db`).

**Никогда не коммитьте `.env` и не вставляйте токен/ключи в код** —
`.env` уже добавлен в `.gitignore`; `.env.example` содержит только пустые
значения-заглушки.

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
│   ├── menu.py                 # роутинг главного меню + режимы (реализовано)
│   ├── settings.py             # ⚙️ Настройки (реализовано)
│   ├── dictionary.py           # 📖 Словарь: поиск + добавление, add_word_batch (реализовано)
│   ├── words.py                 # ⭐ Мои слова: фильтры/страницы/номера/bulk/➕ Добавить слово (реализовано)
│   ├── learning.py              # 📚 Учить слова: сессия, карточка, 4 оценки (реализовано)
│   ├── review.py                 # 🔄 Повторить: тот же цикл, только due-слова (реализовано)
│   ├── text_analysis.py          # 📝 Разобрать текст: AI-разбор + добавление слов (реализовано)
│   ├── grammar.py                # ✏️ Грамматика: свободный вопрос → explain_grammar() (реализовано)
│   ├── media.py                  # 📷 Разобрать фото / 🎤 Разобрать голос: скачать → OCR/STT → analyze_text (реализовано)
│   └── progress.py, payments.py   # заглушки со ссылкой на этап
│
├── services/                 # бизнес-логика, независимая от Telegram
│   ├── subscription_service.py   # trial / PRO-статус (реализовано)
│   ├── word_service.py            # поиск, get_or_create, карточка слова (реализовано)
│   ├── user_word_service.py       # add/pause/resume/delete/mark_mastered, фильтры, поиск (реализовано)
│   ├── dictionary_service.py      # локальный поиск + DictionaryProvider (AI) fallback (реализовано)
│   ├── word_generation_service.py  # автогенерация: локальный пул + AI, generate_extra_words() (реализовано)
│   ├── repetition_service.py      # чистый алгоритм интервального повторения (реализовано)
│   ├── learning_service.py        # сессии, дневной лимит, серия дней, mark_known_and_replace() (реализовано)
│   ├── notification_service.py    # что и кому слать, идемпотентно (реализовано)
│   ├── ai_service.py               # AIService: lookup_word/generate_words/explain_word/
│   │                                # analyze_text/explain_grammar/extract_learning_words (реализовано)
│   ├── ai_provider.py              # AIProvider + HttpAIProvider (OpenAI-совместимый API) (реализовано)
│   ├── ai_models.py                # Pydantic-схемы AI-ответов (реализовано)
│   ├── ai_errors.py                # AIError и подклассы (реализовано)
│   ├── ai_diagnostics.py           # test_deepseek_connection() (реализовано)
│   ├── ocr_service.py, ocr_provider.py   # OCRService/OCRProvider + HttpOCRProvider (реализовано)
│   ├── stt_service.py, stt_provider.py   # SpeechToTextService/Provider + HttpSpeechToTextProvider (реализовано)
│   ├── media_errors.py             # OCRError/STTError и подклассы (реализовано)
│   └── translation_service.py      # заглушка
│
├── database/
│   ├── database.py             # async engine/session (SQLite сейчас, Postgres — смена DATABASE_URL)
│   ├── models.py                # Language, User, UserLanguage, Word, WordTranslation,
│   │                             # WordExample, WordForm, UserWord (+ source), LearningSession,
│   │                             # LearningSessionItem, NotificationLog, WordGenerationLog (SQLAlchemy 2.x, FK-и)
│   ├── seed.py                  # идемпотентный seed 8 языков
│   ├── seed_words.py            # идемпотентный dev-набор, 171 слово / 8 языков
│   └── repositories/
│       ├── users.py, languages.py, user_languages.py, subscriptions.py,
│       │   words.py, user_words.py, learning.py, sessions.py, notifications.py,
│       │   word_generation_logs.py   # реализовано
│
├── locales/
│   └── ru.json                 # все тексты handlers; utils/i18n.py:t(key, lang)
│
├── keyboards/                 # клавиатуры Telegram
│   ├── main_menu.py, language.py, settings.py, dictionary.py, words.py,
│   │   learning.py, text_analysis.py   # реализовано
│   └── payments.py             # заглушка
│
├── scheduler/
│   └── notifications.py       # once-a-minute JobQueue-поллер (реализовано)
│
├── utils/
│   ├── logging.py, languages.py, pagination.py, text.py, i18n.py,
│   │   levels.py, timezones.py, word_display.py, time.py, media.py
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
    │   test_sessions.py, test_notifications.py,
    │   test_dictionary_service.py, test_word_generation_service.py,
    │   test_manual_add_flow.py, test_ai_service.py, test_text_analysis_flow.py,
    │   test_ai_diagnostics.py, test_grammar_flow.py, test_word_display.py,
    │   test_learning_handlers.py, test_media_services.py, test_media_handlers.py
    │   # реализовано
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

## Слова: словарь, ручное добавление, автогенерация

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
существующей записью. Готовый seed-набор для разработки — **171 слово,
не менее 20 на каждый из 8 языков** — лежит в `database/seed_words.py` и
подгружается автоматически при каждом запуске бота (идемпотентно); он
специально достаточно большой, чтобы автогенерацию (см. ниже) можно было
проверить даже без настоящего AI-провайдера.

### Откуда берётся слово: `DictionaryService` и `DictionaryProvider`

Любой поиск слова (📖 Словарь и ⭐ Мои слова → ➕ Добавить слово оба идут
через один и тот же код) вызывает `services/dictionary_service.lookup_word()`:

1. Сначала ищет локально (`word_service.search_words` — точное →
   нормализованное → частичное совпадение).
2. Если локально ничего нет — обращается к настроенному
   `DictionaryProvider` (интерфейс в `services/dictionary_service.py`,
   единственная реализация сегодня — `AIDictionaryProvider`, оборачивающая
   `services/ai_service.get_ai_service()` — см. раздел
   [«AI: как это устроено и как подключить»](#ai-как-это-устроено-и-как-подключить) ниже).
3. Если провайдер что-то нашёл — результат уже провалидирован
   Pydantic-моделью `services/ai_models.GeneratedWord` (это делает сам
   `AIService`, до того как результат вообще покидает его) и сохраняется
   как обычная запись `Word` (со своими `WordTranslation`/`WordExample`/
   формами глагола), так что следующий поиск того же слова снова находит
   его локально, без повторного обращения к AI.
4. Если ни локально, ни у AI ничего нет — пользователь видит честное «не
   найдено», а не пустой список без объяснений.

Без настроенного AI (`AI_API_KEY` пуст, или `AI_ENABLED=false`) шаг 2
всегда возвращает «нет результата» — это ожидаемо и не ошибка: работает
только локальный словарь.

### ➕ Добавить слово (ручное добавление)

`⭐ Мои слова → ➕ Добавить слово` использует **тот же** обработчик, что и
📖 Словарь (`handlers/dictionary.py`) — просто с другим стартовым текстом
и другим значением `source`, никакой второй реализации добавления нет.

- **Одно слово** → показывается карточка (слово, часть речи, перевод,
  произношение, пример) с кнопками **✅ Добавить в обучение** /
  **⬅️ Назад** — слово никогда не добавляется без подтверждения.
- **Уже есть в словаре** → показывается текущий статус (🆕/📖/🔄/⏸/✅), а
  для статуса ⏸ «Отложено» — кнопка **🔄 Вернуть в обучение**; дубликат
  `UserWord` никогда не создаётся (уникальность `(user_id, word_id)` на
  уровне БД плюс проверка в `services/user_word_service.add_word_to_learning`).
- **Несколько слов сразу** — через запятую или с новой строки
  (`utils/text.split_word_batch`). Каждое слово ищется и добавляется тем
  же путём, что и одиночное, без диалога подтверждения на каждое, а в
  конце показывается сводка:

  ```
  Результат добавления слов:

  ✅ Добавлено (2):
  1. improve — улучшать
  2. travel — путешествовать

  ⚠️ Уже было (1):
  3. go (🔄 На повторении)

  ❌ Не удалось определить (1):
  4. asdkfjhskdf
  ```

### Поле `source`

Каждый `UserWord` хранит, откуда взялось слово (`database/models.WordSource`):

| Значение | Когда ставится |
|---|---|
| `dictionary` | добавлено через 📖 Словарь |
| `manual` | добавлено через ⭐ Мои слова → ➕ Добавить слово |
| `generated` | добавлено автоматически (`word_generation_service`) |
| `ocr` / `voice` / `ai` | зарезервировано для будущих этапов (разбор фото/голоса/AI) |

Отдельной «ручной базы слов» не существует — `source` лишь метка на
обычной записи в общей таблице `Word`/`UserWord`.

## Автогенерация новых слов

`📚 Учить слова` теперь никогда не оставляет пользователя без слов на
сегодня: если уже добавленных пользователем слов со статусом NEW не
хватает, чтобы заполнить дневной лимit, `services/learning_service.
get_new_words_for_today()` вызывает `services/word_generation_service.
generate_new_words()` на недостающее количество.

### Как это работает

1. **Сначала локальный пул.** `database/repositories/words.
   find_unknown_words_for_generation()` ищет слова из таблицы `Word` в
   нужном языке, которые пользователю ещё **не известны ни в каком
   статусе** (NEW/LEARNING/REVIEW/PAUSED/MASTERED/DELETED — если
   `UserWord` уже существует, слово не предлагается повторно), с
   предпочтением по уровню пользователя (`beginner` … `advanced`).
2. **AI — только на недостачу.** Если локального пула не хватило,
   запрашивается ровно недостающее количество у `AIService.
   generate_words()` (см. `services/ai_service.py`), с ограниченным
   списком уже известных пользователю слов (до 150, section 13 — не вся
   личная база) и, при неудаче, до `MAX_GENERATION_ATTEMPTS` (по
   умолчанию 3) повторных запросов на оставшуюся недостачу, если часть
   слов от AI оказалась дублями — не больше и никогда не бесконечно.
3. **Строгая валидация.** Каждое слово в ответе AI проверяется Pydantic-
   моделью `services/ai_models.GeneratedWord` внутри `AIService` — слово
   без `word` или без переводов отбрасывается целиком, а не попадает в
   базу; остальные поля (часть речи, уровень, категория) обнуляются, если
   содержат недопустимые значения, вместо того чтобы ронять всю запись.
4. **Никогда не ломает обучение.** Любая ошибка AI (не настроен, сеть
   недоступна, timeout, невалидный ответ) перехватывается — в ответ
   пользователь получает столько слов, сколько нашлось локально (в т.ч.
   ноль), без падения бота.
5. **Каждый вызов логируется** в `WordGenerationLog` (user_id,
   language_code, requested_amount, generated_amount, provider,
   created_at) — для контроля использования AI и затрат, даже если AI ни
   разу не был вызван (`provider="local"`).

### Дневной лимит

Лимит новых слов в день (`UserLanguage.daily_new_words`, значения 2/4/8)
считается по факту показа слова в реальной учебной сессии
(`LearningSessionItem.is_new_word`, в границах локального календарного
дня пользователя — `count_new_words_started_today`), а не по факту
существования `UserWord`. Поэтому:

- Сгенерированные, но ещё не изученные слова просто ждут в статусе NEW и
  не расходуют лимит повторно при следующем открытии `📚 Учить слова` в
  тот же день — они находятся локальным пулом `get_new_word_candidates`
  раньше, чем сработает генерация.
- Если лимит на сегодня уже выбран, `get_new_words_for_today()` вернёт
  пустой список и генерация не вызывается вовсе (`remaining == 0`).

Подробно про настройку и архитектуру AI — в разделе
[«AI: как это устроено и как подключить»](#ai-как-это-устроено-и-как-подключить) ниже.

## AI: как это устроено и как подключить

Safabot использует AI как необязательный интеллектуальный слой поверх
локальной базы — без него бот полностью работает (📖 Словарь и
📚 Учить слова используют только seed-данные), с ним добавляются: поиск
незнакомых слов, автогенерация, `💡 Как использовать?`, `📝 Разбор
текста` и `✏️ Грамматика`.

**Провайдер по умолчанию — цепочка из трёх, каждый шаг опционален:**
**Vercel AI Gateway** (PRIMARY, если настроен — маршрутизирует к Gemini
через инфраструктуру Vercel, что обходит региональные ограничения прямого
доступа к Gemini API) → **прямой Google Gemini** → **DeepSeek**
(`deepseek-chat`, API OpenAI-совместимый,
`AI_BASE_URL=https://api.deepseek.com`) как финальный FALLBACK для
текстовых задач. Любое звено можно не настраивать вовсе — цепочка просто
короче, поведение при единственном настроенном звене идентично тому, что
было до этой интеграции. Ниже описано, как это устроено и как проверить,
что подключение реально работает.

### Архитектура

```
handlers/*.py, DictionaryService, WordGenerationService, PhraseService
        │        (никогда не строят HTTP-запрос сами, никогда не
        │         обращаются к Gateway/Gemini/DeepSeek напрямую)
        ▼
services/ai_service.py — AIService (интерфейс)
        │  lookup_word / generate_words / explain_word /
        │  analyze_text / explain_grammar / extract_learning_words /
        │  generate_verb_conjugation / generate_native_phrase /
        │  translate_phrases / generate_popular_phrases
        │  + retry, per-user rate limit, логирование, кэш фабрики
        ▼
services/ai_provider.py — AIProvider (интерфейс)
        │  единственный метод: complete(system, user) -> raw text
        ▼
FallbackAIProvider (вложенные, по одному на каждую настроенную пару)
        │
        ├─ 1) HttpAIProvider → Vercel AI Gateway — PRIMARY, если задан
        │       AI_GATEWAY_API_KEY (тот же OpenAI-совместимый транспорт,
        │       что и у DeepSeek, только другой base_url/ключ/модель)
        │
        ├─ 2) GeminiTextProvider (services/gemini_provider.py) — прямой
        │       Gemini `generateContent` REST API, если задан
        │       GEMINI_API_KEY
        │
        └─ 3) HttpAIProvider (services/ai_provider.py) — DeepSeek,
                финальный fallback, если задан AI_API_KEY

Каждое звено пробуется по порядку, переход на следующее — при ЛЮБОЙ
AIError (timeout/сеть/rate limit/quota/недоступность/невалидный ответ).
Следующий вызов снова начинает с самого верха цепочки.
```

Для 📷 фото и 🎤 голоса — отдельные интерфейсы (`services/ocr_service.py`,
`services/stt_service.py`), которые Gemini занимает так же: если
`GEMINI_API_KEY` настроен, `GeminiOCRProvider`/`GeminiSTTProvider`
(тот же `services/gemini_provider.py`) читают изображение/аудио напрямую
в одном вызове — DeepSeek и Vercel AI Gateway туда никогда не
подставляются (не заявляют/не проверена поддержка изображений/аудио для
этого сценария), а прежний `OCR_API_KEY`/`STT_API_KEY`-путь остаётся
рабочим для тех, у кого `GEMINI_API_KEY` не задан — поведение идентично
тому, что было до этой интеграции.

- **Handlers никогда не вызывают AI напрямую** — только через
  `services.ai_service.get_ai_service()` /
  `services.ocr_service.get_ocr_service()` /
  `services.stt_service.get_stt_service()`.
- **AIService — единственная точка входа** для всего текстового
  AI-функционала; `DictionaryService`, `WordGenerationService`,
  `PhraseService` тоже вызывают только его.
- **AIProvider — заменяемый транспорт.** `HttpAIProvider` работает с любым
  OpenAI-совместимым API — сама OpenAI, Azure OpenAI, OpenRouter,
  self-hosted шлюз, DeepSeek, **Vercel AI Gateway** — через `base_url`.
  `GeminiTextProvider` реализует тот же интерфейс против Gemini напрямую.
  `FallbackAIProvider` (`services/ai_provider.py`) composes два
  `AIProvider`; `get_ai_service()` вкладывает их друг в друга под
  количество реально настроенных звеньев (0–3): пробует `primary`, при
  **любой** `AIError` логирует и переходит на `secondary` — но каждый
  **следующий** вызов снова начинает с самого верха цепочки, так что
  восстановившийся провайдер подхватывается сам собой, без "залипания"
  на fallback. Ни `AIService`, ни вызывающий код это не видят — как и
  добавление провайдера для другого протокола: реализовать
  `AIProvider.complete()`, ничего больше трогать не нужно.
- **Структурированный вывод.** Всё, что должно попасть в базу
  (`GeneratedWord`, `TextAnalysisResult`, ...), — Pydantic-модели в
  `services/ai_models.py`; сырой JSON от AI (от Gemini или от DeepSeek —
  одинаково) никогда не покидает `ai_service.py` непровалидированным.
  Gemini-запросы используют `responseMimeType: application/json`
  (JSON-режим), тот же ПРОМПТ и тот же Pydantic-парсер/retry, что и
  DeepSeek — ни один prompt не пришлось переписывать под другого
  провайдера.

### `.env`: какие переменные нужны

| Переменная | Обязательна | Назначение |
|---|---|---|
| `AI_GATEWAY_API_KEY` | нет | HIGHEST-priority провайдер — Vercel AI Gateway (маршрутизирует к Gemini и другим моделям из инфраструктуры Vercel, обходя региональные ограничения прямого доступа). Пусто = пропускается, цепочка идёт к `GEMINI_API_KEY`. Получить ключ: vercel.com/ai-gateway — без деплоя кода. **Никогда не коммитить.** |
| `AI_GATEWAY_MODEL` | нет (умолч. `google/gemini-2.5-flash`) | Модель в каталоге Gateway (`creator/model`). Полный список: `curl https://ai-gateway.vercel.sh/v1/models` (без авторизации). |
| `AI_GATEWAY_BASE_URL` | нет (умолч. `https://ai-gateway.vercel.sh/v1`) | Только для нестандартного эндпоинта Gateway. |
| `AI_GATEWAY_ENABLED` | нет (умолч. `true`) | Явный выключатель поверх `AI_GATEWAY_API_KEY`. |
| `GEMINI_API_KEY` | нет | Прямой Gemini, второе звено цепочки. Пусто = используется только `AI_API_KEY` (DeepSeek) как единственный текстовый провайдер, либо только локальная база, если и он пуст. **Никогда не коммитить.** |
| `GEMINI_MODEL` | нет (умолч. `gemini-flash-latest`) | Модель Gemini. `-latest`-алиас — всегда актуальная модель линейки; можно закрепить конкретную версию (например `gemini-2.5-flash`). |
| `GEMINI_TEXT_MODEL` / `GEMINI_MULTIMODAL_MODEL` | нет | Необязательные переопределения `GEMINI_MODEL` отдельно для текста и для фото/аудио — оставьте пустыми, чтобы использовать одну модель для всего. |
| `GEMINI_BASE_URL` | нет | Только для нестандартного эндпоинта Gemini. |
| `GEMINI_ENABLED` | нет (умолч. `true`) | Явный выключатель поверх `GEMINI_API_KEY`. |
| `GEMINI_PROXY_URL` | нет | Форвард-прокси (`http://user:pass@host:port`) для запросов К Gemini, если регион сервера не поддерживается Gemini Developer API напрямую (ошибка `"User location is not supported for the API use"`) — не затрагивает DeepSeek/Telegram/OCR_*/STT_*. |
| `AI_API_KEY` | нет | FALLBACK-провайдер (DeepSeek по умолчанию) для текстовых задач — используется только если Gemini не настроен или временно недоступен. Пусто = нет fallback. **Никогда не коммитить.** |
| `AI_MODEL` | нет (умолч. `gpt-4o-mini`) | Имя модели у fallback-провайдера. |
| `AI_BASE_URL` | нет | Только для не-OpenAI, но OpenAI-совместимого эндпоинта. |
| `AI_ENABLED` | нет (умолч. `true`) | Явный выключатель поверх `AI_API_KEY`. |
| `AI_TIMEOUT_SECONDS` | нет (умолч. `30`) | Таймаут одного запроса к AI — используется и для Gemini, и для fallback-провайдера. |
| `MAX_AI_RETRIES` | нет (умолч. `2`) | Повторы при timeout/сетевой ошибке/невалидном ответе (весь цикл Gemini→fallback повторяется целиком). Никогда не повторяется при 401/403 (неверный ключ). |
| `AI_REQUESTS_PER_MINUTE` / `AI_REQUESTS_PER_DAY` | нет (умолч. `5` / `200`) | Базовый лимит запросов к AI на пользователя (в памяти процесса), общий для всей цепочки Gemini+fallback. |
| `MAX_GENERATION_ATTEMPTS` | нет (умолч. `3`) | Сколько раз `WordGenerationService`/`PhraseService` переспросит AI, если часть результатов оказалась дублями. |

**Как настроить:**

1. `cp .env.example .env` (если ещё не сделано).
2. Получите ключ Gemini на aistudio.google.com (или платный доступ Gemini
   API) и вставьте его **только** в свой локальный `.env` — файл уже в
   `.gitignore`, никогда не попадёт в Git. При желании оставьте
   существующий `AI_API_KEY` (DeepSeek) настроенным — он станет
   text-only fallback-ом автоматически, ничего больше делать не нужно.
3. При необходимости укажите `GEMINI_MODEL`/`AI_MODEL`/`AI_BASE_URL` под
   ваших провайдеров.
4. Перезапустите бота (`python bot.py`).

**Как проверить подключение:**

- `services/ai_diagnostics.test_ai_gateway_connection()`,
  `test_gemini_connection()` и `test_deepseek_connection()` — каждая
  делает один минимальный запрос к своему провайдеру и возвращает
  `ConnectionTestResult(ok, reason, detail)` — никогда не бросает
  исключение и никогда не печатает сам ключ. Все три вызываются
  автоматически при каждом старте бота (`bot.py`'s `on_startup`, не
  блокируют запуск даже при сбое) и пишут в лог ровно `Vercel AI Gateway
  connection: OK` / `Gemini connection: OK` / `DeepSeek connection: OK`
  при успехе, либо `Vercel AI Gateway connection check failed
  (reason=...)` / `Gemini connection check failed (reason=...)` /
  `DeepSeek connection
  check failed (reason=...)` с точной причиной при неудаче
  (`missing_api_key` / `disabled` / `unauthorized` / `rate_limited` /
  `timeout` / `network_error` / `invalid_response`).
- Вручную: `python -c "import asyncio; from services.ai_diagnostics import test_ai_gateway_connection; print(asyncio.run(test_ai_gateway_connection()))"`
  (аналогично с `test_gemini_connection`/`test_deepseek_connection`).
- **`reason=invalid_response` от Gemini на рабочем ключе?** Часто это не
  проблема ключа, а `"User location is not supported for the API use"` —
  Gemini Developer API недоступен из региона сервера. Проверить напрямую:
  ```bash
  source .env
  curl -s "https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL:-gemini-flash-latest}:generateContent" \
    -H "x-goog-api-key: $GEMINI_API_KEY" -H 'Content-Type: application/json' \
    -d '{"contents":[{"parts":[{"text":"ping"}]}]}'
  ```
  Если в ответе именно эта ошибка — бот при этом продолжает работать на
  DeepSeek (fallback сработал автоматически, ничего не сломано). Чтобы
  всё же получить доступ к Gemini из заблокированного региона — два
  варианта:
  1. **`AI_GATEWAY_API_KEY`** (рекомендуется) — Vercel AI Gateway,
     готовый managed-продукт, ключ без деплоя кода (vercel.com/ai-gateway,
     см. таблицу переменных выше). Именно так это подключено на этом
     деплое.
  2. **`GEMINI_PROXY_URL`** — свой форвард-прокси в поддерживаемом
     регионе, если нужен прямой доступ к Gemini API, а не через Gateway.
- В 📖 Словарь введите слово, которого точно нет в seed-наборе
  (`database/seed_words.py`) — например `serendipity`. Если AI настроен
  правильно, придёт карточка с переводом; при следующем вводе того же
  слова карточка приходит мгновенно из локальной базы (AI больше не
  вызывается — раздел про кэширование выше).
- Откройте карточку любого слова и нажмите `💡 Как использовать?` —
  должно прийти развёрнутое объяснение вместо
  «AI-функции пока не настроены.».
- Без ключа (`AI_API_KEY=`) те же действия должны работать **без
  ошибок**: 📖 Словарь ищет только локально, `💡 Как использовать?`
  показывает сохранённый `usage_note` или явное сообщение о том, что AI
  не настроен — бот никогда не падает и не зависает из-за отсутствия ключа.

### Что делает AI сегодня

| Функция | Где | Метод `AIService` |
|---|---|---|
| Поиск незнакомого слова | 📖 Словарь, ➕ Добавить слово | `lookup_word()` |
| Автогенерация новых слов | 📚 Учить слова (через `WordGenerationService`) | `generate_words()` |
| Объяснение слова | Карточка → 💡 Как использовать? | `explain_word()` |
| Разбор текста | 📝 Разобрать текст | `analyze_text()` |
| Объяснение грамматики | ✏️ Грамматика (свободный вопрос, например «Why "went" not "goed"?») | `explain_grammar()` |
| Извлечение слов из текста | зарезервированный метод, пока не вызывается ни одним handler-ом (📷/🎤 переиспользуют `analyze_text()` через `handle_text_input`, см. [«Распознавание фото и голоса (OCR/STT)»](#распознавание-фото-и-голоса-ocrstt)) | `extract_learning_words()` |

Карточка слова (📖 Словарь, ➕ Добавить слово) показывает часть речи,
произношение и значение (`Word.definition`) прямо в тексте карточки, не
отдельными кнопками — только `🔤 Все формы` остаётся отдельной кнопкой
(для глаголов; форма языка-специфична: `base/third_person/past/gerund`
для английского, `Infinitiv/Präsens/Präteritum/Partizip II` для немецкого
и так далее — AI не придумывает форму, если не уверен, просто не
указывает её).

`📝 Разобрать текст`: пользователь присылает текст → AI возвращает
перевод, ключевые слова (слово — перевод, часть речи) и полезные
выражения → пользователь может отправить `⭐ Добавить все` или номера
конкретных слов (`1,3`) → `⭐ Добавить выбранные`. Добавление во всех
случаях идёт через `handlers.dictionary.add_word_batch` — тот же путь
(`DictionaryService` → `UserWordService`), что и у 📖 Словарь/➕ Добавить
слово, без отдельной реализации; слова помечаются `source=ai`.

### Отказоустойчивость (fallback)

Ни одна из этих ситуаций не должна ронять бота или зависать:

- **И `GEMINI_API_KEY`, и `AI_API_KEY` пусты (или отключены)** →
  `get_ai_service()` возвращает `NotConfiguredAIService`, каждый метод
  сразу бросает `AIConfigurationError("AI-функции пока не настроены.")` —
  без сетевого запроса.
- **Gemini ошибся, а DeepSeek настроен** (timeout, сеть, 5xx, rate limit,
  невалидный JSON — любой `AIError`) → `FallbackAIProvider` прозрачно
  переходит на DeepSeek **для этого запроса**; следующий запрос снова
  пробует Gemini первым. Ничего из этого не видно вызывающему коду.
- **Оба провайдера ошиблись** (или только один настроен и он ошибся) →
  `services/ai_errors.py`: `AITimeoutError`/`AIUnavailableError`/
  `AIInvalidResponseError` — весь цикл (Gemini→DeepSeek) повторяется до
  `MAX_AI_RETRIES` раз, затем поднимается вызывающему.
  `DictionaryProvider`/`WordGenerationService` ловят это и откатываются
  на локальную базу; 📝 Разбор текста и `💡 Как использовать?` показывают
  понятное сообщение.
- **Неверный ключ** (401/403) → `AIAuthenticationError` для ЭТОГО
  провайдера — Gemini с неверным ключом всё равно откатывается на
  DeepSeek (если настроен), но сам по себе никогда не повторяется без
  толку.
- **Превышен лимит запросов/квота** → `AIRateLimitedError` — тоже
  триггерит откат на DeepSeek.
- **📷/🎤 (фото/аудио) и Gemini недоступен** → `OCRError`/`STTError`
  показывают понятное сообщение ("Не удалось распознать текст на фото" /
  аналог для голоса) — **без** отката на DeepSeek (не умеет
  изображения/аудио) и без отката на прежний `OCR_API_KEY`/`STT_API_KEY`
  на лету (тот путь используется только когда `GEMINI_API_KEY` вообще не
  задан).

### Безопасность ключей

- Оба ключа читаются только из `.env` (`config.py` →
  `Settings.gemini_api_key` / `Settings.ai_api_key`) — нигде в
  Python-коде, README или тестах нет реального значения.
- `.env` в `.gitignore`; `.env.example` содержит только пустые значения.
- `services/ai_provider.py` (DeepSeek/fallback) передаёт ключ
  исключительно в заголовке `Authorization`; `services/gemini_provider.py`
  (Gemini) — в заголовке `x-goog-api-key` (официально рекомендованная
  Google альтернатива query-параметру `?key=`, именно чтобы ключ не
  оседал в access-логах/URL). Ни один из провайдеров не логирует ключ;
  логи AI-вызовов (`services/ai_service.py`) содержат только операцию,
  user_id, provider/model, время выполнения и тип ошибки (без текста
  запроса/ответа и без ключа).

### Тестирование без реального AI

`tests/test_ai_service.py` использует `MockAIProvider`, а
`tests/test_ai_diagnostics.py` — `MockDeepSeekProvider`: тестовые
реализации `AIProvider` (тот же интерфейс, что и `HttpAIProvider`),
подставляющие заранее заданные ответы/исключения вместо реального HTTP-
запроса. Через них прогоняется настоящий `LiveAIService`/
`test_deepseek_connection()` (сборка промпта → вызов провайдера → retry →
валидация Pydantic-моделью → логирование), так что тесты проверяют
реальную логику, а не только моки.

Ни один тест в проекте не делает настоящий запрос к AI API — даже если в
локальном `.env` разработчика лежит настоящий рабочий ключ DeepSeek.
Это обеспечивает автоматический фикстур `tests/conftest.py:
_isolate_ai_config` (`autouse=True`): каждый тест по умолчанию запускается
с `AI_API_KEY=""`, независимо от реального `.env`; тесты, которым нужен
«настроенный» AI, сами подставляют свой `LiveAIService`/провайдер через
`monkeypatch.setattr(..., "get_ai_service", ...)`, в обход фабрики.

```bash
pytest tests/test_ai_service.py tests/test_ai_diagnostics.py -v
```

## Дополнительные новые слова и «Я это уже знаю»

Часть исправлений bugfix-этапа: после того как дневная порция
📚 Учить слова закончилась (или в любой момент — кнопка
`learn:intro`/`📚 Учить слова` показывает актуальный экран), пользователь
видит три кнопки: **📚 Учить слова** / **➕ Ещё новые слова** /
**⭐ Мои слова**.

**➕ Ещё новые слова** (`handlers/learning.py`, `services/
word_generation_service.generate_extra_words()`):

- Отдельный от `daily_new_words` (2/4/8 в день на язык) пул —
  `MAX_EXTRA_WORDS_PER_DAY` (по умолчанию 20), тоже на язык и на
  календарный день пользователя.
- Нажатие показывает выбор количества (+2/+4/+8, `learn:extra:2/4/8`),
  дальше используется тот же путь генерации, что и у обычной дневной
  порции (локальный пул → AI-добор нехватки), только с
  `trigger="extra_request"` в `WordGenerationLog`, чтобы лимиты не
  смешивались.
- Лимит исчерпан → «На сегодня достигнут лимит дополнительных слов.
  Завтра можно будет добавить ещё.» вместо тихого недобора.
- `services/learning_service.get_new_words_for_today()` расширяет поиск
  уже добавленных, но ещё не показанных `NEW`-слов на количество
  сегодняшних extra-слов, чтобы то, что было добавлено через
  «➕ Ещё новые слова», реально попадало в текущую учебную сессию, а не
  откладывалось на завтра.

**🤔 Я это уже знаю → 🔄 Другое слово** (`services/
learning_service.mark_known_and_replace()`):

- Кнопка показывается только на лицевой стороне карточки **нового**
  (ещё не изученного) слова — для слов, которые уже пришли на повторение,
  её нет: они по определению уже не «совсем новые».
- Нажатие сразу переводит `UserWord.status` в `MASTERED` (слово никогда
  не попадает на обычную лестницу интервального повторения), закрывает
  текущий элемент сессии оценкой `"known"` и пытается подставить один
  замещающий элемент в конец сессии (`trigger="replacement"` в
  `WordGenerationLog`) — так, чтобы дневной объём не уменьшался. Если
  замену найти не удалось (пустой локальный пул и недоступный AI) —
  сессия просто продолжается без замены, ошибка никогда не всплывает
  пользователю.

## Распознавание фото и голоса (OCR/STT)

**📷 Разобрать фото** и **🎤 Разобрать голос** — теперь реальные
Telegram-обработчики (`handlers/media.py`), а не заглушки: файл
скачивается у Telegram, проверяется размер, распознаётся и результат
уходит в тот же пайплайн, что и `📝 Разобрать текст`
(`handlers/text_analysis.handle_text_input`) — перевод, ключевые слова,
`⭐ Добавить все`/`⭐ Добавить выбранные` через `UserWordService`, без
второй реализации «разобрать и предложить добавить».

**Важно: распознавание — это НЕ DeepSeek.** Ни одна документация
DeepSeek не заявляет поддержку изображений или голоса в чат-модели,
поэтому bugfix-спецификация прямо требует не притворяться, что это
работает. **Gemini умеет и то, и другое нативно** (тот же
`generateContent`-вызов с картинкой/аудио в base64 вместо отдельного
эндпоинта) и берёт на себя оба интерфейса автоматически, если
`GEMINI_API_KEY` настроен — раздельная архитектура (`OCRService`/
`SpeechToTextService`) при этом не меняется, меняется только то, какой
провайдер за ней стоит:

```
handlers/media.py (скачать файл, проверить размер, удалить temp-файл)
        │
        ▼                                          ▼
services/ocr_service.py                   services/stt_service.py
  OCRService (интерфейс)                    SpeechToTextService (интерфейс)
        │                                          │
        ▼                                          ▼
services/ocr_provider.py                  services/stt_provider.py
  OCRProvider (интерфейс)                   SpeechToTextProvider (интерфейс)
        │                                          │
        ▼ GEMINI_API_KEY настроен?                 ▼ GEMINI_API_KEY настроен?
   да │         │ нет                          да │         │ нет
      ▼         ▼                                 ▼         ▼
GeminiOCRProvider   HttpOCRProvider       GeminiSTTProvider   HttpSpeechToTextProvider
(services/          (Chat Completions +   (services/          (`/audio/transcriptions`,
 gemini_provider.py)  image_url, OpenAI-    gemini_provider.py)  Whisper-совместимый API)
                      совместимый vision
                      API)
```

- **`GEMINI_API_KEY`/`OCR_API_KEY`/`STT_API_KEY` не заданы по
  умолчанию.** Пока все они пусты, `get_ocr_service()`/`get_stt_service()`
  возвращают `NotConfiguredOCRService`/`NotConfiguredSpeechToTextService`:
  реальное скачивание файла из Telegram, проверка размера и удаление
  temp-файла всё равно происходят, а на этапе распознавания пользователь
  получает честное «Распознавание текста на фото/голосовых сообщений пока
  не настроено.» — никогда не выдуманный результат. DeepSeek никогда не
  подставляется сюда, даже если он настроен как текстовый fallback — не
  умеет изображения/аудио.
- **Независимая конфигурация от AI.** `OCR_PROVIDER`/`OCR_MODEL`/
  `OCR_BASE_URL` и `STT_PROVIDER`/`STT_MODEL`/`STT_BASE_URL` — отдельные
  переменные (см. `.env.example`), используемые только когда
  `GEMINI_API_KEY` не задан; подключить реальный vision- или
  Whisper-совместимый провайдер можно, не трогая `handlers/media.py`
  вообще — только `.env`.
- **Cost control:** `MAX_IMAGE_SIZE_BYTES` (по умолчанию 10 МБ) и
  `MAX_AUDIO_SIZE_BYTES` (по умолчанию 20 МБ) — файл больше лимита
  отклоняется ещё до полной загрузки в память (используется `file_size`
  из ответа Telegram `getFile`), с понятным сообщением пользователю.
- **Temp-файлы.** `utils/media.download_telegram_file()` скачивает файл
  во временный файл и удаляет его в `finally` — гарантированно, даже при
  ошибке скачивания или превышении размера уже после закачки. На сервере
  никогда не остаются файлы пользователей.
- Тесты (`tests/test_media_services.py`, `tests/test_media_handlers.py`)
  используют моки `OCRProvider`/`SpeechToTextProvider` (как
  `MockAIProvider` для AI) — ни один тест не обращается к реальному
  внешнему API.

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
