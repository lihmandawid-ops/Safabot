"""🎯 Темы обучения (settings-improvements stage sections 17-19, 22).

Preset topics deliberately reuse the exact same vocabulary as
Word.category (see database/seed_words.py and AI-generated words'
`category` field) rather than inventing a second categorization scheme -
this is what lets word_generation_service prefer LOCAL words whose
category matches a selected topic, not just bias the AI prompt. A user
can also add a custom free-text topic (handlers/settings.py); those only
ever reach the AI prompt, since no local Word.category will match an
arbitrary string, and that's fine - the AI-generation path already
tolerates additional criteria find_unknown_words_for_generation itself
never sees. Labels for preset topics live in locale files under
"topic.<code>"; custom topics are shown as their own raw text.
"""
from __future__ import annotations

PRESET_TOPICS: tuple[str, ...] = (
    "daily_life",
    "business",
    "work",
    "travel",
    "family",
    "food",
    "health",
    "education",
    "technology",
    "transport",
)

MAX_SELECTED_TOPICS = 8
MAX_CUSTOM_TOPIC_LENGTH = 40
