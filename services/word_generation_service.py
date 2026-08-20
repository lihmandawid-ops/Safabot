"""Automatic new-word generation (bugfix spec root cause #2 - "Safabot не
генерирует и не добавляет новые слова автоматически"; AI-integration spec
section 11). services.learning_service.get_new_words_for_today calls
generate_new_words() for the shortfall whenever the local pool of
already-added NEW words can't fill the user's daily quota on its own.

Local-pool-first, AI-fallback-for-the-rest, same as
dictionary_service.lookup_word: search database.repositories.words.
find_unknown_words_for_generation before ever calling AI, and only ask
for however many words are still missing. AI output is validated by
services/ai_models.py (via services/ai_service.py) before anything from
it is written to the database, and any AI failure degrades to "generated
fewer words than asked for" rather than raising - the learning flow must
never break because generation failed (bugfix spec explicitly).

Every call is logged to WordGenerationLog, including calls that never
reached AI at all, so usage/cost can be audited from one place.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, UserLanguage, UserWord, WordSource
from database.repositories import user_words as user_words_repo
from database.repositories import word_generation_logs as generation_logs_repo
from database.repositories import words as words_repo
from services import ai_models, user_word_service, word_service
from services.ai_errors import AIError
from services.ai_service import get_ai_service
from utils.logging import get_logger

logger = get_logger(__name__)

_ADD_OUTCOMES_COUNTED = {"created", "restored_from_deleted"}
_KNOWN_WORDS_LIMIT = 150


async def generate_new_words(
    session: AsyncSession,
    *,
    user: User,
    user_language: UserLanguage,
    amount: int,
) -> list[UserWord]:
    """Adds up to `amount` new UserWord rows (status NEW, source
    GENERATED) for user_language, local words first, AI fallback for the
    shortfall. Returns however many it actually managed - 0 is a valid,
    non-error result (empty local pool + no/failing AI)."""
    if amount <= 0:
        return []

    created: list[UserWord] = []

    local_candidates = await words_repo.find_unknown_words_for_generation(
        session,
        user_id=user.id,
        language_code=user_language.language_code,
        level=user_language.level,
        limit=amount,
    )
    for word in local_candidates:
        added = await user_word_service.add_word_to_learning(
            session, user_id=user.id, word_id=word.id, language_code=user_language.language_code
        )
        if added.outcome in _ADD_OUTCOMES_COUNTED:
            added.user_word.source = WordSource.GENERATED
            created.append(added.user_word)

    provider = "local"
    if len(created) < amount:
        provider = await _top_up_via_ai(session, user=user, user_language=user_language, amount=amount, created=created)

    await generation_logs_repo.log(
        session,
        user_id=user.id,
        language_code=user_language.language_code,
        requested_amount=amount,
        generated_amount=len(created),
        provider=provider,
    )

    # Every UserWord above only has its bare word_id set in memory - the
    # AI-sourced ones were never routed through a query that eager-loads
    # .word, so reading uw.word later would hit an unsupported lazy-load
    # under async SQLAlchemy (same MissingGreenlet trap documented on
    # sessions_repo.create_session). Re-fetch through user_words_repo,
    # which does eager-load it, before handing anything back.
    return [await user_words_repo.get_by_id(session, uw.id) for uw in created]


async def _top_up_via_ai(
    session: AsyncSession, *, user: User, user_language: UserLanguage, amount: int, created: list[UserWord]
) -> str:
    """Asks AI for the shortfall, retrying up to MAX_GENERATION_ATTEMPTS
    times if what came back was entirely (or partly) duplicates of
    something the user already has - never unbounded (spec section 12).
    Mutates `created` in place; returns the provider label to log.
    """
    from config import get_settings

    settings = get_settings()
    provider_label = settings.ai_provider
    known_words = await _recent_known_words(session, user=user, user_language=user_language)

    attempts = 0
    while len(created) < amount and attempts < settings.max_generation_attempts:
        attempts += 1
        shortfall = amount - len(created)
        entries = await _generate_via_ai(
            language_code=user_language.language_code,
            translation_language=user_language.translation_language,
            level=user_language.level,
            amount=shortfall,
            known_words=known_words,
            user_id=user.id,
        )
        if not entries:
            break

        for entry in entries:
            if len(created) >= amount:
                break
            user_word = await _persist_and_add(session, entry=entry, user=user, user_language=user_language)
            if user_word is not None:
                created.append(user_word)
                known_words.append(entry.word)

    return provider_label if attempts > 0 else "local"


async def _recent_known_words(session: AsyncSession, *, user: User, user_language: UserLanguage) -> list[str]:
    """Section 13: give AI a bounded hint of what the learner already has,
    never the whole personal dictionary."""
    existing = await user_words_repo.get_user_words(
        session, user_id=user.id, language_code=user_language.language_code, limit=_KNOWN_WORDS_LIMIT
    )
    return [uw.word.word for uw in existing]


async def _persist_and_add(
    session: AsyncSession, *, entry: ai_models.GeneratedWord, user: User, user_language: UserLanguage
) -> UserWord | None:
    word, was_created = await word_service.get_or_create_word(
        session,
        language_code=user_language.language_code,
        word=entry.word,
        part_of_speech=entry.part_of_speech,
        pronunciation=entry.pronunciation,
        phonetic=entry.phonetic,
        difficulty=entry.difficulty or user_language.level,
        category=entry.category,
    )
    if was_created:
        for translation in entry.translations:
            await words_repo.add_translation(
                session, word_id=word.id, language_code=user_language.translation_language,
                translation=translation.translation, usage_note=translation.usage_note,
            )
        for example in entry.examples:
            await words_repo.add_example(
                session, word_id=word.id, example_text=example.text, translation=example.translation
            )
        if entry.part_of_speech == "verb" and entry.verb_forms:
            for form_type, form in entry.verb_forms.items():
                await words_repo.add_form(session, word_id=word.id, form_type=form_type, form=form)

    added = await user_word_service.add_word_to_learning(
        session, user_id=user.id, word_id=word.id, language_code=user_language.language_code
    )
    if added.outcome not in _ADD_OUTCOMES_COUNTED:
        # Already known to this user under a different status (e.g. AI
        # echoed back a word the user already has PAUSED) - not a new
        # word, don't count it; the retry loop above will ask for another.
        return None
    added.user_word.source = WordSource.GENERATED
    return added.user_word


async def _generate_via_ai(
    *, language_code: str, translation_language: str, level: str, amount: int,
    known_words: list[str], user_id: int,
) -> list[ai_models.GeneratedWord]:
    """Never raises: any AI failure (not configured, network error,
    invalid response) yields [] so the caller simply ends up with fewer
    generated words instead of a broken learning session."""
    try:
        result = await get_ai_service().generate_words(
            language_code=language_code,
            translation_language=translation_language,
            level=level,
            amount=amount,
            known_words=known_words,
            user_id=user_id,
        )
    except AIError as exc:
        logger.info("Word generation AI fallback unavailable for %r: %s", language_code, type(exc).__name__)
        return []

    return result.words
