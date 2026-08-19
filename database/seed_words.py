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
        "pronunciation": "/ɡoʊ/", "phonetic": "goh", "difficulty": "beginner", "category": "daily_life",
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
        "pronunciation": "/meɪk/", "phonetic": "mayk", "difficulty": "beginner", "category": "daily_life",
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
        "pronunciation": "/teɪk/", "phonetic": "tayk", "difficulty": "beginner", "category": "daily_life",
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
        "pronunciation": "/hæv/", "phonetic": "hav", "difficulty": "beginner", "category": "daily_life",
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
        "pronunciation": "/əˈpɔɪntmənt/", "phonetic": "uh-POYNT-ment", "difficulty": "intermediate", "category": "health",
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
        "pronunciation": "/ˈbɒroʊ/", "phonetic": "BOR-oh", "difficulty": "elementary", "category": "daily_life",
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
        "pronunciation": "/ɪmˈpruːv/", "phonetic": "im-PROOV", "difficulty": "intermediate", "category": "education",
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
        "pronunciation": "/ˈʃedjuːl/", "phonetic": "SHED-yool", "difficulty": "intermediate", "category": "work",
        "definition": "a plan of things that will happen and the times at which they will happen",
        "translations": [{"language_code": "ru", "translation": "расписание"}],
        "examples": [{"example_text": "Here is your schedule for tomorrow.", "translation": "Вот твоё расписание на завтра."}],
    },
    {
        "language_code": "en", "word": "achieve", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "/əˈtʃiːv/", "phonetic": "uh-CHEEV", "difficulty": "intermediate", "category": "education",
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
        "pronunciation": "/ɪnˈvaɪrənmənt/", "phonetic": "in-VY-run-ment", "difficulty": "intermediate", "category": "other",
        "definition": "the natural world, or the conditions in which a person lives or works",
        "translations": [{"language_code": "ru", "translation": "окружающая среда"}],
        "examples": [{"example_text": "We must protect the environment.", "translation": "Мы должны защищать окружающую среду."}],
    },
    {
        "language_code": "en", "word": "travel", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "/ˈtrævəl/", "phonetic": "TRAV-uhl", "difficulty": "beginner", "category": "travel",
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
        "pronunciation": "/ˈfæməli/", "phonetic": "FAM-uh-lee", "difficulty": "beginner", "category": "family",
        "definition": "a group of people related by blood or marriage",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "My family lives in a small town.", "translation": "Моя семья живёт в маленьком городе."}],
    },
    {
        "language_code": "en", "word": "technology", "part_of_speech": "noun",
        "pronunciation": "/tekˈnɒlədʒi/", "phonetic": "tek-NOL-uh-jee", "difficulty": "intermediate", "category": "technology",
        "definition": "machinery and equipment developed from scientific knowledge",
        "translations": [{"language_code": "ru", "translation": "технология"}],
        "examples": [{"example_text": "Technology changes our daily life.", "translation": "Технологии меняют нашу повседневную жизнь."}],
    },
    {
        "language_code": "en", "word": "healthy", "part_of_speech": "adjective",
        "pronunciation": "/ˈhelθi/", "phonetic": "HEL-thee", "difficulty": "beginner", "category": "health",
        "definition": "in good physical or mental condition",
        "translations": [{"language_code": "ru", "translation": "здоровый"}],
        "examples": [{"example_text": "Eating vegetables keeps you healthy.", "translation": "Овощи помогают оставаться здоровым."}],
    },
    {
        "language_code": "en", "word": "transport", "part_of_speech": "noun",
        "pronunciation": "/ˈtrænspɔːt/", "phonetic": "TRAN-sport", "difficulty": "beginner", "category": "transport",
        "definition": "a system or means of moving people or goods",
        "translations": [{"language_code": "ru", "translation": "транспорт"}],
        "examples": [{"example_text": "Public transport is cheap here.", "translation": "Общественный транспорт здесь дешёвый."}],
    },
    {
        "language_code": "en", "word": "business", "part_of_speech": "noun",
        "pronunciation": "/ˈbɪznɪs/", "phonetic": "BIZ-nis", "difficulty": "intermediate", "category": "business",
        "definition": "the activity of buying and selling goods or services",
        "translations": [{"language_code": "ru", "translation": "бизнес, дело"}],
        "examples": [{"example_text": "He started his own business.", "translation": "Он начал своё дело."}],
    },
    {
        "language_code": "en", "word": "quickly", "part_of_speech": "adverb",
        "pronunciation": "/ˈkwɪkli/", "phonetic": "KWIK-lee", "difficulty": "beginner", "category": "other",
        "definition": "at a fast speed",
        "translations": [{"language_code": "ru", "translation": "быстро"}],
        "examples": [{"example_text": "She finished the test quickly.", "translation": "Она быстро закончила тест."}],
    },
    {
        "language_code": "en", "word": "because", "part_of_speech": "conjunction",
        "pronunciation": "/bɪˈkɒz/", "phonetic": "bih-KOZ", "difficulty": "beginner", "category": "other",
        "definition": "for the reason that",
        "translations": [{"language_code": "ru", "translation": "потому что"}],
        "examples": [{"example_text": "I stayed home because it rained.", "translation": "Я остался дома, потому что шёл дождь."}],
    },
    {
        "language_code": "de", "word": "gehen", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "/ˈɡeːən/", "phonetic": "GAY-en", "difficulty": "beginner", "category": "daily_life",
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
        "pronunciation": "/ˈmaxən/", "phonetic": "MAKH-en", "difficulty": "beginner", "category": "daily_life",
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
        "pronunciation": "/ˈneːmən/", "phonetic": "NAY-men", "difficulty": "elementary", "category": "daily_life",
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
        "pronunciation": "/ˈhaːbən/", "phonetic": "HAH-ben", "difficulty": "beginner", "category": "daily_life",
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
        "pronunciation": "/tɛɐ̯ˈmiːn/", "phonetic": "ter-MEEN", "difficulty": "intermediate", "category": "health",
        "definition": "eine verabredete Zeit für ein Treffen",
        "translations": [{"language_code": "ru", "translation": "встреча, назначенное время"}],
        "examples": [{"example_text": "Ich habe morgen einen Termin.", "translation": "У меня завтра встреча."}],
    },
    {
        "language_code": "de", "word": "verbessern", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "/fɛɐ̯ˈbɛsɐn/", "phonetic": "fer-BES-ern", "difficulty": "intermediate", "category": "education",
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
        "pronunciation": "/ˈʊmvɛlt/", "phonetic": "OOM-velt", "difficulty": "intermediate", "category": "other",
        "definition": "die natürliche Welt um uns herum",
        "translations": [{"language_code": "ru", "translation": "окружающая среда"}],
        "examples": [{"example_text": "Wir müssen die Umwelt schützen.", "translation": "Мы должны защищать окружающую среду."}],
    },
    {
        "language_code": "de", "word": "Familie", "part_of_speech": "noun",
        "pronunciation": "/faˈmiːliə/", "phonetic": "fah-MEE-lyeh", "difficulty": "beginner", "category": "family",
        "definition": "eine Gruppe von Menschen, die verwandt sind",
        "translations": [{"language_code": "ru", "translation": "семья"}],
        "examples": [{"example_text": "Meine Familie wohnt in einer kleinen Stadt.", "translation": "Моя семья живёт в маленьком городе."}],
    },
    {
        "language_code": "de", "word": "Gesundheit", "part_of_speech": "noun",
        "pronunciation": "/ɡəˈzʊntˌhaɪt/", "phonetic": "guh-ZOONT-hite", "difficulty": "intermediate", "category": "health",
        "definition": "der Zustand, gesund zu sein",
        "translations": [{"language_code": "ru", "translation": "здоровье"}],
        "examples": [{"example_text": "Gesundheit ist wichtiger als Geld.", "translation": "Здоровье важнее денег."}],
    },
    {
        "language_code": "de", "word": "reisen", "part_of_speech": "verb", "is_verb": True,
        "pronunciation": "/ˈʁaɪzən/", "phonetic": "RY-zen", "difficulty": "beginner", "category": "travel",
        "definition": "von einem Ort zu einem anderen fahren",
        "translations": [{"language_code": "ru", "translation": "путешествовать"}],
        "examples": [{"example_text": "Sie reisen gern ins Ausland.", "translation": "Они любят путешествовать за границей."}],
        "forms": [
            {"form_type": "infinitiv", "form": "reisen"}, {"form_type": "präsens_ich", "form": "reise"},
            {"form_type": "präteritum", "form": "reiste"}, {"form_type": "partizip_ii", "form": "gereist"},
        ],
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
