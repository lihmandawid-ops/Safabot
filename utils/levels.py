"""The CEFR proficiency levels Safabot tracks (level-and-difficulty stage).

Both onboarding (handlers/start.py) and Settings (handlers/settings.py)
import from here so the level list and its labels never drift apart.

Replaces the earlier 5-tier custom scale (beginner/elementary/
intermediate/upper_intermediate/advanced) with the standard 6-tier CEFR
scale, per the explicit requirement to use CEFR as the base. LEGACY_LEVEL_MAP
is the one-time migration mapping (old code -> new code) used by the
database migration that rewrote every existing User.level/UserLanguage.level/
Word.difficulty value - kept here, not duplicated in the migration file,
so the mapping only ever lives in one place.
"""
from __future__ import annotations

LEVELS: tuple[tuple[str, str], ...] = (
    ("a1", "🟢 A1 — Начальный"),
    ("a2", "🟡 A2 — Элементарный"),
    ("b1", "🟠 B1 — Средний"),
    ("b2", "🔵 B2 — Выше среднего"),
    ("c1", "🔴 C1 — Продвинутый"),
    ("c2", "🟣 C2 — Свободное владение"),
)

LEVEL_LABELS: dict[str, str] = dict(LEVELS)
LEVEL_CODES: tuple[str, ...] = tuple(code for code, _ in LEVELS)

# One CEFR tier below the next in this exact order - LevelProgressService
# (services/level_progress_service.py) only ever advances one step at a
# time along this sequence, never jumps.
LEVEL_ORDER: tuple[str, ...] = LEVEL_CODES

LEGACY_LEVEL_MAP: dict[str, str] = {
    "beginner": "a1",
    "elementary": "a2",
    "intermediate": "b1",
    "upper_intermediate": "b2",
    "advanced": "c1",
    # "c2" has no prior equivalent - only reachable via LevelProgressService
    # or an explicit manual pick from now on.
}


def is_valid_level(code: str) -> bool:
    return code in LEVEL_LABELS


def next_level(code: str) -> str | None:
    """The single next CEFR tier after `code`, or None if already at the
    top (c2) or `code` isn't recognized."""
    try:
        index = LEVEL_ORDER.index(code)
    except ValueError:
        return None
    if index + 1 >= len(LEVEL_ORDER):
        return None
    return LEVEL_ORDER[index + 1]
