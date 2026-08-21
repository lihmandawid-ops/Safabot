"""AI integration point (spec: "Подключить AI как интеллектуальный слой
Safabot").

AIService is the ONLY interface anything else is allowed to depend on for
AI-backed features - handlers, DictionaryService, WordGenerationService
all call `get_ai_service()` and one of its methods, never
services/ai_provider.py directly and never build an HTTP request
themselves. The concrete provider (services/ai_provider.HttpAIProvider,
today's only implementation, OpenAI-compatible) is selected here from
config.get_settings(), so swapping providers later never touches a
caller.

Every public method either returns validated data (services/ai_models.py)
or raises a services.ai_errors.AIError subclass - never None, never a
raw dict, never a bare Exception. Callers decide the user-facing fallback
(local DB, a friendly message) for each error; this module's job stops at
"call the provider correctly, validate what comes back, log what
happened, without ever leaking the API key or a user's full text into a
log line".
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from functools import lru_cache
from typing import Callable, TypeVar

from pydantic import ValidationError

from services import ai_models
from services.ai_errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIError,
    AIInvalidResponseError,
    AIRateLimitedError,
    AIUnavailableError,
)
from services.ai_provider import AIProvider, HttpAIProvider
from utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class AIService(ABC):
    @abstractmethod
    async def lookup_word(
        self, word: str, *, language_code: str, translation_language: str,
        user_level: str | None = None, user_id: int,
    ) -> ai_models.WordAIResult:
        """Meaning, translations, part of speech, examples for a single
        word not found in the local dictionary (DictionaryService's AI
        fallback)."""

    @abstractmethod
    async def generate_words(
        self, *, language_code: str, translation_language: str, level: str, amount: int,
        category: str | None = None, known_words: list[str] | None = None, user_id: int,
    ) -> ai_models.GenerateWordsResult:
        """Up to `amount` new words the learner doesn't already know
        (WordGenerationService's AI fallback for the shortfall)."""

    @abstractmethod
    async def explain_word(
        self, word: str, *, language_code: str, translation_language: str,
        level: str, interface_language: str, user_id: int,
    ) -> str:
        """Free-form usage explanation: meanings, context, collocations,
        common mistakes, examples - level- and interface-language-aware."""

    @abstractmethod
    async def analyze_text(
        self, text: str, *, language_code: str, translation_language: str,
        interface_language: str, user_id: int,
    ) -> ai_models.TextAnalysisResult:
        """Translation + key vocabulary + useful phrases for a
        user-submitted text."""

    @abstractmethod
    async def explain_grammar(
        self, topic: str, *, language_code: str, level: str, interface_language: str, user_id: int,
    ) -> str:
        """Short grammar explanation grounded in real words/sentences."""

    @abstractmethod
    async def extract_learning_words(self, text: str, *, language_code: str, user_id: int) -> list[str]:
        """Candidate words worth adding to learning, extracted from
        text/OCR/speech output - the seam future OCR/voice stages plug
        into without a new AIService method."""


class NotConfiguredAIService(AIService):
    """Used whenever AI isn't usable: AI_ENABLED=false, or no AI_API_KEY
    set. Every method fails clearly and immediately (no network attempt,
    no rate-limit bookkeeping) so callers fall back to the local database
    instead of getting fabricated content or hanging.
    """

    async def lookup_word(self, word, *, language_code, translation_language, user_level=None, user_id):
        raise AIConfigurationError()

    async def generate_words(self, *, language_code, translation_language, level, amount, category=None, known_words=None, user_id):
        raise AIConfigurationError()

    async def explain_word(self, word, *, language_code, translation_language, level, interface_language, user_id):
        raise AIConfigurationError()

    async def analyze_text(self, text, *, language_code, translation_language, interface_language, user_id):
        raise AIConfigurationError()

    async def explain_grammar(self, topic, *, language_code, level, interface_language, user_id):
        raise AIConfigurationError()

    async def extract_learning_words(self, text, *, language_code, user_id):
        raise AIConfigurationError()


class _RateLimiter:
    """Basic in-process per-user request limiter (spec section 24) - not
    distributed/persisted, which is fine for a single bot process; a
    restart simply resets everyone's counters. `<=0` for either limit
    disables that dimension."""

    def __init__(self, *, per_minute: int, per_day: int) -> None:
        self._per_minute = per_minute
        self._per_day = per_day
        self._minute_calls: dict[int, deque[float]] = defaultdict(deque)
        self._day_calls: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> None:
        now = time.monotonic()

        if self._per_minute > 0:
            dq = self._minute_calls[user_id]
            while dq and now - dq[0] > 60:
                dq.popleft()
            if len(dq) >= self._per_minute:
                raise AIRateLimitedError(
                    f"Слишком много запросов к AI за минуту (лимит {self._per_minute}/мин). Подожди немного."
                )
            dq.append(now)

        if self._per_day > 0:
            dq = self._day_calls[user_id]
            while dq and now - dq[0] > 86400:
                dq.popleft()
            if len(dq) >= self._per_day:
                raise AIRateLimitedError(
                    f"Дневной лимит запросов к AI исчерпан (лимит {self._per_day}/день). Попробуй завтра."
                )
            dq.append(now)


# --- Prompts. Kept short and specific (spec section 26: "не отправлять в
# AI огромные контексты") - each asks for exactly one JSON shape, matching
# a services/ai_models.py model, and nothing else. ---

_LOOKUP_WORD_SYSTEM = (
    "You are a dictionary assistant for a language-learning app. Given a single word or short "
    "phrase, respond with ONLY a JSON object (no extra text) with this shape: "
    '{"word": str, "translations": [{"translation": str, "usage_note": str|null}], '
    '"part_of_speech": str|null, "phonetic": str|null, "pronunciation": str|null, '
    '"definition": str|null, "examples": [{"text": str, "translation": str|null}], '
    '"difficulty": str|null, "category": str|null, "verb_forms": object|null}. '
    "The input word or phrase may be written in EITHER the target language or the translation "
    "language - the user does not indicate which. Detect which language it's actually in "
    'yourself: if it is already in the target language, "word" is that same word (normalized to '
    "its dictionary/base form) and \"translations\" hold its meaning in the translation language. "
    'If it is written in the translation language instead, "word" MUST be the equivalent word in '
    'the target language (never the input as-is), and "translations" hold the original input '
    "(or its natural equivalents) back in the translation language - i.e. always return a "
    "target-language headword with translation-language translations, regardless of which "
    "language the input was actually typed in. "
    '"pronunciation" must be a phonetic transcription of the target-language "word" that a reader '
    "of the translation language can sound out using that language's own spelling conventions "
    "(not IPA, not a transcription system for a third language) - e.g. for an English word shown "
    "to a Russian speaker, write it out approximately in Cyrillic the way a Russian speaker would "
    "read it aloud. Always attempt a pronunciation rather than leaving it null unless the script "
    "makes this genuinely impossible - this field is shown to the learner directly, so it must "
    "almost never be null. "
    '"phonetic" is a SEPARATE, standard IPA transcription of the same word (e.g. "/ɡoʊ/") - always '
    "attempt it too when you can produce a real IPA transcription; leave it null only if you are "
    "not confident in the exact IPA symbols, never fill it with the same content as \"pronunciation\". "
    "verb_forms MUST be set whenever part_of_speech is \"verb\" - include every commonly-taught "
    "inflected form for that specific target language (do not force English's forms onto other "
    "languages, and do not invent a form you are not confident about, but do not omit the field "
    "entirely for a verb either)."
)

_GENERATE_WORDS_SYSTEM = (
    "You generate new vocabulary for a language-learning app. Respond with ONLY a JSON object: "
    '{"words": [ {"word": str, "translations": [{"translation": str, "usage_note": str|null}], '
    '"part_of_speech": str|null, "phonetic": str|null, "pronunciation": str|null, '
    '"definition": str|null, "examples": [{"text": str, "translation": str|null}], '
    '"difficulty": str|null, "category": str|null, "verb_forms": object|null}, ... ]}. '
    "Return exactly the requested amount of DISTINCT words the learner does not already know. "
    "Never repeat a word from the learner's known-words list. "
    'For each word, "pronunciation" must be a phonetic transcription using the translation '
    "language's own spelling conventions (not IPA) so the learner can sound it out directly - "
    'always attempt it, it is shown to the learner and must almost never be null. "phonetic" is a '
    "separate, standard IPA transcription of the same word - attempt it too when confident, leave "
    "it null otherwise, never duplicate \"pronunciation\" into it."
)

_EXPLAIN_SYSTEM = (
    "You are a language-learning assistant. Respond with ONLY a JSON object: "
    '{"explanation": str, "examples": [str]}. The explanation must be plain text (no markdown), '
    "written in the requested response language, at a level appropriate for the learner."
)

_ANALYZE_TEXT_SYSTEM = (
    "You analyze a short text for a language-learning app. Respond with ONLY a JSON object: "
    '{"original_text": str, "translation": str, '
    '"key_words": [{"word": str, "translation": str, "part_of_speech": str|null}], '
    '"difficulty": str|null, "useful_phrases": [str]}. '
    "key_words should list the words most worth learning from the text, in the order they appear."
)

_EXTRACT_WORDS_SYSTEM = (
    "Extract the words most worth adding to a language learner's vocabulary from this text. "
    'Respond with ONLY a JSON object: {"words": [str, ...]}, base/dictionary form, no duplicates.'
)


def _strip_markdown_fence(raw: str) -> str:
    """Some models occasionally wrap JSON-mode output in a ```json ... ```
    fence despite being told not to - cheap enough to always check for and
    strip before parsing, real-world defensive programming that costs
    nothing when the response is already clean."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


def _parse_json(raw: str) -> object:
    try:
        return json.loads(_strip_markdown_fence(raw))
    except json.JSONDecodeError as exc:
        raise AIInvalidResponseError("AI returned invalid JSON") from exc


def _parse_word_response(raw: str) -> ai_models.WordAIResult:
    payload = _parse_json(raw)
    try:
        return ai_models.WordAIResult.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected word schema") from exc


def _parse_generate_words_response(raw: str) -> ai_models.GenerateWordsResult:
    payload = _parse_json(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("words"), list):
        raise AIInvalidResponseError('AI response is missing a "words" list')

    words: list[ai_models.GeneratedWord] = []
    for item in payload["words"]:
        try:
            words.append(ai_models.GeneratedWord.model_validate(item))
        except ValidationError:
            # One malformed entry must not cost the rest of an otherwise
            # valid batch (spec section 12/6).
            continue
    return ai_models.GenerateWordsResult(words=words)


def _parse_explanation_response(raw: str) -> ai_models.GrammarExplanation:
    payload = _parse_json(raw)
    try:
        return ai_models.GrammarExplanation.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected explanation schema") from exc


def _format_explanation(result: ai_models.GrammarExplanation) -> str:
    if not result.examples:
        return result.explanation
    examples = "\n".join(f"- {example}" for example in result.examples)
    return f"{result.explanation}\n\n{examples}"


def _parse_word_list_response(raw: str) -> list[str]:
    payload = _parse_json(raw)
    words = payload.get("words") if isinstance(payload, dict) else None
    if not isinstance(words, list):
        raise AIInvalidResponseError('AI response is missing a "words" list')
    return [w.strip() for w in words if isinstance(w, str) and w.strip()]


def _parse_text_analysis_response(raw: str) -> ai_models.TextAnalysisResult:
    payload = _parse_json(raw)
    try:
        return ai_models.TextAnalysisResult.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected text-analysis schema") from exc


class LiveAIService(AIService):
    """Real implementation: builds a prompt per operation, calls the
    configured AIProvider with a bounded retry, validates the result, and
    logs the attempt - all before any caller sees the data."""

    def __init__(
        self, *, provider: AIProvider, model: str, provider_label: str,
        max_retries: int, requests_per_minute: int, requests_per_day: int,
    ) -> None:
        self._provider = provider
        self._model = model
        self._provider_label = provider_label
        self._max_retries = max(0, max_retries)
        self._rate_limiter = _RateLimiter(per_minute=requests_per_minute, per_day=requests_per_day)

    async def lookup_word(self, word, *, language_code, translation_language, user_level=None, user_id):
        user = (
            f"Word or phrase: {word!r}\n"
            f"Target language code (ISO 639-1): {language_code}\n"
            f"Translate into language code: {translation_language}\n"
            f"Learner level: {user_level or 'unknown'}\n"
        )
        return await self._complete("lookup_word", user_id, _LOOKUP_WORD_SYSTEM, user, _parse_word_response)

    async def generate_words(self, *, language_code, translation_language, level, amount, category=None, known_words=None, user_id):
        known = ", ".join((known_words or [])[:200])
        user = (
            f"Language being learned (ISO 639-1): {language_code}\n"
            f"Translate into language code: {translation_language}\n"
            f"Learner level: {level}\n"
            f"Category: {category or 'any suitable for everyday use'}\n"
            f"Exact amount of new distinct words to return: {amount}\n"
            f"Words the learner already knows - never repeat any of these: {known or 'none'}\n"
        )
        return await self._complete("generate_words", user_id, _GENERATE_WORDS_SYSTEM, user, _parse_generate_words_response)

    async def explain_word(self, word, *, language_code, translation_language, level, interface_language, user_id):
        user = (
            f"Word: {word!r}\n"
            f"Target language code: {language_code}\n"
            f"Translate into language code: {translation_language}\n"
            f"Learner level: {level}\n"
            f"Respond in this language (ISO 639-1): {interface_language}\n"
            "This will be shown as a short chat message, not an article - keep it VERY brief: "
            "at most one short sentence covering the single most useful thing to know (the most "
            "important nuance, a common mistake, or a typical collocation - whichever matters "
            "most for this word), plus at most one short example if it fits. Do not try to cover "
            "every meaning or list multiple points."
        )
        result = await self._complete("explain_word", user_id, _EXPLAIN_SYSTEM, user, _parse_explanation_response)
        return _format_explanation(result)

    async def analyze_text(self, text, *, language_code, translation_language, interface_language, user_id):
        user = (
            f"Text (language code {language_code}):\n{text}\n\n"
            f"Translate into language code: {translation_language}\n"
            f"Respond in this language for any prose (ISO 639-1): {interface_language}\n"
        )
        return await self._complete("analyze_text", user_id, _ANALYZE_TEXT_SYSTEM, user, _parse_text_analysis_response)

    async def explain_grammar(self, topic, *, language_code, level, interface_language, user_id):
        user = (
            f"Grammar question about language {language_code}: {topic}\n"
            f"Learner level: {level}\n"
            f"Respond in this language (ISO 639-1): {interface_language}\n"
        )
        result = await self._complete("explain_grammar", user_id, _EXPLAIN_SYSTEM, user, _parse_explanation_response)
        return _format_explanation(result)

    async def extract_learning_words(self, text, *, language_code, user_id):
        user = f"Text (language code {language_code}):\n{text}\n"
        return await self._complete("extract_learning_words", user_id, _EXTRACT_WORDS_SYSTEM, user, _parse_word_list_response)

    async def _complete(self, operation: str, user_id: int, system: str, user: str, parse: Callable[[str], T]) -> T:
        """Runs one operation end-to-end (network call + parse/validate)
        inside the retry loop, so a malformed/invalid response (spec
        section 21's "malformed JSON") gets retried exactly like a
        network hiccup would - parsing failures aren't network errors,
        but they're just as transient in practice (a re-asked model often
        gets the shape right the second time), and it would defeat the
        point of MAX_AI_RETRIES to only cover the transport half of the
        call."""
        self._rate_limiter.check(user_id)

        max_tries = self._max_retries + 1
        last_error: AIError | None = None
        for attempt in range(1, max_tries + 1):
            start = time.monotonic()
            try:
                raw = await self._provider.complete(system=system, user=user)
                result = parse(raw)
            except AIAuthenticationError as exc:
                self._log(operation, user_id, start, "error", exc)
                raise  # bad key - retrying changes nothing (spec section 22)
            except AIError as exc:
                last_error = exc
                is_last = attempt == max_tries
                self._log(operation, user_id, start, "error" if is_last else "retry", exc)
                if is_last:
                    raise
                continue
            else:
                self._log(operation, user_id, start, "success", None)
                return result
        raise last_error or AIUnavailableError("AI request failed")

    def _log(self, operation: str, user_id: int, start: float, outcome: str, exc: AIError | None) -> None:
        # Deliberately: no prompt/response content, no API key - only
        # metadata (spec section 25).
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if exc is None:
            logger.info(
                "AI call operation=%s user_id=%s provider=%s model=%s elapsed_ms=%d outcome=%s",
                operation, user_id, self._provider_label, self._model, elapsed_ms, outcome,
            )
        else:
            logger.warning(
                "AI call operation=%s user_id=%s provider=%s model=%s elapsed_ms=%d outcome=%s error=%s",
                operation, user_id, self._provider_label, self._model, elapsed_ms, outcome, type(exc).__name__,
            )


@lru_cache(maxsize=1)
def get_ai_service() -> AIService:
    """Factory selecting the configured AI backend. Cached like
    config.get_settings() - call get_ai_service.cache_clear() after
    changing AI-related environment variables mid-process (tests only;
    the real bot reads .env once at startup)."""
    from config import get_settings

    settings = get_settings()
    if not settings.ai_enabled or not settings.ai_api_key:
        return NotConfiguredAIService()

    provider = HttpAIProvider(
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        base_url=settings.ai_base_url,
        timeout=settings.ai_timeout_seconds,
    )
    return LiveAIService(
        provider=provider,
        model=settings.ai_model,
        provider_label=settings.ai_provider,
        max_retries=settings.max_ai_retries,
        requests_per_minute=settings.ai_requests_per_minute,
        requests_per_day=settings.ai_requests_per_day,
    )
