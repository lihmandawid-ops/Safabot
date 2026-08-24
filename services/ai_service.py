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
from services.ai_provider import AIProvider, FallbackAIProvider, HttpAIProvider
from utils.logging import get_logger
from utils.phrase_situations import PRESET_SITUATIONS
from utils.text import normalize_word

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
        category: str | None = None, industry: str | None = None, goal: str | None = None,
        known_words: list[str] | None = None, user_id: int,
    ) -> ai_models.GenerateWordsResult:
        """Up to `amount` new words the learner doesn't already know
        (WordGenerationService's AI fallback for the shortfall, and the
        AI-first path behind 🆕 Новые слова / 🎯 Новые слова по теме -
        spec sections 40-58). `category` carries the user's selected
        topics/interests (settings-improvements stage section 22: "🎯 Темы
        обучения"); `industry` is only ever set when the user's
        learning_goal is "work" (section 20); `goal` is that same
        learning_goal itself (e.g. "travel", "work", "study") so the AI
        can bias vocabulary toward it even outside the "work" case."""

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

    @abstractmethod
    async def generate_verb_conjugation(
        self, word: str, *, language_code: str, translation_language: str, user_id: int,
    ) -> ai_models.VerbConjugationResult:
        """🔤 Все формы (repetition-system stage sections 18-25; bidirectional-
        dictionary stage sections 14-18): a full conjugation table using
        whatever tense/mood structure is natural for `language_code`'s own
        grammar - never English's four tenses forced onto another language.
        Each form also carries a grammatical-person label and its own
        translation, both written in `translation_language` (never
        interface_language). Callers (services/verb_forms_service.py) cache
        the result on Word.verb_conjugation, scoped per translation_language
        since the label/translation text is native-language-dependent."""

    @abstractmethod
    async def generate_native_phrase(
        self, *, language_code: str, translation_language: str, level: str, situation: str,
        industry: str | None = None, topics: list[str] | None = None,
        exclude_phrases: list[str] | None = None, user_id: int,
    ) -> ai_models.NativePhraseResult:
        """💬 Полезные фразы (native-speaker phrasebook stage, sections
        6-13): ONE natural phrase a real native speaker of language_code
        would actually say in `situation` - never a literal translation of
        a fixed sentence. `exclude_phrases` backs 🔄 Другая фраза (never
        the exact same text twice in a row)."""

    @abstractmethod
    async def translate_phrases(
        self, phrases: list[str], *, language_code: str, translation_language: str, user_id: int,
    ) -> list[str]:
        """🔥 Популярные фразы' translation cache (native-speaker
        phrasebook stage bugfix): translates the WHOLE given batch of
        target-language phrases into translation_language in ONE call,
        same order - services/phrase_service.py calls this at most once
        per (language_code, translation_language) pair, ever, caching the
        result so no later view or page ever needs a live call again."""

    @abstractmethod
    async def generate_popular_phrases(
        self, *, language_code: str, translation_language: str, level: str, amount: int = 8,
        category: str | None = None, industry: str | None = None, topics: list[str] | None = None,
        known_phrases: list[str] | None = None, user_id: int,
    ) -> ai_models.PopularPhraseBatchResult:
        """✨ Сгенерировать ещё (native-speaker phrasebook stage): a fresh
        batch of `amount` natural, native-speaker phrases for
        language_code in ONE call - never one request per phrase.
        `known_phrases` is what services/phrase_service.py asks the AI to
        avoid repeating; the real duplicate guarantee is still the DB
        check in database.repositories.popular_phrases, since this list
        is only ever a bounded sample, never the whole table."""

    @abstractmethod
    async def generate_placement_test(
        self, *, language_code: str, translation_language: str, user_id: int,
    ) -> ai_models.PlacementTestResult:
        """🤖 Узнать мой уровень (real user request): 6 items, one per
        CEFR tier a1..c2 in order, alternating self-report word-
        recognition and sentence-translation questions - see
        ai_models.PlacementQuestion for the exact shape each item takes."""

    @abstractmethod
    async def grade_placement_test(
        self, *, language_code: str, translation_language: str,
        transcript: list[dict[str, str]], user_id: int,
    ) -> ai_models.PlacementLevelResult:
        """Reads the full placement-test transcript (one dict per
        question: level/kind/prompt/answer, same order as generated) and
        returns the AI's own best-estimate CEFR level - the single
        source of truth for where the learner actually lands, not a
        locally-computed score."""


class NotConfiguredAIService(AIService):
    """Used whenever AI isn't usable: AI_ENABLED=false, or no AI_API_KEY
    set. Every method fails clearly and immediately (no network attempt,
    no rate-limit bookkeeping) so callers fall back to the local database
    instead of getting fabricated content or hanging.
    """

    async def lookup_word(self, word, *, language_code, translation_language, user_level=None, user_id):
        raise AIConfigurationError()

    async def generate_words(self, *, language_code, translation_language, level, amount, category=None, industry=None, goal=None, known_words=None, user_id):
        raise AIConfigurationError()

    async def explain_word(self, word, *, language_code, translation_language, level, interface_language, user_id):
        raise AIConfigurationError()

    async def analyze_text(self, text, *, language_code, translation_language, interface_language, user_id):
        raise AIConfigurationError()

    async def explain_grammar(self, topic, *, language_code, level, interface_language, user_id):
        raise AIConfigurationError()

    async def extract_learning_words(self, text, *, language_code, user_id):
        raise AIConfigurationError()

    async def generate_verb_conjugation(self, word, *, language_code, translation_language, user_id):
        raise AIConfigurationError()

    async def generate_native_phrase(self, *, language_code, translation_language, level, situation, industry=None, topics=None, exclude_phrases=None, user_id):
        raise AIConfigurationError()

    async def translate_phrases(self, phrases, *, language_code, translation_language, user_id):
        raise AIConfigurationError()

    async def generate_popular_phrases(self, *, language_code, translation_language, level, amount=8, category=None, industry=None, topics=None, known_phrases=None, user_id):
        raise AIConfigurationError()

    async def generate_placement_test(self, *, language_code, translation_language, user_id):
        raise AIConfigurationError()

    async def grade_placement_test(self, *, language_code, translation_language, transcript, user_id):
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
    "You are a dictionary assistant for a language-learning app - a genuinely BIDIRECTIONAL "
    "dictionary between the learner's learning_language (the target language code given below) "
    "and their native_language (the translation language code given below; the app's interface "
    "language is a SEPARATE, unrelated setting and must never influence anything you output). "
    "Given a single word or short phrase, respond with ONLY a JSON object (no extra text) with "
    'this shape: {"query_language": str, "word": str, "translations": [{"translation": str, '
    '"usage_note": str|null}], "part_of_speech": str|null, "phonetic": str|null, "pronunciation": '
    'str|null, "definition": str|null, "examples": [{"text": str, "translation": str|null, '
    '"pronunciation": str|null}], "difficulty": str|null, "category": str|null, '
    '"verb_forms": object|null}. '
    "The input word or phrase may be written in EITHER learning_language or native_language - the "
    "user does not indicate which. Detect which one it's actually in yourself and report your "
    'decision as "query_language" (the ISO 639-1 code of learning_language or native_language, '
    "exactly one of the two, never a third language): if the input is already in learning_language, "
    '"word" is that same word (normalized to its dictionary/base form) and "translations" hold its '
    "meaning in native_language. If the input is written in native_language instead, \"word\" MUST "
    "be the equivalent word in learning_language (never the input left as-is or merely transliterated "
    '- it must be a real translation), and "translations" hold the original input (or its natural '
    "equivalents) back in native_language - i.e. always return a learning_language headword with "
    "native_language translations, regardless of which language the input was actually typed in. "
    '"translations", "usage_note", "definition", and every example "translation" MUST ALL be written '
    "in native_language - never in English or Russian unless that IS native_language; never leave the "
    "learner an explanation in the wrong language. If the word has multiple common, genuinely "
    'distinct senses (e.g. "bank" = financial institution vs. river bank), return one entry per '
    'sense in "translations" rather than picking only one; keep it to the few most useful senses '
    "for a learner, never an exhaustive dictionary entry. When the word is used differently across "
    'common contexts, use "usage_note" on the relevant translation entries to explain each context '
    "briefly, in native_language. "
    '"pronunciation" must be a phonetic transcription of the learning_language "word" that a reader '
    "of native_language can sound out using that language's own spelling conventions (not IPA, not "
    "a transcription system for a third language) - e.g. for an English word shown to a Russian "
    "speaker, write it out approximately in Cyrillic the way a Russian speaker would read it aloud. "
    "Always attempt a pronunciation rather than leaving it null unless the script makes this "
    "genuinely impossible - this field is shown to the learner directly, so it must almost never be "
    "null. "
    '"phonetic" is a SEPARATE, standard IPA transcription of the same word (e.g. "/ɡoʊ/") - always '
    "attempt it too when you can produce a real IPA transcription; leave it null only if you are "
    "not confident in the exact IPA symbols, never fill it with the same content as \"pronunciation\". "
    "Each example sentence's own \"pronunciation\" must be the same kind of readable transcription "
    "but for the WHOLE sentence, not just the headword - always attempt it too, for the same reason. "
    "verb_forms MUST be set whenever part_of_speech is \"verb\" - include every commonly-taught "
    "inflected form for that specific learning_language (do not force English's forms onto other "
    "languages, and do not invent a form you are not confident about, but do not omit the field "
    "entirely for a verb either)."
)

_GENERATE_WORDS_SYSTEM = (
    "You generate new vocabulary for a language-learning app. Respond with ONLY a JSON object: "
    '{"words": [ {"word": str, "translations": [{"translation": str, "usage_note": str|null}], '
    '"part_of_speech": str|null, "phonetic": str|null, "pronunciation": str|null, '
    '"definition": str|null, "examples": [{"text": str, "translation": str|null, '
    '"pronunciation": str|null}], "difficulty": str|null, "category": str|null, '
    '"verb_forms": object|null}, ... ]}. '
    "Return exactly the requested amount of DISTINCT words the learner does not already know. "
    "Never repeat a word from the learner's known-words list. "
    "The \"Category/topic\" line may be a free-text theme, not just a fixed label - genuinely "
    "interpret its real-world meaning and relevant subtopics (e.g. \"job interview\" implies "
    "vocabulary for qualifications, salary negotiation, and self-presentation, not just the literal "
    "phrase) and pick words a learner pursuing it would actually need, factoring in the stated goal "
    "and industry too when given. "
    'For each word, "pronunciation" must be a phonetic transcription using the translation '
    "language's own spelling conventions (not IPA) so the learner can sound it out directly - "
    'always attempt it, it is shown to the learner and must almost never be null. "phonetic" is a '
    "separate, standard IPA transcription of the same word - attempt it too when confident, leave "
    "it null otherwise, never duplicate \"pronunciation\" into it. Each example sentence's own "
    "\"pronunciation\" must be the SAME kind of readable transcription (translation language's own "
    "spelling conventions, not IPA) but for the WHOLE example sentence, not just the headword - "
    "always attempt it too, for the same reason. "
    "\"translations\"/\"usage_note\"/\"definition\"/example \"translation\" must ALL be written in "
    "the translate-into language given below - never in English or Russian unless that IS the "
    "translate-into language."
)

_EXPLAIN_SYSTEM = (
    "You are a language-learning assistant. Respond with ONLY a JSON object: "
    '{"explanation": str, "examples": [str]}. The explanation must be plain text (no markdown), '
    "written in the requested response language, at a level appropriate for the learner."
)

_ANALYZE_TEXT_SYSTEM = (
    "You analyze a short text for a language-learning app. Respond with ONLY a JSON object: "
    '{"original_text": str, "translation": str, "pronunciation": str|null, '
    '"key_words": [{"word": str, "translation": str, "part_of_speech": str|null, "pronunciation": str|null}], '
    '"difficulty": str|null, "useful_phrases": [{"phrase": str, "pronunciation": str|null}]}. '
    "key_words should list the words most worth learning from the text, in the order they appear. "
    'The top-level "pronunciation" is a phonetic transcription of the WHOLE original_text, and each '
    'key word\'s and each useful_phrase\'s own "pronunciation" is a transcription of just that word '
    "or phrase - ALWAYS of the TARGET-language text itself (original_text/the key word/the useful "
    "phrase), NEVER of its translation. Every \"pronunciation\" value MUST be written using LATIN "
    "LETTERS ONLY - a simple, readable Latin transliteration, never Cyrillic, Hebrew, or any other "
    "non-Latin script, and never IPA - regardless of what script the translation language itself "
    "uses, so it stays readable no matter which language the learner's interface is in. A "
    '"pronunciation" value must never be identical to, or a rephrasing of, the translation text - '
    "it represents SOUND, not meaning; if you find yourself writing something that reads like a "
    "translation rather than a sound-it-out guide, that is wrong. Always attempt a pronunciation "
    "for the whole text, for every key word, and for every useful phrase, rather than leaving it "
    "null, unless the script makes this genuinely impossible - these fields are shown to the "
    "learner directly."
)

_EXTRACT_WORDS_SYSTEM = (
    "Extract the words most worth adding to a language learner's vocabulary from this text. "
    'Respond with ONLY a JSON object: {"words": [str, ...]}, base/dictionary form, no duplicates.'
)

_VERB_CONJUGATION_SYSTEM = (
    "You produce a full conjugation table for a single verb, for a language-learning app. "
    'Respond with ONLY a JSON object: {"word": str, "language": str, "forms": object}. '
    '"forms" maps a tense/mood name to a list of {"form": str, "pronunciation": str|null, '
    '"person_label": str|null, "translation": str|null} objects - one per grammatical person '
    "that language actually distinguishes. The tense/mood names you choose, and how many of "
    "them you return, MUST reflect how THIS language's own grammar actually organizes its verb "
    "system - do not force English's four tenses (present/past/future/perfect) onto a language "
    "that categorizes verbs differently (for example, use German's own Präsens/Präteritum/"
    "Perfekt/Futur, or Russian's aspect-based present/past/future, or whatever a native grammar "
    "reference for that language would use). Each list must contain one row per grammatical "
    "person that language actually distinguishes (do not pad to exactly six English-style "
    "persons for a language that has fewer or more, and do not force a gender split where the "
    "language's own teaching materials would combine two genders on one row instead) - include "
    "the subject pronoun in each form exactly the way that language normally states it (e.g. "
    '"I am", not just "am"; omit the pronoun only if the language\'s own conjugated verb form '
    "already fully identifies the person, e.g. many null-subject languages). "
    '"person_label" is that row\'s grammatical person written out IN THE NATIVE/TRANSLATION '
    'LANGUAGE given below (e.g. "Я"/"Ты"/"Он"/"Она"/"Мы"/"Вы"/"Они" for a Russian native '
    "language, grouped and gendered however is natural for that person's real grammar - never "
    "the same fixed six-row scheme for every learning language. "
    '"translation" is that ONE specific conjugated form\'s own meaning, translated into the '
    "native/translation language - never left the same for every row, since different persons "
    "of the same verb translate differently. Both person_label and translation must ALWAYS be "
    "written in the native/translation language, never in the learning language, and never left "
    "in English or Russian unless that IS the native/translation language. "
    "Each form's own \"pronunciation\" is a readable phonetic transcription (not IPA) of just "
    "THAT conjugated form specifically - not the infinitive's pronunciation reused for every "
    "row, since conjugated forms often sound different from each other - written so a learner "
    "can sound it out directly. Always attempt one per form, leave it null only when the script "
    "makes this genuinely impossible."
)


_NATIVE_PHRASE_SYSTEM = (
    "You are a native speaker of the target language helping a language learner with a real "
    "everyday situation. Respond with ONLY a JSON object: "
    '{"language": str, "phrase": str, "translation": str, "pronunciation": str|null, '
    '"register": str|null, "naturalness": str|null, "situation": str|null, '
    '"explanation": str|null, "alternative": str|null}. '
    '"language" MUST be the target language\'s ISO 639-1 code, exactly as given below. '
    "\n\n"
    "CRITICAL - this is a native-speaker phrase generator, NOT a translator: your task is to "
    "produce the phrase a real native speaker of the target language would ACTUALLY SAY in the "
    "given situation - never a literal, word-for-word translation of any fixed source sentence "
    "in another language. Do not think 'how do I translate X' - think 'what would a native "
    "speaker naturally say here'. Do not use an artificial textbook construction when real "
    "native speakers would normally phrase it differently in everyday life. "
    "\n\n"
    "When several natural phrasings exist for the situation, prioritize in this exact order: "
    "(1) naturalness - how a real native speaker actually talks, (2) how common/widespread the "
    "phrasing is, (3) fit for the specific situation given, (4) fit for the learner's level, "
    "(5) grammatical correctness. If multiple options tie on naturalness and commonness, pick "
    "the single most common, neutral one - do not return multiple options unless the caller "
    "explicitly asks for alternatives elsewhere. "
    "\n\n"
    "Regional/variant guidance: prefer modern, natural, widely-understood usage for the target "
    "language over dated or overly formal/bookish phrasing, unless the situation specifically "
    "calls for formality. For English, default to modern international English unless a region "
    "is otherwise indicated. For Hebrew specifically, use MODERN COLLOQUIAL ISRAELI HEBREW as "
    "actually spoken day to day - not a purely formal grammatical construction - whenever "
    "everyday spoken Hebrew would phrase it more naturally; this matters more for Hebrew than "
    "for most other languages. "
    "\n\n"
    "Adapt complexity to the learner's level: a beginner gets a short, simple phrase; an "
    "elementary learner gets a simple everyday expression; an intermediate learner gets a "
    "natural conversational phrase; an upper-intermediate or advanced learner can get a more "
    "sophisticated, idiomatic, or professional/field-specific expression when that fits the "
    "situation. Never hand a beginner a complex idiom just because it's popular. "
    "\n\n"
    '"pronunciation" is a readable Latin-letter phonetic transcription (never IPA, never the '
    "translation language's native script) so the learner can sound the phrase out directly - "
    "always attempt one unless the script makes it genuinely impossible. "
    '"register" is a short tag like "casual"/"neutral"/"polite"/"formal". "explanation" is one '
    "short sentence (in the requested response language) on when/how this phrase is used - "
    "especially important for idiomatic expressions whose literal words don't convey the actual "
    'meaning. "alternative" is one other natural phrasing for the same situation, or null if '
    "there isn't a meaningfully different common one."
)

_TRANSLATE_PHRASES_SYSTEM = (
    "You translate a numbered list of short target-language phrases for a language-learning "
    'app. Respond with ONLY a JSON object: {"translations": [str, ...]}. The array MUST have '
    "EXACTLY the same number of items, in the EXACT same order, as the numbered phrases given "
    "below - one natural, idiomatic translation per phrase (not an overly literal word-for-word "
    "translation). Never add, merge, split, skip, or reorder entries - every input phrase gets "
    "exactly one output translation at the same position."
)

_POPULAR_PHRASES_SYSTEM = (
    "You are a native speaker of the target language creating a batch of common, useful, "
    "everyday phrases for a language-learning app. Respond with ONLY a JSON object: "
    '{"phrases": [{"phrase": str, "translation": str, "pronunciation": str|null, '
    '"category": str|null}, ...]}. Generate the EXACT requested amount of DISTINCT phrases '
    "(fewer only if you genuinely cannot find that many that satisfy every rule below). "
    "\n\n"
    "CRITICAL - same native-speaker rule as everywhere else in this app: each phrase must be "
    "something a real native speaker would actually say - never a literal, word-for-word "
    "translation of a fixed sentence in another language. Prioritize naturalness and how "
    "commonly the phrase is actually used in real everyday life over textbook-style phrasing. "
    "\n\n"
    "Never repeat any phrase already in the learner's existing list, given below - if a natural "
    "option would overlap with one of those, generate a genuinely different phrase instead of a "
    "trivial reword of an existing one (e.g. not just swapping 'Hello' for 'Hi' if 'Hello' is "
    "already there). "
    "\n\n"
    "Adapt complexity to the learner's level: a beginner/elementary learner gets short, simple "
    "everyday phrases; an intermediate learner gets natural conversational phrases; an "
    "upper-intermediate or advanced learner can get more idiomatic or field-specific phrases "
    "when relevant. "
    "\n\n"
    '"pronunciation" MUST be written using LATIN LETTERS ONLY - a simple, readable '
    "transliteration of the PHRASE ITSELF (never of the translation, never IPA, never a "
    "non-Latin script) - always attempt one. "
    f'"category" is one short tag best describing the phrase\'s everyday context - use one of: '
    f"{', '.join(PRESET_SITUATIONS)} - or null if none fit well."
)


_PLACEMENT_TEST_SYSTEM = (
    "You create a short placement test for a language-learning app, used to estimate a "
    "learner's CEFR level (A1-C2) in the language they are learning. Respond with ONLY a JSON "
    'object: {"questions": [{"level": str, "kind": str, "prompt": str}, ...]}. Generate EXACTLY '
    "6 questions, one for each CEFR level in this exact order: a1, a2, b1, b2, c1, c2 - "
    '"level" must be that lowercase CEFR code. Alternate "kind" between "word" and "translate", '
    "starting with \"word\" for a1 (so a1=word, a2=translate, b1=word, b2=translate, c1=word, "
    "c2=translate). "
    "\n\n"
    'For a "word" question, "prompt" is a single common word or short common expression in the '
    "target language typical of that CEFR level (increasingly rare, abstract, or complex as the "
    "level rises) - just the word/expression itself, nothing else, no translation, no example "
    "sentence. "
    "\n\n"
    'For a "translate" question, "prompt" is ONE natural, self-contained sentence written in the '
    "target language, typical in length and grammatical complexity of that CEFR level, that the "
    "learner will be asked to translate into their own language - never include the translation "
    "itself, never a question about the sentence, just the sentence."
)

_GRADE_PLACEMENT_TEST_SYSTEM = (
    "You are grading a short placement test for a language-learning app, used to determine a "
    "learner's CEFR level (A1-C2) in the language they are learning. You will see a numbered "
    'list of items, each as "N. [level] (kind): prompt -> learner\'s answer". '
    '"word" items are self-reports: the learner said whether they already know that word/'
    'expression ("yes" or "no"). "translate" items asked the learner to translate a sentence '
    "from the target language into their own language; their answer is either a translation "
    "attempt or a statement that they could not do it. "
    "\n\n"
    "Judge translation attempts for genuine comprehension of the sentence's actual meaning, not "
    "perfect grammar or spelling in the learner's own language - a translation that gets the "
    "core meaning across counts as understood even if imperfect; an empty answer, 'no'/'don't "
    "know'/similar, or a translation that is clearly wrong or unrelated to the sentence's actual "
    "meaning counts as not understood. "
    "\n\n"
    "Weigh every item together and estimate the learner's overall CEFR level as the highest "
    "level at which they show reliably solid understanding - do not over-credit a single lucky "
    "guess at a much higher level than the surrounding pattern supports, and do not under-credit "
    "a learner who understood everything up to some level and only struggled beyond it. "
    "\n\n"
    'Respond with ONLY a JSON object: {"level": str} where level is exactly one of: a1, a2, b1, '
    "b2, c1, c2."
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


def _parse_verb_conjugation_response(raw: str) -> ai_models.VerbConjugationResult:
    payload = _parse_json(raw)
    try:
        return ai_models.VerbConjugationResult.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected verb-conjugation schema") from exc


def _parse_native_phrase_response(raw: str) -> ai_models.NativePhraseResult:
    payload = _parse_json(raw)
    try:
        return ai_models.NativePhraseResult.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected native-phrase schema") from exc


def _parse_translate_phrases_response(raw: str) -> ai_models.PhraseTranslationsResult:
    payload = _parse_json(raw)
    try:
        return ai_models.PhraseTranslationsResult.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected phrase-translations schema") from exc


def _parse_popular_phrases_response(raw: str) -> ai_models.PopularPhraseBatchResult:
    payload = _parse_json(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("phrases"), list):
        raise AIInvalidResponseError('AI response is missing a "phrases" list')

    phrases: list[ai_models.GeneratedPopularPhrase] = []
    for item in payload["phrases"]:
        try:
            phrases.append(ai_models.GeneratedPopularPhrase.model_validate(item))
        except ValidationError:
            # One malformed entry must not cost the rest of an otherwise
            # valid batch, same as _parse_generate_words_response above.
            continue
    return ai_models.PopularPhraseBatchResult(phrases=phrases)


_EXPECTED_PLACEMENT_LEVELS = ("a1", "a2", "b1", "b2", "c1", "c2")


def _parse_placement_test_response(raw: str) -> ai_models.PlacementTestResult:
    payload = _parse_json(raw)
    try:
        result = ai_models.PlacementTestResult.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected placement-test schema") from exc
    # Unlike a phrase/word batch, a partial or out-of-order placement
    # test is useless - the handler renders exactly 6 questions in this
    # exact level sequence, so treat any deviation as an invalid
    # response and let it feed the same bounded retry _complete already
    # runs for malformed JSON, rather than silently dropping items.
    levels = tuple(q.level for q in result.questions)
    if levels != _EXPECTED_PLACEMENT_LEVELS:
        raise AIInvalidResponseError("AI placement test did not cover exactly a1..c2 in order")
    return result


def _parse_placement_level_response(raw: str) -> ai_models.PlacementLevelResult:
    payload = _parse_json(raw)
    try:
        return ai_models.PlacementLevelResult.model_validate(payload)
    except ValidationError as exc:
        raise AIInvalidResponseError("AI response did not match the expected placement-level schema") from exc


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
        known_languages = {language_code.strip().lower(), translation_language.strip().lower()}

        def _parse(raw: str) -> ai_models.WordAIResult:
            result = _parse_word_response(raw)
            # Bidirectional-dictionary stage (spec sections 8, 27-29): the AI
            # must decide the translation direction itself and self-report
            # it as query_language. None is tolerated (an older response
            # shape that never populated this field) - only a populated,
            # wrong value is treated as invalid. A third/hallucinated
            # language, or a native-language query the AI just echoed back
            # unchanged instead of actually translating, both feed the same
            # bounded retry _complete already runs for a malformed body -
            # never shown to the learner as-is (spec: "никогда не давать
            # пользователю неверный перевод").
            if result.query_language is not None and result.query_language not in known_languages:
                raise AIInvalidResponseError("AI reported an unexpected query_language")
            if result.query_language == translation_language.strip().lower():
                if normalize_word(result.word) == normalize_word(word):
                    raise AIInvalidResponseError("AI did not translate the native-language query")
            return result

        return await self._complete("lookup_word", user_id, _LOOKUP_WORD_SYSTEM, user, _parse)

    async def generate_words(self, *, language_code, translation_language, level, amount, category=None, industry=None, goal=None, known_words=None, user_id):
        known = ", ".join((known_words or [])[:200])
        industry_line = f"Learner's work industry - bias vocabulary toward this field: {industry}\n" if industry else ""
        goal_line = f"Learner's goal for this language: {goal}\n" if goal else ""
        user = (
            f"Language being learned (ISO 639-1): {language_code}\n"
            f"Translate into language code: {translation_language}\n"
            f"Learner level: {level}\n"
            f"Category/topic: {category or 'any suitable for everyday use'}\n"
            f"{goal_line}"
            f"{industry_line}"
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

    async def generate_verb_conjugation(self, word, *, language_code, translation_language, user_id):
        user = (
            f"Verb: {word!r}\n"
            f"Language code (ISO 639-1): {language_code}\n"
            f"Native/translation language code for person_label and translation: {translation_language}\n"
        )
        return await self._complete(
            "generate_verb_conjugation", user_id, _VERB_CONJUGATION_SYSTEM, user, _parse_verb_conjugation_response
        )

    async def generate_native_phrase(self, *, language_code, translation_language, level, situation, industry=None, topics=None, exclude_phrases=None, user_id):
        topics_line = f"Learner's topics of interest: {', '.join(topics)}\n" if topics else ""
        industry_line = f"Learner's work industry - bias toward this field if relevant: {industry}\n" if industry else ""
        exclude = ", ".join((exclude_phrases or [])[:20])
        exclude_line = f'Do NOT repeat any of these already-shown phrases - give a different natural one: {exclude}\n' if exclude else ""
        user = (
            f"Target language the learner is learning (ISO 639-1): {language_code}\n"
            f"Respond (translation/explanation) in this language: {translation_language}\n"
            f"Learner level: {level}\n"
            f"Situation: {situation}\n"
            f"{topics_line}{industry_line}{exclude_line}"
        )

        def _parse(raw: str) -> ai_models.NativePhraseResult:
            result = _parse_native_phrase_response(raw)
            if result.language.strip().lower() != language_code.strip().lower():
                # Section 14: never trust the AI blindly - a phrase in the
                # wrong language must not reach the learner. Raising
                # AIInvalidResponseError here feeds the same bounded retry
                # loop _complete already runs for a malformed JSON body,
                # so this needs no separate retry mechanism of its own.
                raise AIInvalidResponseError("AI returned a phrase in the wrong language")
            return result

        return await self._complete("generate_native_phrase", user_id, _NATIVE_PHRASE_SYSTEM, user, _parse)

    async def translate_phrases(self, phrases, *, language_code, translation_language, user_id):
        numbered = "\n".join(f"{i + 1}. {phrase}" for i, phrase in enumerate(phrases))
        user = (
            f"Phrases are in language code (ISO 639-1): {language_code}\n"
            f"Translate into language code: {translation_language}\n"
            f"Phrases:\n{numbered}\n"
        )
        result = await self._complete(
            "translate_phrases", user_id, _TRANSLATE_PHRASES_SYSTEM, user, _parse_translate_phrases_response
        )
        return result.translations

    async def generate_popular_phrases(self, *, language_code, translation_language, level, amount=8, category=None, industry=None, topics=None, known_phrases=None, user_id):
        known = ", ".join((known_phrases or [])[:50])
        category_line = f"Bias generated phrases toward this category if it fits naturally: {category}\n" if category else ""
        topics_line = f"Learner's topics of interest: {', '.join(topics)}\n" if topics else ""
        industry_line = f"Learner's work industry - bias toward this field if relevant: {industry}\n" if industry else ""
        user = (
            f"Target language the learner is learning (ISO 639-1): {language_code}\n"
            f"Translate into language code: {translation_language}\n"
            f"Learner level: {level}\n"
            f"Exact amount of new distinct phrases to generate: {amount}\n"
            f"{category_line}{topics_line}{industry_line}"
            f"Phrases the learner already has - never repeat any of these: {known or 'none'}\n"
        )
        return await self._complete(
            "generate_popular_phrases", user_id, _POPULAR_PHRASES_SYSTEM, user, _parse_popular_phrases_response
        )

    async def generate_placement_test(self, *, language_code, translation_language, user_id):
        user = (
            f"Target language the learner is learning (ISO 639-1): {language_code}\n"
            f"Learner's own language (ISO 639-1) - the 'translate' questions ask them to "
            f"translate INTO this language: {translation_language}\n"
        )
        return await self._complete(
            "generate_placement_test", user_id, _PLACEMENT_TEST_SYSTEM, user, _parse_placement_test_response
        )

    async def grade_placement_test(self, *, language_code, translation_language, transcript, user_id):
        lines = "\n".join(
            f"{i}. [{item['level']}] ({item['kind']}): {item['prompt']} -> {item['answer']}"
            for i, item in enumerate(transcript, start=1)
        )
        user = (
            f"Target language the learner is learning (ISO 639-1): {language_code}\n"
            f"Learner's own language (ISO 639-1): {translation_language}\n"
            f"Placement test items and the learner's answers:\n{lines}\n"
        )
        return await self._complete(
            "grade_placement_test", user_id, _GRADE_PLACEMENT_TEST_SYSTEM, user, _parse_placement_level_response
        )

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
    the real bot reads .env once at startup).

    Builds a priority-ordered fallback chain out of whichever text
    providers are actually configured, highest priority first:

      1. Vercel AI Gateway (AI_GATEWAY_API_KEY) - an OpenAI-Chat-
         Completions-compatible endpoint that routes to Gemini (and
         others) from Vercel's own infrastructure. Useful when the
         server's own region can't reach Gemini directly.
      2. Direct Gemini (GEMINI_API_KEY)
      3. DeepSeek/AI_API_KEY - the original, pre-Gemini-integration
         provider slot, still the final fallback

    Each is independently optional - any single one alone works exactly
    as it always has (e.g. DeepSeek-only is identical to every release
    before Gemini existed), any combination chains via nested
    FallbackAIProvider (tries the next one down on ANY AIError, always
    starting from the top again on the NEXT call - never sticky), and
    none configured returns NotConfiguredAIService - AI-backed features
    always degrade to the local database, never block the bot from
    starting."""
    from config import get_settings
    from services.gemini_provider import GeminiTextProvider

    settings = get_settings()

    candidates: list[tuple[str, AIProvider, str]] = []  # (label, provider, model_label)

    if settings.ai_gateway_enabled and settings.ai_gateway_api_key:
        candidates.append((
            "vercel-gateway",
            HttpAIProvider(
                api_key=settings.ai_gateway_api_key,
                model=settings.ai_gateway_model,
                base_url=settings.ai_gateway_base_url,
                timeout=settings.ai_timeout_seconds,
            ),
            settings.ai_gateway_model,
        ))

    if settings.gemini_enabled and settings.gemini_api_key:
        candidates.append((
            "gemini",
            GeminiTextProvider(
                api_key=settings.gemini_api_key,
                model=settings.gemini_text_model or settings.gemini_model,
                base_url=settings.gemini_base_url,
                timeout=settings.ai_timeout_seconds,
                proxy=settings.gemini_proxy_url,
            ),
            settings.gemini_text_model or settings.gemini_model,
        ))

    if settings.ai_enabled and settings.ai_api_key:
        candidates.append((
            settings.ai_provider,
            HttpAIProvider(
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                base_url=settings.ai_base_url,
                timeout=settings.ai_timeout_seconds,
            ),
            settings.ai_model,
        ))

    if not candidates:
        return NotConfiguredAIService()

    # Fold right-to-left into nested FallbackAIProviders: the last
    # candidate is the innermost/final fallback, each earlier one wraps
    # it as a new primary - so trying `provider` tries candidates in
    # their original (highest-priority-first) order.
    provider_label, provider, _ = candidates[-1]
    for label, p, _ in reversed(candidates[:-1]):
        provider = FallbackAIProvider(primary=p, secondary=provider, primary_label=label, secondary_label=provider_label)
        provider_label = f"{label}+{provider_label}"
    model_label = candidates[0][2]  # the highest-priority candidate's own model, for logging

    return LiveAIService(
        provider=provider,
        model=model_label,
        provider_label=provider_label,
        max_retries=settings.max_ai_retries,
        requests_per_minute=settings.ai_requests_per_minute,
        requests_per_day=settings.ai_requests_per_day,
    )
