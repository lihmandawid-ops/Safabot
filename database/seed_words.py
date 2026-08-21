"""Small development word set (spec section 23): enough to exercise
search, cards, and the "same word in different languages doesn't
collide" guarantee - not a real dictionary.

Idempotent like database/seed.py's language seeding: re-running it (every
bot startup) only inserts words that aren't already there, keyed by
(language_code, normalized_word) - the same uniqueness the Word model
itself enforces.
"""
from __future__ import annotations

from database.repositories import words as words_repo
from utils.text import normalize_word

SEED_WORDS: tuple[dict, ...] = (
    {
        "language_code": "en", "word": "go", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "goh", "phonetic": "/ɡoʊ/", "difficulty": "beginner", "category": "daily_life",
        "definition": "to move or travel from one place to another",
        "translations": [{"language_code": "ru", "translation": "идти, ехать", "usage_note": "Часто используется с предлогами: go to, go on, go out."}],
        "examples": [{"example_text": "I go to school every day.", "translation": "Я хожу в школу каждый день.", "level": "beginner"}],
        "forms": [
            {"form_type": "base", "form": "go"}, {"form_type": "third_person", "form": "goes"},
            {"form_type": "past", "form": "went"}, {"form_type": "participle", "form": "gone"},
            {"form_type": "gerund", "form": "going"},
        ],
    },
    {
        "language_code": "en", "word": "make", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "mayk", "phonetic": "/meɪk/", "difficulty": "beginner", "category": "daily_life",
        "definition": "to create or produce something",
        "translations": [{"language_code": "ru", "translation": "делать, создавать"}],
        "examples": [{"example_text": "She makes breakfast every morning.", "translation": "Она готовит завтрак каждое утро."}],
        "forms": [
            {"form_type": "base", "form": "make"}, {"form_type": "third_person", "form": "makes"},
            {"form_type": "past", "form": "made"}, {"form_type": "participle", "form": "made"},
            {"form_type": "gerund", "form": "making"},
        ],
    },
    {
        "language_code": "en", "word": "take", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "tayk", "phonetic": "/teɪk/", "difficulty": "beginner", "category": "daily_life",
        "definition": "to reach out and hold something, or to travel using a means of transport",
        "translations": [{"language_code": "ru", "translation": "брать, взять"}],
        "examples": [{"example_text": "Take the bus to the city center.", "translation": "Поезжай на автобусе в центр города."}],
        "forms": [
            {"form_type": "base", "form": "take"}, {"form_type": "third_person", "form": "takes"},
            {"form_type": "past", "form": "took"}, {"form_type": "participle", "form": "taken"},
            {"form_type": "gerund", "form": "taking"},
        ],
    },
    {
        "language_code": "en", "word": "have", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "hav", "phonetic": "/hæv/", "difficulty": "beginner", "category": "daily_life",
        "definition": "to possess, own, or hold something",
        "translations": [{"language_code": "ru", "translation": "иметь"}],
        "examples": [{"example_text": "I have two brothers.", "translation": "У меня два брата."}],
        "forms": [
            {"form_type": "base", "form": "have"}, {"form_type": "third_person", "form": "has"},
            {"form_type": "past", "form": "had"}, {"form_type": "participle", "form": "had"},
            {"form_type": "gerund", "form": "having"},
        ],
    },
    {
        "language_code": "en", "word": "appointment", "part_of_speech": "noun",
        "pronunciation": "uh-POYNT-ment", "phonetic": "/əˈpɔɪntmənt/", "difficulty": "intermediate", "category": "health",
        "definition": "an arrangement to meet someone at a particular time and place",
        "translations": [
            {"language_code": "ru", "translation": "встреча"},
            {"language_code": "ru", "translation": "запись"},
            {"language_code": "ru", "translation": "назначенная встреча"},
        ],
        "examples": [{"example_text": "I have an appointment tomorrow.", "translation": "У меня завтра встреча."}],
    },
    {
        "language_code": "en", "word": "borrow", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "BOR-oh", "phonetic": "/ˈbɒroʊ/", "difficulty": "elementary", "category": "daily_life",
        "definition": "to take and use something that belongs to someone else, intending to return it",
        "translations": [{"language_code": "ru", "translation": "одолжить, брать взаймы"}],
        "examples": [{"example_text": "Can I borrow your pen?", "translation": "Можно одолжить твою ручку?"}],
        "forms": [
            {"form_type": "base", "form": "borrow"}, {"form_type": "third_person", "form": "borrows"},
            {"form_type": "past", "form": "borrowed"}, {"form_type": "participle", "form": "borrowed"},
            {"form_type": "gerund", "form": "borrowing"},
        ],
    },
    {
        "language_code": "en", "word": "improve", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "im-PROOV", "phonetic": "/ɪmˈpruːv/", "difficulty": "intermediate", "category": "education",
        "definition": "to make or become better",
        "translations": [{"language_code": "ru", "translation": "улучшать"}],
        "examples": [{"example_text": "I want to improve my German.", "translation": "Я хочу улучшить свой немецкий."}],
        "forms": [
            {"form_type": "base", "form": "improve"}, {"form_type": "third_person", "form": "improves"},
            {"form_type": "past", "form": "improved"}, {"form_type": "participle", "form": "improved"},
            {"form_type": "gerund", "form": "improving"},
        ],
    },
    {
        "language_code": "en", "word": "schedule", "part_of_speech": "noun",
        "pronunciation": "SHED-yool", "phonetic": "/ˈʃedjuːl/", "difficulty": "intermediate", "category": "work",
        "definition": "a plan of things that will happen and the times at which they will happen",
        "translations": [{"language_code": "ru", "translation": "расписание"}],
        "examples": [{"example_text": "Here is your schedule for tomorrow.", "translation": "Вот твоё расписание на завтра."}],
    },
    {
        "language_code": "en", "word": "achieve", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "uh-CHEEV", "phonetic": "/əˈtʃiːv/", "difficulty": "intermediate", "category": "education",
        "definition": "to successfully complete something or reach a goal",
        "translations": [{"language_code": "ru", "translation": "достигать"}],
        "examples": [{"example_text": "She achieved her goal.", "translation": "Она достигла своей цели."}],
        "forms": [
            {"form_type": "base", "form": "achieve"}, {"form_type": "third_person", "form": "achieves"},
            {"form_type": "past", "form": "achieved"}, {"form_type": "participle", "form": "achieved"},
            {"form_type": "gerund", "form": "achieving"},
        ],
    },
    {
        "language_code": "en", "word": "environment", "part_of_speech": "noun",
        "pronunciation": "in-VY-run-ment", "phonetic": "/ɪnˈvaɪrənmənt/", "difficulty": "intermediate", "category": "other",
        "definition": "the natural world, or the conditions in which a person lives or works",
        "translations": [{"language_code": "ru", "translation": "окружающая среда"}],
        "examples": [{"example_text": "We must protect the environment.", "translation": "Мы должны защищать окружающую среду."}],
    },
    {
        "language_code": "en", "word": "travel", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "TRAV-uhl", "phonetic": "/ˈtrævəl/", "difficulty": "beginner", "category": "travel",
        "definition": "to go from one place to another, especially over a long distance",
        "translations": [{"language_code": "ru", "translation": "путешествовать"}],
        "examples": [{"example_text": "They love to travel abroad.", "translation": "Они любят путешествовать за границей."}],
        "forms": [
            {"form_type": "base", "form": "travel"}, {"form_type": "third_person", "form": "travels"},
            {"form_type": "past", "form": "travelled"}, {"form_type": "participle", "form": "travelled"},
            {"form_type": "gerund", "form": "travelling"},
        ],
    },
    {
        "language_code": "en", "word": "family", "part_of_speech": "noun",
        "pronunciation": "FAM-uh-lee", "phonetic": "/ˈfæməli/", "difficulty": "beginner", "category": "family",
        "definition": "a group of people related by blood or marriage",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "My family lives in a small town.", "translation": "Моя семья живёт в маленьком городе."}],
    },
    {
        "language_code": "en", "word": "technology", "part_of_speech": "noun",
        "pronunciation": "tek-NOL-uh-jee", "phonetic": "/tekˈnɒlədʒi/", "difficulty": "intermediate", "category": "technology",
        "definition": "machinery and equipment developed from scientific knowledge",
        "translations": [{"language_code": "ru", "translation": "технология"}],
        "examples": [{"example_text": "Technology changes our daily life.", "translation": "Технологии меняют нашу повседневную жизнь."}],
    },
    {
        "language_code": "en", "word": "healthy", "part_of_speech": "adjective",
        "pronunciation": "HEL-thee", "phonetic": "/ˈhelθi/", "difficulty": "beginner", "category": "health",
        "definition": "in good physical or mental condition",
        "translations": [{"language_code": "ru", "translation": "здоровый"}],
        "examples": [{"example_text": "Eating vegetables keeps you healthy.", "translation": "Овощи помогают оставаться здоровым."}],
    },
    {
        "language_code": "en", "word": "transport", "part_of_speech": "noun",
        "pronunciation": "TRAN-sport", "phonetic": "/ˈtrænspɔːt/", "difficulty": "beginner", "category": "transport",
        "definition": "a system or means of moving people or goods",
        "translations": [{"language_code": "ru", "translation": "транспорт"}],
        "examples": [{"example_text": "Public transport is cheap here.", "translation": "Общественный транспорт здесь дешёвый."}],
    },
    {
        "language_code": "en", "word": "business", "part_of_speech": "noun",
        "pronunciation": "BIZ-nis", "phonetic": "/ˈbɪznɪs/", "difficulty": "intermediate", "category": "business",
        "definition": "the activity of buying and selling goods or services",
        "translations": [{"language_code": "ru", "translation": "бизнес, дело"}],
        "examples": [{"example_text": "He started his own business.", "translation": "Он начал своё дело."}],
    },
    {
        "language_code": "en", "word": "quickly", "part_of_speech": "adverb",
        "pronunciation": "KWIK-lee", "phonetic": "/ˈkwɪkli/", "difficulty": "beginner", "category": "other",
        "definition": "at a fast speed",
        "translations": [{"language_code": "ru", "translation": "быстро"}],
        "examples": [{"example_text": "She finished the test quickly.", "translation": "Она быстро закончила тест."}],
    },
    {
        "language_code": "en", "word": "because", "part_of_speech": "conjunction",
        "pronunciation": "bih-KOZ", "phonetic": "/bɪˈkɒz/", "difficulty": "beginner", "category": "other",
        "definition": "for the reason that",
        "translations": [{"language_code": "ru", "translation": "потому что"}],
        "examples": [{"example_text": "I stayed home because it rained.", "translation": "Я остался дома, потому что шёл дождь."}],
    },
    {
        "language_code": "de", "word": "gehen", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "GAY-en", "phonetic": "/ˈɡeːən/", "difficulty": "beginner", "category": "daily_life",
        "definition": "sich zu Fuß fortbewegen",
        "translations": [{"language_code": "ru", "translation": "идти, ходить"}],
        "examples": [{"example_text": "Ich gehe jeden Tag zur Schule.", "translation": "Я хожу в школу каждый день."}],
        "forms": [
            {"form_type": "infinitiv", "form": "gehen"}, {"form_type": "präsens_ich", "form": "gehe"},
            {"form_type": "präteritum", "form": "ging"}, {"form_type": "partizip_ii", "form": "gegangen"},
        ],
    },
    {
        "language_code": "de", "word": "machen", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "MAKH-en", "phonetic": "/ˈmaxən/", "difficulty": "beginner", "category": "daily_life",
        "definition": "etwas herstellen oder tun",
        "translations": [{"language_code": "ru", "translation": "делать"}],
        "examples": [{"example_text": "Was machst du heute?", "translation": "Что ты делаешь сегодня?"}],
        "forms": [
            {"form_type": "infinitiv", "form": "machen"}, {"form_type": "präsens_ich", "form": "mache"},
            {"form_type": "präteritum", "form": "machte"}, {"form_type": "partizip_ii", "form": "gemacht"},
        ],
    },
    {
        "language_code": "de", "word": "nehmen", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "NAY-men", "phonetic": "/ˈneːmən/", "difficulty": "elementary", "category": "daily_life",
        "definition": "etwas in die Hand nehmen oder benutzen",
        "translations": [{"language_code": "ru", "translation": "брать, взять"}],
        "examples": [{"example_text": "Nimm den Bus zum Zentrum.", "translation": "Поезжай на автобусе в центр."}],
        "forms": [
            {"form_type": "infinitiv", "form": "nehmen"}, {"form_type": "präsens_ich", "form": "nehme"},
            {"form_type": "präteritum", "form": "nahm"}, {"form_type": "partizip_ii", "form": "genommen"},
        ],
    },
    {
        "language_code": "de", "word": "haben", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "HAH-ben", "phonetic": "/ˈhaːbən/", "difficulty": "beginner", "category": "daily_life",
        "definition": "etwas besitzen",
        "translations": [{"language_code": "ru", "translation": "иметь"}],
        "examples": [{"example_text": "Ich habe zwei Brüder.", "translation": "У меня два брата."}],
        "forms": [
            {"form_type": "infinitiv", "form": "haben"}, {"form_type": "präsens_ich", "form": "habe"},
            {"form_type": "präteritum", "form": "hatte"}, {"form_type": "partizip_ii", "form": "gehabt"},
        ],
    },
    {
        "language_code": "de", "word": "Termin", "part_of_speech": "noun",
        "pronunciation": "ter-MEEN", "phonetic": "/tɛɐ̯ˈmiːn/", "difficulty": "intermediate", "category": "health",
        "definition": "eine verabredete Zeit für ein Treffen",
        "translations": [{"language_code": "ru", "translation": "встреча, назначенное время"}],
        "examples": [{"example_text": "Ich habe morgen einen Termin.", "translation": "У меня завтра встреча."}],
    },
    {
        "language_code": "de", "word": "verbessern", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "fer-BES-ern", "phonetic": "/fɛɐ̯ˈbɛsɐn/", "difficulty": "intermediate", "category": "education",
        "definition": "besser machen",
        "translations": [{"language_code": "ru", "translation": "улучшать"}],
        "examples": [{"example_text": "Ich möchte mein Deutsch verbessern.", "translation": "Я хочу улучшить свой немецкий."}],
        "forms": [
            {"form_type": "infinitiv", "form": "verbessern"}, {"form_type": "präsens_ich", "form": "verbessere"},
            {"form_type": "präteritum", "form": "verbesserte"}, {"form_type": "partizip_ii", "form": "verbessert"},
        ],
    },
    {
        "language_code": "de", "word": "Umwelt", "part_of_speech": "noun",
        "pronunciation": "OOM-velt", "phonetic": "/ˈʊmvɛlt/", "difficulty": "intermediate", "category": "other",
        "definition": "die natürliche Welt um uns herum",
        "translations": [{"language_code": "ru", "translation": "окружающая среда"}],
        "examples": [{"example_text": "Wir müssen die Umwelt schützen.", "translation": "Мы должны защищать окружающую среду."}],
    },
    {
        "language_code": "de", "word": "Familie", "part_of_speech": "noun",
        "pronunciation": "fah-MEE-lyeh", "phonetic": "/faˈmiːliə/", "difficulty": "beginner", "category": "family",
        "definition": "eine Gruppe von Menschen, die verwandt sind",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "Meine Familie wohnt in einer kleinen Stadt.", "translation": "Моя семья живёт в маленьком городе."}],
    },
    {
        "language_code": "de", "word": "Gesundheit", "part_of_speech": "noun",
        "pronunciation": "guh-ZOONT-hite", "phonetic": "/ɡəˈzʊntˌhaɪt/", "difficulty": "intermediate", "category": "health",
        "definition": "der Zustand, gesund zu sein",
        "translations": [{"language_code": "ru", "translation": "здоровье"}],
        "examples": [{"example_text": "Gesundheit ist wichtiger als Geld.", "translation": "Здоровье важнее денег."}],
    },
    {
        "language_code": "de", "word": "reisen", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "RY-zen", "phonetic": "/ˈʁaɪzən/", "difficulty": "beginner", "category": "travel",
        "definition": "von einem Ort zu einem anderen fahren",
        "translations": [{"language_code": "ru", "translation": "путешествовать"}],
        "examples": [{"example_text": "Sie reisen gern ins Ausland.", "translation": "Они любят путешествовать за границей."}],
        "forms": [
            {"form_type": "infinitiv", "form": "reisen"}, {"form_type": "präsens_ich", "form": "reise"},
            {"form_type": "präteritum", "form": "reiste"}, {"form_type": "partizip_ii", "form": "gereist"},
        ],
    },

    # --- More English (spec: >=20 words/language so generation is
    # testable without a real AI provider configured) ---
    {
        "language_code": "en", "word": "hello", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "привет"}],
        "examples": [{"example_text": "Hello! Nice to meet you.", "translation": "Привет! Приятно познакомиться."}],
    },
    {
        "language_code": "en", "word": "house", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "дом"}],
        "examples": [{"example_text": "This is my house.", "translation": "Это мой дом."}],
    },
    {
        "language_code": "en", "word": "water", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "вода"}],
        "examples": [{"example_text": "Please give me some water.", "translation": "Пожалуйста, дай мне воды."}],
    },
    {
        "language_code": "en", "word": "eat", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "есть, кушать"}],
        "examples": [{"example_text": "I eat breakfast every morning.", "translation": "Я завтракаю каждое утро."}],
        "forms": [
            {"form_type": "base", "form": "eat"}, {"form_type": "third_person", "form": "eats"},
            {"form_type": "past", "form": "ate"}, {"form_type": "participle", "form": "eaten"},
            {"form_type": "gerund", "form": "eating"},
        ],
    },
    {
        "language_code": "en", "word": "happy", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "счастливый"}],
        "examples": [{"example_text": "She is very happy today.", "translation": "Она сегодня очень счастлива."}],
    },

    # --- More German ---
    {
        "language_code": "de", "word": "Hallo", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "привет"}],
        "examples": [{"example_text": "Hallo! Wie geht es dir?", "translation": "Привет! Как дела?"}],
    },
    {
        "language_code": "de", "word": "Haus", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "дом"}],
        "examples": [{"example_text": "Das ist mein Haus.", "translation": "Это мой дом."}],
    },
    {
        "language_code": "de", "word": "Wasser", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "вода"}],
        "examples": [{"example_text": "Ich trinke Wasser.", "translation": "Я пью воду."}],
    },
    {
        "language_code": "de", "word": "essen", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "есть, кушать"}],
        "examples": [{"example_text": "Ich esse einen Apfel.", "translation": "Я ем яблоко."}],
        "forms": [
            {"form_type": "infinitiv", "form": "essen"}, {"form_type": "präsens_ich", "form": "esse"},
            {"form_type": "präteritum", "form": "aß"}, {"form_type": "partizip_ii", "form": "gegessen"},
        ],
    },
    {
        "language_code": "de", "word": "Buch", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "книга"}],
        "examples": [{"example_text": "Ich lese ein interessantes Buch.", "translation": "Я читаю интересную книгу."}],
    },
    {
        "language_code": "de", "word": "Tag", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "день"}],
        "examples": [{"example_text": "Heute ist ein guter Tag.", "translation": "Сегодня хороший день."}],
    },
    {
        "language_code": "de", "word": "gut", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "хороший"}],
        "examples": [{"example_text": "Das ist ein guter Film.", "translation": "Это хороший фильм."}],
    },
    {
        "language_code": "de", "word": "neu", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "новый"}],
        "examples": [{"example_text": "Ich habe ein neues Handy.", "translation": "У меня новый телефон."}],
    },
    {
        "language_code": "de", "word": "klein", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "маленький"}],
        "examples": [{"example_text": "Sie hat einen kleinen Hund.", "translation": "У неё маленькая собака."}],
    },
    {
        "language_code": "de", "word": "lieben", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "любить"}],
        "examples": [{"example_text": "Ich liebe Musik.", "translation": "Я люблю музыку."}],
        "forms": [
            {"form_type": "infinitiv", "form": "lieben"}, {"form_type": "präsens_ich", "form": "liebe"},
            {"form_type": "präteritum", "form": "liebte"}, {"form_type": "partizip_ii", "form": "geliebt"},
        ],
    },
    {
        "language_code": "de", "word": "Zeit", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "время"}],
        "examples": [{"example_text": "Ich habe keine Zeit.", "translation": "У меня нет времени."}],
    },
    {
        "language_code": "de", "word": "Hund", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "собака"}],
        "examples": [{"example_text": "Ich habe einen Hund.", "translation": "У меня есть собака."}],
    },

    # --- Russian (>=20 words, translated into English) ---
    {
        "language_code": "ru", "word": "привет", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "hello"}],
        "examples": [{"example_text": "Привет! Как дела?", "translation": "Hi! How are you?"}],
    },
    {
        "language_code": "ru", "word": "дом", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "en", "translation": "house"}],
        "examples": [{"example_text": "Мой дом большой.", "translation": "My house is big."}],
    },
    {
        "language_code": "ru", "word": "вода", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "en", "translation": "water"}],
        "examples": [{"example_text": "Я пью воду.", "translation": "I drink water."}],
    },
    {
        "language_code": "ru", "word": "есть", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "en", "translation": "to eat"}],
        "examples": [{"example_text": "Я ем яблоко.", "translation": "I eat an apple."}],
    },
    {
        "language_code": "ru", "word": "работать", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "work",
        "translations": [{"language_code": "en", "translation": "to work"}],
        "examples": [{"example_text": "Я работаю в офисе.", "translation": "I work in an office."}],
    },
    {
        "language_code": "ru", "word": "семья", "part_of_speech": "noun", "difficulty": "beginner", "category": "family",
        "translations": [{"language_code": "en", "translation": "family"}],
        "examples": [{"example_text": "Моя семья живёт в Москве.", "translation": "My family lives in Moscow."}],
    },
    {
        "language_code": "ru", "word": "друг", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "en", "translation": "friend"}],
        "examples": [{"example_text": "Он мой лучший друг.", "translation": "He is my best friend."}],
    },
    {
        "language_code": "ru", "word": "книга", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "en", "translation": "book"}],
        "examples": [{"example_text": "Я читаю интересную книгу.", "translation": "I am reading an interesting book."}],
    },
    {
        "language_code": "ru", "word": "день", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "day"}],
        "examples": [{"example_text": "Сегодня хороший день.", "translation": "Today is a good day."}],
    },
    {
        "language_code": "ru", "word": "хороший", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "good"}],
        "examples": [{"example_text": "Это хороший фильм.", "translation": "This is a good movie."}],
    },
    {
        "language_code": "ru", "word": "новый", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "new"}],
        "examples": [{"example_text": "У меня новый телефон.", "translation": "I have a new phone."}],
    },
    {
        "language_code": "ru", "word": "большой", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "big"}],
        "examples": [{"example_text": "Это большой город.", "translation": "This is a big city."}],
    },
    {
        "language_code": "ru", "word": "маленький", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "small"}],
        "examples": [{"example_text": "У неё маленькая собака.", "translation": "She has a small dog."}],
    },
    {
        "language_code": "ru", "word": "любить", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "en", "translation": "to love"}],
        "examples": [{"example_text": "Я люблю музыку.", "translation": "I love music."}],
    },
    {
        "language_code": "ru", "word": "время", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "time"}],
        "examples": [{"example_text": "У меня нет времени.", "translation": "I don't have time."}],
    },
    {
        "language_code": "ru", "word": "город", "part_of_speech": "noun", "difficulty": "beginner", "category": "travel",
        "translations": [{"language_code": "en", "translation": "city"}],
        "examples": [{"example_text": "Москва — большой город.", "translation": "Moscow is a big city."}],
    },
    {
        "language_code": "ru", "word": "школа", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "en", "translation": "school"}],
        "examples": [{"example_text": "Дети идут в школу.", "translation": "The children go to school."}],
    },
    {
        "language_code": "ru", "word": "счастливый", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "happy"}],
        "examples": [{"example_text": "Она счастливый человек.", "translation": "She is a happy person."}],
    },
    {
        "language_code": "ru", "word": "солнце", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "sun"}],
        "examples": [{"example_text": "Солнце светит ярко.", "translation": "The sun shines brightly."}],
    },
    {
        "language_code": "ru", "word": "собака", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "en", "translation": "dog"}],
        "examples": [{"example_text": "У меня есть собака.", "translation": "I have a dog."}],
    },
    {
        "language_code": "ru", "word": "спасибо", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "en", "translation": "thank you"}],
        "examples": [{"example_text": "Спасибо за помощь!", "translation": "Thank you for your help!"}],
    },

    # --- Hebrew (>=20 words, translated into Russian) ---
    {
        "language_code": "he", "word": "שלום", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "pronunciation": "shalom",
        "translations": [{"language_code": "ru", "translation": "привет"}],
        "examples": [{"example_text": "שלום! מה שלומך?", "translation": "Привет! Как дела?"}],
    },
    {
        "language_code": "he", "word": "בית", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "pronunciation": "bayit",
        "translations": [{"language_code": "ru", "translation": "дом"}],
        "examples": [{"example_text": "זה הבית שלי.", "translation": "Это мой дом."}],
    },
    {
        "language_code": "he", "word": "מים", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "pronunciation": "mayim",
        "translations": [{"language_code": "ru", "translation": "вода"}],
        "examples": [{"example_text": "אני שותה מים.", "translation": "Я пью воду."}],
    },
    {
        "language_code": "he", "word": "לאכול", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "pronunciation": "le'echol",
        "translations": [{"language_code": "ru", "translation": "есть, кушать"}],
        "examples": [{"example_text": "אני אוכל תפוח.", "translation": "Я ем яблоко."}],
    },
    {
        "language_code": "he", "word": "לעבוד", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "work",
        "pronunciation": "la'avod",
        "translations": [{"language_code": "ru", "translation": "работать"}],
        "examples": [{"example_text": "אני עובד במשרד.", "translation": "Я работаю в офисе."}],
    },
    {
        "language_code": "he", "word": "משפחה", "part_of_speech": "noun", "difficulty": "beginner", "category": "family",
        "pronunciation": "mishpacha",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "המשפחה שלי גרה בתל אביב.", "translation": "Моя семья живёт в Тель-Авиве."}],
    },
    {
        "language_code": "he", "word": "חבר", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "pronunciation": "chaver",
        "translations": [{"language_code": "ru", "translation": "друг"}],
        "examples": [{"example_text": "הוא החבר הכי טוב שלי.", "translation": "Он мой лучший друг."}],
    },
    {
        "language_code": "he", "word": "ספר", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "pronunciation": "sefer",
        "translations": [{"language_code": "ru", "translation": "книга"}],
        "examples": [{"example_text": "אני קורא ספר מעניין.", "translation": "Я читаю интересную книгу."}],
    },
    {
        "language_code": "he", "word": "יום", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "pronunciation": "yom",
        "translations": [{"language_code": "ru", "translation": "день"}],
        "examples": [{"example_text": "היום זה יום טוב.", "translation": "Сегодня хороший день."}],
    },
    {
        "language_code": "he", "word": "טוב", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "pronunciation": "tov",
        "translations": [{"language_code": "ru", "translation": "хороший"}],
        "examples": [{"example_text": "זה סרט טוב.", "translation": "Это хороший фильм."}],
    },
    {
        "language_code": "he", "word": "חדש", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "pronunciation": "chadash",
        "translations": [{"language_code": "ru", "translation": "новый"}],
        "examples": [{"example_text": "יש לי טלפון חדש.", "translation": "У меня новый телефон."}],
    },
    {
        "language_code": "he", "word": "גדול", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "pronunciation": "gadol",
        "translations": [{"language_code": "ru", "translation": "большой"}],
        "examples": [{"example_text": "זו עיר גדולה.", "translation": "Это большой город."}],
    },
    {
        "language_code": "he", "word": "קטן", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "pronunciation": "katan",
        "translations": [{"language_code": "ru", "translation": "маленький"}],
        "examples": [{"example_text": "יש לה כלב קטן.", "translation": "У неё маленькая собака."}],
    },
    {
        "language_code": "he", "word": "לאהוב", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "daily_life",
        "pronunciation": "le'ehov",
        "translations": [{"language_code": "ru", "translation": "любить"}],
        "examples": [{"example_text": "אני אוהב מוזיקה.", "translation": "Я люблю музыку."}],
    },
    {
        "language_code": "he", "word": "זמן", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "pronunciation": "zman",
        "translations": [{"language_code": "ru", "translation": "время"}],
        "examples": [{"example_text": "אין לי זמן.", "translation": "У меня нет времени."}],
    },
    {
        "language_code": "he", "word": "עיר", "part_of_speech": "noun", "difficulty": "beginner", "category": "travel",
        "pronunciation": "ir",
        "translations": [{"language_code": "ru", "translation": "город"}],
        "examples": [{"example_text": "תל אביב היא עיר גדולה.", "translation": "Тель-Авив — большой город."}],
    },
    {
        "language_code": "he", "word": "בית ספר", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "pronunciation": "beit sefer",
        "translations": [{"language_code": "ru", "translation": "школа"}],
        "examples": [{"example_text": "הילדים הולכים לבית הספר.", "translation": "Дети идут в школу."}],
    },
    {
        "language_code": "he", "word": "שמח", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "pronunciation": "sameach",
        "translations": [{"language_code": "ru", "translation": "счастливый"}],
        "examples": [{"example_text": "היא אדם שמח.", "translation": "Она счастливый человек."}],
    },
    {
        "language_code": "he", "word": "שמש", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "pronunciation": "shemesh",
        "translations": [{"language_code": "ru", "translation": "солнце"}],
        "examples": [{"example_text": "השמש זורחת בחוזקה.", "translation": "Солнце светит ярко."}],
    },
    {
        "language_code": "he", "word": "כלב", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "pronunciation": "kelev",
        "translations": [{"language_code": "ru", "translation": "собака"}],
        "examples": [{"example_text": "יש לי כלב.", "translation": "У меня есть собака."}],
    },
    {
        "language_code": "he", "word": "תודה", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "pronunciation": "toda",
        "translations": [{"language_code": "ru", "translation": "спасибо"}],
        "examples": [{"example_text": "תודה על העזרה!", "translation": "Спасибо за помощь!"}],
    },

    # --- Spanish (>=20 words, translated into Russian) ---
    {
        "language_code": "es", "word": "hola", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "привет"}],
        "examples": [{"example_text": "¡Hola! ¿Cómo estás?", "translation": "Привет! Как дела?"}],
    },
    {
        "language_code": "es", "word": "casa", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "дом"}],
        "examples": [{"example_text": "Esta es mi casa.", "translation": "Это мой дом."}],
    },
    {
        "language_code": "es", "word": "agua", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "вода"}],
        "examples": [{"example_text": "Bebo agua todos los días.", "translation": "Я пью воду каждый день."}],
    },
    {
        "language_code": "es", "word": "comer", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "есть, кушать"}],
        "examples": [{"example_text": "Yo como una manzana.", "translation": "Я ем яблоко."}],
    },
    {
        "language_code": "es", "word": "trabajar", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "work",
        "translations": [{"language_code": "ru", "translation": "работать"}],
        "examples": [{"example_text": "Trabajo en una oficina.", "translation": "Я работаю в офисе."}],
    },
    {
        "language_code": "es", "word": "familia", "part_of_speech": "noun", "difficulty": "beginner", "category": "family",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "Mi familia vive en Madrid.", "translation": "Моя семья живёт в Мадриде."}],
    },
    {
        "language_code": "es", "word": "amigo", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "друг"}],
        "examples": [{"example_text": "Él es mi mejor amigo.", "translation": "Он мой лучший друг."}],
    },
    {
        "language_code": "es", "word": "libro", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "книга"}],
        "examples": [{"example_text": "Estoy leyendo un libro interesante.", "translation": "Я читаю интересную книгу."}],
    },
    {
        "language_code": "es", "word": "día", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "день"}],
        "examples": [{"example_text": "Hoy es un buen día.", "translation": "Сегодня хороший день."}],
    },
    {
        "language_code": "es", "word": "bueno", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "хороший"}],
        "examples": [{"example_text": "Es una buena película.", "translation": "Это хороший фильм."}],
    },
    {
        "language_code": "es", "word": "nuevo", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "новый"}],
        "examples": [{"example_text": "Tengo un teléfono nuevo.", "translation": "У меня новый телефон."}],
    },
    {
        "language_code": "es", "word": "grande", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "большой"}],
        "examples": [{"example_text": "Es una ciudad grande.", "translation": "Это большой город."}],
    },
    {
        "language_code": "es", "word": "pequeño", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "маленький"}],
        "examples": [{"example_text": "Ella tiene un perro pequeño.", "translation": "У неё маленькая собака."}],
    },
    {
        "language_code": "es", "word": "amar", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "любить"}],
        "examples": [{"example_text": "Amo la música.", "translation": "Я люблю музыку."}],
    },
    {
        "language_code": "es", "word": "tiempo", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "время"}],
        "examples": [{"example_text": "No tengo tiempo.", "translation": "У меня нет времени."}],
    },
    {
        "language_code": "es", "word": "ciudad", "part_of_speech": "noun", "difficulty": "beginner", "category": "travel",
        "translations": [{"language_code": "ru", "translation": "город"}],
        "examples": [{"example_text": "Madrid es una ciudad grande.", "translation": "Мадрид — большой город."}],
    },
    {
        "language_code": "es", "word": "escuela", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "школа"}],
        "examples": [{"example_text": "Los niños van a la escuela.", "translation": "Дети идут в школу."}],
    },
    {
        "language_code": "es", "word": "feliz", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "счастливый"}],
        "examples": [{"example_text": "Ella es una persona feliz.", "translation": "Она счастливый человек."}],
    },
    {
        "language_code": "es", "word": "sol", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "солнце"}],
        "examples": [{"example_text": "El sol brilla intensamente.", "translation": "Солнце светит ярко."}],
    },
    {
        "language_code": "es", "word": "perro", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "собака"}],
        "examples": [{"example_text": "Tengo un perro.", "translation": "У меня есть собака."}],
    },
    {
        "language_code": "es", "word": "gracias", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "спасибо"}],
        "examples": [{"example_text": "¡Gracias por tu ayuda!", "translation": "Спасибо за твою помощь!"}],
    },

    # --- French (>=20 words, translated into Russian) ---
    {
        "language_code": "fr", "word": "bonjour", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "привет"}],
        "examples": [{"example_text": "Bonjour ! Comment ça va ?", "translation": "Привет! Как дела?"}],
    },
    {
        "language_code": "fr", "word": "maison", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "дом"}],
        "examples": [{"example_text": "Voici ma maison.", "translation": "Вот мой дом."}],
    },
    {
        "language_code": "fr", "word": "eau", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "вода"}],
        "examples": [{"example_text": "Je bois de l'eau.", "translation": "Я пью воду."}],
    },
    {
        "language_code": "fr", "word": "manger", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "есть, кушать"}],
        "examples": [{"example_text": "Je mange une pomme.", "translation": "Я ем яблоко."}],
    },
    {
        "language_code": "fr", "word": "travailler", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "work",
        "translations": [{"language_code": "ru", "translation": "работать"}],
        "examples": [{"example_text": "Je travaille dans un bureau.", "translation": "Я работаю в офисе."}],
    },
    {
        "language_code": "fr", "word": "famille", "part_of_speech": "noun", "difficulty": "beginner", "category": "family",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "Ma famille habite à Paris.", "translation": "Моя семья живёт в Париже."}],
    },
    {
        "language_code": "fr", "word": "ami", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "друг"}],
        "examples": [{"example_text": "Il est mon meilleur ami.", "translation": "Он мой лучший друг."}],
    },
    {
        "language_code": "fr", "word": "livre", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "книга"}],
        "examples": [{"example_text": "Je lis un livre intéressant.", "translation": "Я читаю интересную книгу."}],
    },
    {
        "language_code": "fr", "word": "jour", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "день"}],
        "examples": [{"example_text": "Aujourd'hui est un bon jour.", "translation": "Сегодня хороший день."}],
    },
    {
        "language_code": "fr", "word": "bon", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "хороший"}],
        "examples": [{"example_text": "C'est un bon film.", "translation": "Это хороший фильм."}],
    },
    {
        "language_code": "fr", "word": "nouveau", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "новый"}],
        "examples": [{"example_text": "J'ai un nouveau téléphone.", "translation": "У меня новый телефон."}],
    },
    {
        "language_code": "fr", "word": "grand", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "большой"}],
        "examples": [{"example_text": "C'est une grande ville.", "translation": "Это большой город."}],
    },
    {
        "language_code": "fr", "word": "petit", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "маленький"}],
        "examples": [{"example_text": "Elle a un petit chien.", "translation": "У неё маленькая собака."}],
    },
    {
        "language_code": "fr", "word": "aimer", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "любить"}],
        "examples": [{"example_text": "J'aime la musique.", "translation": "Я люблю музыку."}],
    },
    {
        "language_code": "fr", "word": "temps", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "время"}],
        "examples": [{"example_text": "Je n'ai pas de temps.", "translation": "У меня нет времени."}],
    },
    {
        "language_code": "fr", "word": "ville", "part_of_speech": "noun", "difficulty": "beginner", "category": "travel",
        "translations": [{"language_code": "ru", "translation": "город"}],
        "examples": [{"example_text": "Paris est une grande ville.", "translation": "Париж — большой город."}],
    },
    {
        "language_code": "fr", "word": "école", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "школа"}],
        "examples": [{"example_text": "Les enfants vont à l'école.", "translation": "Дети идут в школу."}],
    },
    {
        "language_code": "fr", "word": "heureux", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "счастливый"}],
        "examples": [{"example_text": "Elle est une personne heureuse.", "translation": "Она счастливый человек."}],
    },
    {
        "language_code": "fr", "word": "soleil", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "солнце"}],
        "examples": [{"example_text": "Le soleil brille fort.", "translation": "Солнце светит ярко."}],
    },
    {
        "language_code": "fr", "word": "chien", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "собака"}],
        "examples": [{"example_text": "J'ai un chien.", "translation": "У меня есть собака."}],
    },
    {
        "language_code": "fr", "word": "merci", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "спасибо"}],
        "examples": [{"example_text": "Merci pour ton aide !", "translation": "Спасибо за помощь!"}],
    },

    # --- Italian (>=20 words, translated into Russian) ---
    {
        "language_code": "it", "word": "ciao", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "привет"}],
        "examples": [{"example_text": "Ciao! Come stai?", "translation": "Привет! Как дела?"}],
    },
    {
        "language_code": "it", "word": "casa", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "дом"}],
        "examples": [{"example_text": "Questa è la mia casa.", "translation": "Это мой дом."}],
    },
    {
        "language_code": "it", "word": "acqua", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "вода"}],
        "examples": [{"example_text": "Bevo acqua ogni giorno.", "translation": "Я пью воду каждый день."}],
    },
    {
        "language_code": "it", "word": "mangiare", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "есть, кушать"}],
        "examples": [{"example_text": "Io mangio una mela.", "translation": "Я ем яблоко."}],
    },
    {
        "language_code": "it", "word": "lavorare", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "work",
        "translations": [{"language_code": "ru", "translation": "работать"}],
        "examples": [{"example_text": "Lavoro in un ufficio.", "translation": "Я работаю в офисе."}],
    },
    {
        "language_code": "it", "word": "famiglia", "part_of_speech": "noun", "difficulty": "beginner", "category": "family",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "La mia famiglia vive a Roma.", "translation": "Моя семья живёт в Риме."}],
    },
    {
        "language_code": "it", "word": "amico", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "друг"}],
        "examples": [{"example_text": "Lui è il mio migliore amico.", "translation": "Он мой лучший друг."}],
    },
    {
        "language_code": "it", "word": "libro", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "книга"}],
        "examples": [{"example_text": "Sto leggendo un libro interessante.", "translation": "Я читаю интересную книгу."}],
    },
    {
        "language_code": "it", "word": "giorno", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "день"}],
        "examples": [{"example_text": "Oggi è una buona giornata.", "translation": "Сегодня хороший день."}],
    },
    {
        "language_code": "it", "word": "buono", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "хороший"}],
        "examples": [{"example_text": "È un buon film.", "translation": "Это хороший фильм."}],
    },
    {
        "language_code": "it", "word": "nuovo", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "новый"}],
        "examples": [{"example_text": "Ho un telefono nuovo.", "translation": "У меня новый телефон."}],
    },
    {
        "language_code": "it", "word": "grande", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "большой"}],
        "examples": [{"example_text": "È una grande città.", "translation": "Это большой город."}],
    },
    {
        "language_code": "it", "word": "piccolo", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "маленький"}],
        "examples": [{"example_text": "Lei ha un cane piccolo.", "translation": "У неё маленькая собака."}],
    },
    {
        "language_code": "it", "word": "amare", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "любить"}],
        "examples": [{"example_text": "Amo la musica.", "translation": "Я люблю музыку."}],
    },
    {
        "language_code": "it", "word": "tempo", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "время"}],
        "examples": [{"example_text": "Non ho tempo.", "translation": "У меня нет времени."}],
    },
    {
        "language_code": "it", "word": "città", "part_of_speech": "noun", "difficulty": "beginner", "category": "travel",
        "translations": [{"language_code": "ru", "translation": "город"}],
        "examples": [{"example_text": "Roma è una grande città.", "translation": "Рим — большой город."}],
    },
    {
        "language_code": "it", "word": "scuola", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "школа"}],
        "examples": [{"example_text": "I bambini vanno a scuola.", "translation": "Дети идут в школу."}],
    },
    {
        "language_code": "it", "word": "felice", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "счастливый"}],
        "examples": [{"example_text": "Lei è una persona felice.", "translation": "Она счастливый человек."}],
    },
    {
        "language_code": "it", "word": "sole", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "солнце"}],
        "examples": [{"example_text": "Il sole splende forte.", "translation": "Солнце светит ярко."}],
    },
    {
        "language_code": "it", "word": "cane", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "собака"}],
        "examples": [{"example_text": "Ho un cane.", "translation": "У меня есть собака."}],
    },
    {
        "language_code": "it", "word": "grazie", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "спасибо"}],
        "examples": [{"example_text": "Grazie per il tuo aiuto!", "translation": "Спасибо за твою помощь!"}],
    },

    # --- Ukrainian (>=20 words, translated into Russian) ---
    {
        "language_code": "uk", "word": "привіт", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "привет"}],
        "examples": [{"example_text": "Привіт! Як справи?", "translation": "Привет! Как дела?"}],
    },
    {
        "language_code": "uk", "word": "будинок", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "дом"}],
        "examples": [{"example_text": "Це мій будинок.", "translation": "Это мой дом."}],
    },
    {
        "language_code": "uk", "word": "вода", "part_of_speech": "noun", "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "вода"}],
        "examples": [{"example_text": "Я п'ю воду.", "translation": "Я пью воду."}],
    },
    {
        "language_code": "uk", "word": "їсти", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "food",
        "translations": [{"language_code": "ru", "translation": "есть, кушать"}],
        "examples": [{"example_text": "Я їм яблуко.", "translation": "Я ем яблоко."}],
    },
    {
        "language_code": "uk", "word": "працювати", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "work",
        "translations": [{"language_code": "ru", "translation": "работать"}],
        "examples": [{"example_text": "Я працюю в офісі.", "translation": "Я работаю в офисе."}],
    },
    {
        "language_code": "uk", "word": "сім'я", "part_of_speech": "noun", "difficulty": "beginner", "category": "family",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "Моя сім'я живе у Києві.", "translation": "Моя семья живёт в Киеве."}],
    },
    {
        "language_code": "uk", "word": "друг", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "друг"}],
        "examples": [{"example_text": "Він мій найкращий друг.", "translation": "Он мой лучший друг."}],
    },
    {
        "language_code": "uk", "word": "книга", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "книга"}],
        "examples": [{"example_text": "Я читаю цікаву книгу.", "translation": "Я читаю интересную книгу."}],
    },
    {
        "language_code": "uk", "word": "день", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "день"}],
        "examples": [{"example_text": "Сьогодні гарний день.", "translation": "Сегодня хороший день."}],
    },
    {
        "language_code": "uk", "word": "хороший", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "хороший"}],
        "examples": [{"example_text": "Це хороший фільм.", "translation": "Это хороший фильм."}],
    },
    {
        "language_code": "uk", "word": "новий", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "новый"}],
        "examples": [{"example_text": "У мене новий телефон.", "translation": "У меня новый телефон."}],
    },
    {
        "language_code": "uk", "word": "великий", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "большой"}],
        "examples": [{"example_text": "Це велике місто.", "translation": "Это большой город."}],
    },
    {
        "language_code": "uk", "word": "маленький", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "маленький"}],
        "examples": [{"example_text": "У неї маленька собака.", "translation": "У неё маленькая собака."}],
    },
    {
        "language_code": "uk", "word": "любити", "part_of_speech": "verb", "is_verb": True, "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "любить"}],
        "examples": [{"example_text": "Я люблю музику.", "translation": "Я люблю музыку."}],
    },
    {
        "language_code": "uk", "word": "час", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "время"}],
        "examples": [{"example_text": "У мене немає часу.", "translation": "У меня нет времени."}],
    },
    {
        "language_code": "uk", "word": "місто", "part_of_speech": "noun", "difficulty": "beginner", "category": "travel",
        "translations": [{"language_code": "ru", "translation": "город"}],
        "examples": [{"example_text": "Київ — велике місто.", "translation": "Киев — большой город."}],
    },
    {
        "language_code": "uk", "word": "школа", "part_of_speech": "noun", "difficulty": "beginner", "category": "education",
        "translations": [{"language_code": "ru", "translation": "школа"}],
        "examples": [{"example_text": "Діти йдуть до школи.", "translation": "Дети идут в школу."}],
    },
    {
        "language_code": "uk", "word": "щасливий", "part_of_speech": "adjective", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "счастливый"}],
        "examples": [{"example_text": "Вона щаслива людина.", "translation": "Она счастливый человек."}],
    },
    {
        "language_code": "uk", "word": "сонце", "part_of_speech": "noun", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "солнце"}],
        "examples": [{"example_text": "Сонце яскраво світить.", "translation": "Солнце светит ярко."}],
    },
    {
        "language_code": "uk", "word": "собака", "part_of_speech": "noun", "difficulty": "beginner", "category": "daily_life",
        "translations": [{"language_code": "ru", "translation": "собака"}],
        "examples": [{"example_text": "У мене є собака.", "translation": "У меня есть собака."}],
    },
    {
        "language_code": "uk", "word": "дякую", "part_of_speech": "other", "difficulty": "beginner", "category": "other",
        "translations": [{"language_code": "ru", "translation": "спасибо"}],
        "examples": [{"example_text": "Дякую за допомогу!", "translation": "Спасибо за помощь!"}],
    },
)


async def seed_words(session) -> int:
    """Insert every SEED_WORDS entry not already present. Returns the
    total number of Word rows that now exist across the seed languages
    (not just the ones newly inserted this run)."""
    inserted = 0
    for entry in SEED_WORDS:
        language_code = entry["language_code"]
        normalized = normalize_word(entry["word"])
        existing = await words_repo.find_exact(session, language_code=language_code, normalized_word=normalized)
        if existing is not None:
            continue

        word = await words_repo.create(
            session,
            language_code=language_code,
            word=entry["word"],
            part_of_speech=entry.get("part_of_speech"),
            pronunciation=entry.get("pronunciation"),
            phonetic=entry.get("phonetic"),
            definition=entry.get("definition"),
            difficulty=entry.get("difficulty"),
            category=entry.get("category"),
            is_verb=entry.get("is_verb", False),
        )
        for tr in entry.get("translations", []):
            await words_repo.add_translation(session, word_id=word.id, **tr)
        for ex in entry.get("examples", []):
            await words_repo.add_example(session, word_id=word.id, **ex)
        for form in entry.get("forms", []):
            await words_repo.add_form(session, word_id=word.id, **form)
        inserted += 1

    if inserted:
        await session.flush()

    return len({(e["language_code"], normalize_word(e["word"])) for e in SEED_WORDS})
