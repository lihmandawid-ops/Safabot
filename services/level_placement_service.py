"""🤖 Узнать мой уровень (real user request): a short AI-graded placement
test that replaces the old "Автоматически" difficulty setting - instead
of passively tracking level over time, the learner answers 6 questions
right now (self-report word recognition + sentence translation, one per
CEFR tier a1..c2) and the AI itself decides the resulting level.

services.ai_service does the actual AI calls and validates their shape;
this module only turns that into the plain dicts handlers/settings.py's
multi-question context.user_data state needs, and back again for
grading - same "AIError bubbles up, the handler decides the user-facing
fallback" convention every other AI-backed flow in this codebase
follows (see services/phrase_service.py, services/word_generation_service.py).
"""
from __future__ import annotations

from database.models import UserLanguage
from services.ai_service import get_ai_service


async def start_placement_test(user_language: UserLanguage, *, user_id: int) -> list[dict]:
    """Returns exactly 6 plain dicts ({"level", "kind", "prompt"}, in
    a1..c2 order - see ai_models.PlacementTestResult), ready to store in
    context.user_data["placement_test"]["questions"] as-is."""
    result = await get_ai_service().generate_placement_test(
        language_code=user_language.language_code,
        translation_language=user_language.translation_language,
        user_id=user_id,
    )
    return [{"level": q.level, "kind": q.kind, "prompt": q.prompt} for q in result.questions]


async def grade_placement_test(
    user_language: UserLanguage, questions: list[dict], answers: list[str], *, user_id: int,
) -> str:
    """`answers` must be the same length and order as `questions` - one
    answer string per question ("yes"/"no" for a "word" question, the
    learner's translation attempt or a "can't do it" statement for a
    "translate" one). Returns the AI's own determined CEFR code."""
    transcript = [{**question, "answer": answer} for question, answer in zip(questions, answers)]
    result = await get_ai_service().grade_placement_test(
        language_code=user_language.language_code,
        translation_language=user_language.translation_language,
        transcript=transcript,
        user_id=user_id,
    )
    return result.level
