"""Automatic new-word generation (bugfix spec, root cause #2 - "Safabot не
генерирует и не добавляет новые слова автоматически"). services.learning_
service.get_new_words_for_today calls generate_new_words() for the
shortfall whenever the local pool of already-added NEW words can't fill
the user's daily quota on its own.

Local-pool-first, AI-fallback-for-the-rest, same as
dictionary_service.lookup_word: search database.repositories.words.
find_unknown_words_for_generation before ever calling an AI provider, and
only ask the provider for however many words are still missing. AI output
is validated by services.ai_word_schema before anything from it is
written to the database, and any provider failure degrades to "generated
fewer words than asked for" rather than raising - the learning flow must
never break because generation failed (bugfix spec explicitly).

Every call is logged to WordGenerationLog, including calls that never
reached an AI provider at all, so usage/cost can be audited from one place.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, UserLanguage, UserWord, WordSource
from database.repositories import user_words as user_words_repo
from database.repositories import word_generation_logs as generation_logs_repo
from database.repositories import words as words_repo
from services import ai_word_schema, user_word_service, word_service
from services.ai_service import get_ai_service

_ADD_OUTCOMES_COUNTED = {"created", "restored_from_deleted"}


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
    non-error result (empty local pool + no/failing AI provider)."""
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
    shortfall = amount - len(created)
    if shortfall > 0:
        entries, provider = await _generate_via_ai(
            language_code=user_language.language_code,
            translation_language=user_language.translation_language,
            level=user_language.level,
            amount=shortfall,
        )
        for entry in entries:
            if len(created) >= amount:
                break
            user_word = await _persist_and_add(
                session, entry=entry, user=user, user_language=user_language
            )
            if user_word is not None:
                created.append(user_word)

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


async def _persist_and_add(
    session: AsyncSession, *, entry: ai_word_schema.WordEntry, user: User, user_language: UserLanguage
) -> UserWord | None:
    word, was_created = await word_service.get_or_create_word(
        session,
        language_code=user_language.language_code,
        word=entry.word,
        part_of_speech=entry.part_of_speech,
        phonetic=entry.phonetic,
        difficulty=entry.difficulty or user_language.level,
        category=entry.category,
    )
    if was_created:
        for translation in entry.translations:
            await words_repo.add_translation(
                session, word_id=word.id, language_code=user_language.translation_language, translation=translation
            )
        for example in entry.examples:
            await words_repo.add_example(
                session, word_id=word.id, example_text=example.text, translation=example.translation
            )

    added = await user_word_service.add_word_to_learning(
        session, user_id=user.id, word_id=word.id, language_code=user_language.language_code
    )
    if added.outcome not in _ADD_OUTCOMES_COUNTED:
        # Already known to this user under a different status (e.g. the AI
        # echoed back a word the user already has PAUSED) - not a new word,
        # don't count it.
        return None
    added.user_word.source = WordSource.GENERATED
    return added.user_word


async def _generate_via_ai(
    *, language_code: str, translation_language: str, level: str, amount: int
) -> tuple[list[ai_word_schema.WordEntry], str]:
    """Never raises: any AI failure (not configured, network error,
    malformed JSON) yields ([], "<provider>") so the caller simply ends up
    with fewer generated words instead of a broken learning session."""
    from config import get_settings

    provider_name = get_settings().ai_provider
    try:
        raw = await get_ai_service().generate_words(
            language_code=language_code,
            translation_language=translation_language,
            level=level,
            amount=amount,
        )
    except Exception:
        return [], provider_name

    return ai_word_schema.parse_generation_response(raw), provider_name
