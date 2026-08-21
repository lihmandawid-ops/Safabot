"""Why a user is learning a given language (settings-improvements stage
sections 18-21). Labels live in locale files under "goal.<code>" (same
pattern as utils/levels.py's LEVEL_CODES), never hardcoded here.

learning_goal == "work" is the one value with a special onboarding
consequence: it triggers a follow-up work-industry question (see
utils/industries.py) so word_generation_service can bias generated
vocabulary toward that industry.
"""
from __future__ import annotations

GOAL_CODES: tuple[str, ...] = ("general", "work", "travel", "study", "family")


def is_valid_goal(code: str | None) -> bool:
    return code in GOAL_CODES
