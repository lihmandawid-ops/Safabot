"""Preset work industries offered when learning_goal == "work" (settings-
improvements stage section 20). A user whose field isn't listed can
still type it in free text (handlers/start.py and handlers/settings.py's
"other" flow) - work_industry is a free String(64) column, never
constrained to this list at the database level, only offered as a
shortcut in the UI. Labels live in locale files under "industry.<code>".
"""
from __future__ import annotations

PRESET_INDUSTRIES: tuple[str, ...] = (
    "it",
    "healthcare",
    "education",
    "finance",
    "hospitality",
    "retail",
    "engineering",
    "legal",
    "marketing",
    "manufacturing",
)
