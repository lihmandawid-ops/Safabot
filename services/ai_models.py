"""Structured, validated shapes for everything an AI provider returns
(spec section 6: "AI не должен возвращать данные в виде произвольного
текста там, где данные нужно сохранять в БД").

These are the ONLY shapes services/ai_service.py hands back to its
callers - a provider's raw JSON never leaves ai_service.py unparsed.
Enum-like fields reuse the database's own vocabulary
(database.models.PartOfSpeech/WordCategory, utils.levels.LEVEL_CODES)
instead of a second hand-maintained list, so the two can never drift.

An invalid *individual* field (e.g. an unrecognised part_of_speech) is
dropped rather than failing the whole word - a word without a
part-of-speech tag is still useful, but `word`/`translations` are load-
bearing everywhere downstream, so those two remain required.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from database.models import PartOfSpeech, WordCategory
from utils.levels import LEVEL_CODES
from utils.phrase_situations import PRESET_SITUATIONS

_VALID_PARTS_OF_SPEECH = {p.value for p in PartOfSpeech}
_VALID_CATEGORIES = {c.value for c in WordCategory}
_VALID_DIFFICULTIES = set(LEVEL_CODES)
_VALID_PHRASE_CATEGORIES = set(PRESET_SITUATIONS)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class TranslationResult(BaseModel):
    translation: str
    usage_note: str | None = None

    @field_validator("translation")
    @classmethod
    def _translation_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("translation must not be blank")
        return value

    @field_validator("usage_note", mode="before")
    @classmethod
    def _clean_usage_note(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value


class ExampleResult(BaseModel):
    text: str
    translation: str | None = None
    # study-flow-rework stage section 40: the example sentence's OWN Latin
    # pronunciation (global pronunciation rule, sections 8/35) - a whole
    # sentence reads differently than the headword alone, so this is never
    # inferred from GeneratedWord.pronunciation.
    pronunciation: str | None = None

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("example text must not be blank")
        return value

    @field_validator("translation", "pronunciation", mode="before")
    @classmethod
    def _clean_translation(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value


class GeneratedWord(BaseModel):
    """One AI-produced word, whether from a single dictionary lookup or a
    bulk generation batch - both need exactly the same fields to become a
    Word/UserWord row, so there is only one shape for both.
    """

    word: str
    # No default: pydantic only runs field validators on an explicitly
    # provided value, not on a default (validate_default=False) - making
    # this required means both "translations missing entirely" and
    # "translations: []" fail validation, instead of only the latter.
    translations: list[TranslationResult]
    part_of_speech: str | None = None
    phonetic: str | None = None
    pronunciation: str | None = None
    # Singular, matching database.models.Word.definition - a short meaning/
    # gloss, not a list of alternate senses (spec section 5's schema).
    definition: str | None = None
    examples: list[ExampleResult] = Field(default_factory=list)
    difficulty: str | None = None
    category: str | None = None
    # form_type -> form, e.g. {"past": "went", "gerund": "going"} for
    # English or {"präteritum": "ging"} for German - free-form on purpose
    # (spec section 20: no invented universal verb-form schema).
    verb_forms: dict[str, str] | None = None

    @field_validator("word")
    @classmethod
    def _word_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("word must not be blank")
        return value

    @field_validator("translations")
    @classmethod
    def _at_least_one_translation(cls, value: list[TranslationResult]) -> list[TranslationResult]:
        if not value:
            raise ValueError("at least one translation is required")
        return value

    @field_validator("part_of_speech", "difficulty", "category", "phonetic", "pronunciation", "definition", mode="before")
    @classmethod
    def _clean_optional_str(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value

    @field_validator("part_of_speech")
    @classmethod
    def _valid_part_of_speech(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        return value if value in _VALID_PARTS_OF_SPEECH else None

    @field_validator("difficulty")
    @classmethod
    def _valid_difficulty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        return value if value in _VALID_DIFFICULTIES else None

    @field_validator("category")
    @classmethod
    def _valid_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        return value if value in _VALID_CATEGORIES else None

    @field_validator("verb_forms")
    @classmethod
    def _only_for_verbs_and_non_empty(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if not value:
            return None
        cleaned = {str(k).strip(): str(v).strip() for k, v in value.items() if str(k).strip() and str(v).strip()}
        return cleaned or None


class WordAIResult(GeneratedWord):
    """Alias name for the single-word dictionary-lookup case (spec section
    6 lists it separately from GeneratedWord) - identical shape, since a
    looked-up word and a generated word are persisted the same way.

    `query_language` (bidirectional-dictionary stage sections 8, 27-29):
    the ISO 639-1 code the AI itself decided the user's raw input was
    written in - either the learning language or the native/translation
    language, never a third one. This is the ONLY reliable, structural
    way services.dictionary_service can catch "AI mixed up the
    translation direction" and retry, rather than trying to language-
    detect free text itself. None is tolerated (an older prompt/response
    shape) - callers simply skip the direction check in that case rather
    than failing a previously-working response shape."""

    query_language: str | None = None

    @field_validator("query_language", mode="before")
    @classmethod
    def _clean_query_language(cls, value: object) -> object:
        return _clean(value.lower()) if isinstance(value, str) else value


class GenerateWordsResult(BaseModel):
    words: list[GeneratedWord] = Field(default_factory=list)


class AnalyzedWord(BaseModel):
    word: str
    translation: str
    part_of_speech: str | None = None
    pronunciation: str | None = None

    @field_validator("word", "translation")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("part_of_speech", mode="before")
    @classmethod
    def _clean_pos(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value

    @field_validator("part_of_speech")
    @classmethod
    def _valid_pos(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        return value if value in _VALID_PARTS_OF_SPEECH else None

    @field_validator("pronunciation", mode="before")
    @classmethod
    def _clean_pronunciation(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value


class AnalyzedPhrase(BaseModel):
    """💬 Полезные фразы (global pronunciation rule, section 44): a phrase
    with its own whole-phrase pronunciation, kept alongside key_words
    rather than replacing it - key_words already covers per-word
    pronunciation for the significant vocabulary shown from the text."""

    phrase: str
    pronunciation: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_plain_string(cls, value: object) -> object:
        # Tolerates an older/pre-pronunciation AI response shape (a plain
        # list[str]) so a model that ignores the updated prompt still
        # degrades gracefully instead of failing the whole analysis.
        if isinstance(value, str):
            return {"phrase": value, "pronunciation": None}
        return value

    @field_validator("phrase")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("pronunciation", mode="before")
    @classmethod
    def _clean_pronunciation(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value


class TextAnalysisResult(BaseModel):
    original_text: str
    translation: str
    pronunciation: str | None = None
    key_words: list[AnalyzedWord] = Field(default_factory=list)
    difficulty: str | None = None
    useful_phrases: list[AnalyzedPhrase] = Field(default_factory=list)

    @field_validator("pronunciation", mode="before")
    @classmethod
    def _clean_pronunciation(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value

    @field_validator("difficulty", mode="before")
    @classmethod
    def _clean_difficulty(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value

    @field_validator("difficulty")
    @classmethod
    def _valid_difficulty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        return value if value in _VALID_DIFFICULTIES else None

    @model_validator(mode="after")
    def _text_not_blank(self) -> "TextAnalysisResult":
        if not self.original_text.strip():
            raise ValueError("original_text must not be blank")
        if not self.translation.strip():
            raise ValueError("translation must not be blank")
        return self


class GrammarExplanation(BaseModel):
    explanation: str
    examples: list[str] = Field(default_factory=list)

    @field_validator("explanation")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("explanation must not be blank")
        return value


class ConjugatedForm(BaseModel):
    """One conjugated form plus its own pronunciation (global pronunciation
    rule, section 49: "ideally per individual conjugated form" - each verb
    form is its own distinct pronunciation, not a single pronunciation for
    the infinitive reused across the whole table).

    `person_label` and `translation` (bidirectional-dictionary stage
    sections 14-18): the grammatical-person label ("Я"/"Ты"/"Он"/..., or
    however this specific language naturally groups its persons - e.g.
    Hebrew commonly pairs masculine/feminine on one row) and this form's
    own translation, BOTH written in native_language by the AI itself -
    deliberately free text rather than a fixed enum of person tags, same
    philosophy as `forms`' own free-form tense/mood keys, since forcing
    one universal person scheme onto every language is exactly what the
    spec forbids. Both optional so an older cached table (pre-dating this
    field) keeps rendering exactly as it did before."""

    form: str
    pronunciation: str | None = None
    person_label: str | None = None
    translation: str | None = None

    @field_validator("form")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("pronunciation", "person_label", "translation", mode="before")
    @classmethod
    def _clean_pronunciation(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value


class VerbConjugationResult(BaseModel):
    """🔤 Все формы (repetition-system stage sections 22-24): `forms` maps
    a tense/mood name - in whatever terms are natural for THIS word's own
    language, never forced into English's four - to an ordered list of
    conjugated forms, one per grammatical person that language
    distinguishes. Free-form keys on purpose, same philosophy as
    GeneratedWord.verb_forms above."""

    word: str
    language: str
    forms: dict[str, list[ConjugatedForm]]

    @field_validator("word", "language")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("forms", mode="before")
    @classmethod
    def _clean_forms(cls, value: dict) -> dict:
        # Tolerates a plain list[str] per tense too (an older/pre-
        # pronunciation AI response shape, or a caller that hasn't been
        # updated) - each bare string becomes a form with no pronunciation
        # rather than failing the whole conjugation table.
        cleaned: dict[str, list[dict]] = {}
        for tense, items in (value or {}).items():
            tense = str(tense).strip()
            if not tense or not isinstance(items, list):
                continue
            forms: list[dict] = []
            for item in items:
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        forms.append({"form": text, "pronunciation": None})
                elif isinstance(item, dict):
                    text = str(item.get("form", "")).strip()
                    if text:
                        forms.append({
                            "form": text,
                            "pronunciation": item.get("pronunciation"),
                            "person_label": item.get("person_label"),
                            "translation": item.get("translation"),
                        })
            if forms:
                cleaned[tense] = forms
        if not cleaned:
            raise ValueError("forms must contain at least one non-empty tense")
        return cleaned


class NativePhraseResult(BaseModel):
    """💬 Полезные фразы (native-speaker phrasebook stage, sections 6-13):
    a single natural, native-speaker phrase for a situation - never a
    literal translation of a fixed source sentence. `language` is checked
    by the caller (services/ai_service.py's generate_native_phrase)
    against the requested language_code, so a response in the wrong
    language is treated as invalid and retried through the normal
    _complete retry loop rather than silently shown to the learner.

    The field is `register_type`, not `register` - pydantic's BaseModel
    already has an attribute named `register`, and shadowing it triggers
    a UserWarning on every import. The AI's JSON key is still plain
    "register" (matching the prompt's documented response shape); the
    "before" validator below just renames that one key on the way in.
    """

    language: str
    phrase: str
    translation: str
    pronunciation: str | None = None
    register_type: str | None = None
    naturalness: str | None = None
    situation: str | None = None
    explanation: str | None = None
    alternative: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _rename_register_key(cls, value: object) -> object:
        if isinstance(value, dict) and "register" in value and "register_type" not in value:
            value = {**value, "register_type": value["register"]}
        return value

    @field_validator("language", "phrase", "translation")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("pronunciation", "register_type", "naturalness", "situation", "explanation", "alternative", mode="before")
    @classmethod
    def _clean_optional(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value


class PhraseTranslationsResult(BaseModel):
    """🔥 Популярные фразы' translation cache (native-speaker phrasebook
    stage bugfix): a batch translation of N target-language phrases into
    translation_language, in the same order - one AI call per (language,
    translation_language) pair ever, instead of one call per phrase or
    per page. Order/count are matched up against the input list by the
    caller (services/phrase_service.py), which tolerates a mismatched
    count gracefully rather than failing the whole batch."""

    translations: list[str] = Field(default_factory=list)


class GeneratedPopularPhrase(BaseModel):
    """One phrase out of a ✨ Сгенерировать ещё batch (native-speaker
    phrasebook stage) - same native-speaker/Latin-pronunciation rules as
    NativePhraseResult, but produced N-at-a-time instead of one at a
    time, and destined for the shared 🔥 Популярные фразы pool (database.
    models.PopularPhrase) rather than one user's own saved list."""

    phrase: str
    translation: str
    pronunciation: str | None = None
    category: str | None = None

    @field_validator("phrase", "translation")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("pronunciation", mode="before")
    @classmethod
    def _clean_pronunciation(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value

    @field_validator("category", mode="before")
    @classmethod
    def _clean_category(cls, value: object) -> object:
        return _clean(value.lower()) if isinstance(value, str) else value

    @field_validator("category")
    @classmethod
    def _valid_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value if value in _VALID_PHRASE_CATEGORIES else None


class PopularPhraseBatchResult(BaseModel):
    phrases: list[GeneratedPopularPhrase] = Field(default_factory=list)
