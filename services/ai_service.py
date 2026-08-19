"""AI provider integration point (spec section 27).

AIService is the only interface handlers are allowed to depend on for
AI-backed features (word explanations, text analysis, grammar
explanations); the concrete provider is selected via
config.get_settings().ai_provider / ai_api_key and must never be called
directly from handlers.

TODO(stage-14): implement AIService against a real provider. Until then,
every method raises NotImplementedError so callers fail loudly instead of
returning fabricated content.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class AIService(ABC):
    @abstractmethod
    async def analyze_word(self, word: str, *, language_code: str) -> dict:
        """Meaning, part of speech, examples for a single word."""

    @abstractmethod
    async def explain_word(self, word: str, *, language_code: str) -> str:
        """Free-form usage explanation (spec section 17): context, collocations,
        examples, common mistakes."""

    @abstractmethod
    async def analyze_text(self, text: str, *, language_code: str) -> dict:
        """Translation + key vocabulary for a user-submitted text (section 18)."""

    @abstractmethod
    async def extract_learning_words(self, text: str, *, language_code: str) -> list[str]:
        """Candidate words worth adding to learning, extracted from text/OCR/speech output."""

    @abstractmethod
    async def explain_grammar(self, topic: str, *, language_code: str) -> str:
        """Short grammar explanation grounded in real words/sentences (section 21)."""


class NotConfiguredAIService(AIService):
    """Placeholder used while config.get_settings().ai_provider == "none".

    Fails clearly instead of silently returning fake AI output.
    """

    async def analyze_word(self, word: str, *, language_code: str) -> dict:
        raise NotImplementedError("AI provider not configured (see AI_PROVIDER in .env); arrives in Stage 14")

    async def explain_word(self, word: str, *, language_code: str) -> str:
        raise NotImplementedError("AI provider not configured (see AI_PROVIDER in .env); arrives in Stage 14")

    async def analyze_text(self, text: str, *, language_code: str) -> dict:
        raise NotImplementedError("AI provider not configured (see AI_PROVIDER in .env); arrives in Stage 14")

    async def extract_learning_words(self, text: str, *, language_code: str) -> list[str]:
        raise NotImplementedError("AI provider not configured (see AI_PROVIDER in .env); arrives in Stage 14")

    async def explain_grammar(self, topic: str, *, language_code: str) -> str:
        raise NotImplementedError("AI provider not configured (see AI_PROVIDER in .env); arrives in Stage 14")


def get_ai_service() -> AIService:
    """Factory selecting the configured AI provider. Only NotConfiguredAIService
    exists today; Stage 14 adds real provider classes here."""
    return NotConfiguredAIService()
