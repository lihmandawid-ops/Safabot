"""💬 Полезные фразы situation categories (native-speaker phrasebook
stage, section 4): 14 presets plus a "🎯 Своя ситуация" free-text entry
handled separately by the handler (not a code in this list, since it
isn't itself a situation - it's the trigger for typing one).

Labels live in locale files under "phrase_situation.<code>", same
pattern utils/topics.py's PRESET_TOPICS and the industry picker already
use - so a category is never hardcoded to one language.
"""
from __future__ import annotations

PRESET_SITUATIONS: tuple[str, ...] = (
    "work",
    "shopping",
    "restaurant",
    "travel",
    "hotel",
    "transport",
    "meeting",
    "daily_life",
    "socializing",
    "phone",
    "doctor",
    "bank",
    "study",
    "customer_service",
)

MAX_CUSTOM_SITUATION_LENGTH = 200
