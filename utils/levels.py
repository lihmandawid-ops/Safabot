"""The 5 proficiency levels Safabot tracks (spec section 7), in one place.

Both onboarding (handlers/start.py) and Settings (handlers/settings.py)
import from here so the level list and its labels never drift apart.
"""
from __future__ import annotations

LEVELS: tuple[tuple[str, str], ...] = (
    ("beginner", "🟢 Начальный"),
    ("elementary", "🟡 Элементарный"),
    ("intermediate", "🟠 Средний"),
    ("upper_intermediate", "🔵 Выше среднего"),
    ("advanced", "🔴 Продвинутый"),
)

LEVEL_LABELS: dict[str, str] = dict(LEVELS)
LEVEL_CODES: tuple[str, ...] = tuple(code for code, _ in LEVELS)


def is_valid_level(code: str) -> bool:
    return code in LEVEL_LABELS
