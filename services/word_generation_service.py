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

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, UserLanguage, UserWord, WordSource, WordStatus
from database.repositories import rejected_words as rejected_words_repo
from database.repositories import user_words as user_words_repo
from database.repositories import word_generation_logs as generation_logs_repo
from database.repositories import words as words_repo
from services import ai_models, learner_profile_service, user_word_service, word_service
from services.ai_errors import AIError
from services.ai_service import get_ai_service
from utils.logging import get_logger
from utils.text import normalize_word
from utils.time import local_day_bounds, utc_now

logger = get_logger(__name__)

_ADD_OUTCOMES_COUNTED = {"created", "restored_from_deleted"}
_KNOWN_WORDS_LIMIT = 150


@dataclass
class ExtraWordsResult:
    """Result of an explicit "➕ Ещё новые слова" request (bugfix stage,
    sections 9-11) - kept separate from generate_new_words' plain list
    because the caller needs to tell "got some, ask again later for more"
    apart from "hit today's extra-words cap, come back tomorrow"."""

    words: list[UserWord] = field(default_factory=list)
    limit_reached: bool = False
    remaining_today: int = 0


async def generate_new_words(
    session: AsyncSession,
    *,
    user: User,
    user_language: UserLanguage,
    amount: int,
    trigger: str = "daily_quota",
    status: str = WordStatus.NEW,
) -> list[UserWord]:
    """Adds up to `amount` new UserWord rows (status NEW by default,
    source GENERATED) for user_language, local words first, AI fallback
    for the shortfall. Returns however many it actually managed - 0 is a
    valid, non-error result (empty local pool + no/failing AI).

    `trigger` only affects what gets written to WordGenerationLog - it
    doesn't change the algorithm - so generate_extra_words() and the
    "🤔 Я это уже знаю" replacement flow reuse this exact function instead
    of a second local-pool/AI-fallback implementation.

    `status` defaults to NEW so services.learning_service.
    get_new_words_for_today's local-pool rediscovery (get_new_word_
    candidates' status==NEW query) keeps working - generate_extra_words
    (➕ Ещё новые слова, a LIVE user action) passes status=WordStatus.
    LEARNING instead, per user_word_service.add_word_to_learning's
    docstring."""
    if amount <= 0:
        return []

    from services.level_progress_service import effective_difficulty

    created: list[UserWord] = []

    local_candidates = await words_repo.find_unknown_words_for_generation(
        session,
        user_id=user.id,
        language_code=user_language.language_code,
        level=effective_difficulty(user_language),
        limit=amount,
        topics=user_language.selected_topics,
    )
    for word in local_candidates:
        added = await user_word_service.add_word_to_learning(
            session, user_id=user.id, word_id=word.id, language_code=user_language.language_code, status=status
        )
        if added.outcome in _ADD_OUTCOMES_COUNTED:
            added.user_word.source = WordSource.GENERATED
            created.append(added.user_word)

    provider = "local"
    if len(created) < amount:
        provider = await _top_up_via_ai(
            session, user=user, user_language=user_language, amount=amount, created=created, status=status
        )

    await generation_logs_repo.log(
        session,
        user_id=user.id,
        language_code=user_language.language_code,
        requested_amount=amount,
        generated_amount=len(created),
        provider=provider,
        trigger=trigger,
    )

    # Every UserWord above only has its bare word_id set in memory - the
    # AI-sourced ones were never routed through a query that eager-loads
    # .word, so reading uw.word later would hit an unsupported lazy-load
    # under async SQLAlchemy (same MissingGreenlet trap documented on
    # sessions_repo.create_session). Re-fetch through user_words_repo,
    # which does eager-load it, before handing anything back.
    return [await user_words_repo.get_by_id(session, uw.id) for uw in created]


async def generate_extra_words(
    session: AsyncSession,
    *,
    user: User,
    user_language: UserLanguage,
    amount: int,
    now=None,
) -> ExtraWordsResult:
    """➕ Ещё новые слова (bugfix spec sections 9-11): a user-initiated
    top-up on top of the normal daily_new_words pace, bounded by its own
    separate MAX_EXTRA_WORDS_PER_DAY cap so repeatedly pressing the button
    can't drive unbounded DeepSeek usage. Reuses generate_new_words for
    the actual local-pool/AI-fallback/dedup work - only the quota check is
    new here.

    Real user request: this is a LIVE, user-initiated add (unlike
    get_new_words_for_today's own internal shortfall top-up), so it
    explicitly opts these words into status=LEARNING - they must enter
    repetition immediately instead of sitting as an untouched NEW
    candidate.
    """
    from config import get_settings

    settings = get_settings()
    now = now if now is not None else utc_now()
    day_start, day_end = local_day_bounds(now, user.timezone)

    used_today = await generation_logs_repo.sum_generated_today(
        session, user_id=user.id, language_code=user_language.language_code,
        trigger="extra_request", day_start=day_start, day_end=day_end,
    )
    available = max(0, settings.max_extra_words_per_day - used_today)
    if available <= 0:
        return ExtraWordsResult(words=[], limit_reached=True, remaining_today=0)

    bounded_amount = min(amount, available)
    created = await generate_new_words(
        session, user=user, user_language=user_language, amount=bounded_amount, trigger="extra_request",
        status=WordStatus.LEARNING,
    )
    return ExtraWordsResult(words=created, limit_reached=False, remaining_today=max(0, available - len(created)))


async def generate_words_ai_first(
    session: AsyncSession,
    *,
    user: User,
    user_language: UserLanguage,
    amount: int,
    topics: list[str] | None = None,
    trigger: str = "explicit_new_words",
) -> list[UserWord]:
    """🆕 Новые слова / 🎯 Новые слова по теме (level-and-difficulty stage,
    spec sections 40-62): explicit, deliberate requests where the AI must
    genuinely pick words for THIS learner - level, goal, industry,
    topic/interests, and what they already know - never "take some rows
    out of the local pool first" like generate_new_words()'s daily-quota/
    ➕-extra/already-know-it callers do (those stay on generate_new_words,
    completely unchanged).

    Goes straight to _top_up_via_ai with an empty `created` seed, so the
    local database is used only for existence/duplicate checks inside that
    call (via word_service.get_or_create_word and user_word_service.
    add_word_to_learning), never as a source of which words to suggest -
    and it inherits the exact same bounded-retry, no-random-padding
    behavior already covering generate_new_words' AI shortfall path.

    `topics` is the ONE topic (or short list) this specific call is
    scoped to - pass None for a plain 🆕 Новые слова request (falls back
    to the profile's saved selected_topics/goal/industry, same hints
    generate_new_words already uses), or the user's freshly typed/picked
    topic(s) for 🎯 Новые слова по теме. Returns [] (never raises) if AI
    couldn't produce anything usable - callers show the standard "couldn't
    find new words, try again" message rather than falling back to random
    database words.
    """
    if amount <= 0:
        return []

    created: list[UserWord] = []
    provider = await _top_up_via_ai(
        session, user=user, user_language=user_language, amount=amount, created=created, topics_override=topics,
    )

    await generation_logs_repo.log(
        session,
        user_id=user.id,
        language_code=user_language.language_code,
        requested_amount=amount,
        generated_amount=len(created),
        provider=provider,
        trigger=trigger,
    )

    return [await user_words_repo.get_by_id(session, uw.id) for uw in created]


async def generate_candidates(
    session: AsyncSession,
    *,
    user: User,
    user_language: UserLanguage,
    amount: int,
    topics: list[str] | None = None,
) -> list[ai_models.GeneratedWord]:
    """🆕 Новые слова / 🎯 Новые слова по теме (AI-new-words stage sections
    1-7, 32-33): unlike generate_words_ai_first (which persists every AI
    result as a UserWord immediately), this hands back raw, NOT-YET-
    PERSISTED candidates for handlers/learning.py to walk through one at a
    time - a word only becomes a real UserWord row once the learner taps
    ➕ Добавить в обучение (services.user_word_service.add_word_to_learning,
    called from the handler), and a ❌ Я уже знаю это слово tap never
    touches UserWord at all (see reject_word below). Still fully AI-first,
    still bounded-retry (MAX_GENERATION_ATTEMPTS), still logged to
    WordGenerationLog - only the persistence timing differs.

    Excludes both what the learner already owns (known_words, same 150-
    word hint generate_new_words/generate_words_ai_first already use) AND
    everything they've previously rejected (rejected_words) - spec section
    7's "AI не должен повторно предлагать отклонённые слова". Both lists
    are merged into the single `known_words` prompt field the AI already
    understands as "never suggest these again", so no AIService interface
    change is needed for the exclusion itself.
    """
    if amount <= 0:
        return []

    from config import get_settings
    from services.level_progress_service import effective_difficulty

    settings = get_settings()
    known_words = await _recent_known_words(session, user=user, user_language=user_language)
    rejected = await rejected_words_repo.list_words(session, user_id=user.id, language_code=user_language.language_code)
    excluded = list(known_words)
    seen_normalized = {normalize_word(w) for w in excluded}
    for word in rejected:
        key = normalize_word(word)
        if key not in seen_normalized:
            seen_normalized.add(key)
            excluded.append(word)

    category = _topic_hint(user_language, override=topics)
    industry = _industry_hint(user_language)
    goal = _goal_hint(user_language)
    performance_note = await _performance_note(session, user_id=user.id, user_language=user_language)

    candidates: list[ai_models.GeneratedWord] = []
    attempts = 0
    while len(candidates) < amount and attempts < settings.max_generation_attempts:
        attempts += 1
        shortfall = amount - len(candidates)
        entries = await _generate_via_ai(
            language_code=user_language.language_code,
            translation_language=user_language.translation_language,
            level=effective_difficulty(user_language),
            amount=shortfall,
            category=category,
            industry=industry,
            goal=goal,
            known_words=excluded,
            performance_note=performance_note,
            user_id=user.id,
        )
        if not entries:
            break
        for entry in entries:
            if len(candidates) >= amount:
                break
            key = normalize_word(entry.word)
            if key in seen_normalized:
                continue
            seen_normalized.add(key)
            excluded.append(entry.word)
            candidates.append(entry)

    await generation_logs_repo.log(
        session,
        user_id=user.id,
        language_code=user_language.language_code,
        requested_amount=amount,
        generated_amount=len(candidates),
        provider=(settings.ai_provider if attempts > 0 else "local"),
        trigger="explicit_new_words" if topics is None else "explicit_new_words_topic",
    )
    return candidates


async def add_candidate_to_learning(
    session: AsyncSession, *, entry: ai_models.GeneratedWord, user: User, user_language: UserLanguage
) -> UserWord | None:
    """➕ Добавить в обучение on a candidate from generate_candidates - the
    ONLY point a candidate actually becomes a UserWord row. Reuses the
    exact same persist-then-add path _persist_and_add already validated
    (get_or_create_word + add_word_to_learning, source GENERATED) so an
    added candidate is indistinguishable from any other generated word
    once it's in the learner's list.

    Real user request: both callers of this function (📚 Учить слова's
    candidate cards, and generate_and_add_morning_words' auto-added
    morning words) are LIVE additions the learner has already seen in
    full - status=WordStatus.LEARNING so the word enters repetition right
    away instead of sitting as an untouched NEW candidate only the (now
    unreachable) daily-quota flow would ever pick up."""
    return await _persist_and_add(session, entry=entry, user=user, user_language=user_language, status=WordStatus.LEARNING)


async def generate_and_add_morning_words(
    session: AsyncSession, *, user: User, user_language: UserLanguage, amount: int
) -> list[ai_models.GeneratedWord]:
    """🌅 Automatic morning notification (learning-methodology stage
    sections 1-5, 18, 27-28, 34): exactly `amount` (2, per the scheduler
    caller) new words are added straight away, with no confirm/reject
    step - a morning word is part of the daily routine, not an offer the
    learner has to accept (spec section 18: "не спрашивать 'Добавить
    слово в обучение?'"). Composes the two building blocks the manual
    🆕/🎯 flow already uses (generate_candidates for the context-aware,
    already-known/rejected-excluding AI pick, add_candidate_to_learning
    for the actual persistence) into a single call, so this shares 100%
    of the same exclusion logic and AI prompt - no separate code path,
    no separate AI call shape. One AI request covers the whole batch
    (generate_candidates already asks for `amount` words in one call,
    section 27's "один AI-запрос -> сразу 2 слова" - not one request per
    word).

    Returns the ai_models.GeneratedWord entries that were actually
    persisted (word/pronunciation/translations already in hand, ready for
    the notification text) rather than the resulting UserWord rows -
    add_candidate_to_learning's return value has an unloaded `.word`
    relationship (same MissingGreenlet trap documented on
    word_generation_service._persist_and_add's other callers), so handing
    back the already-in-memory AI entry instead is both simpler and
    avoids an extra DB round-trip. However many actually got added is
    returned - 0 is a valid, non-error result (AI unavailable/failed),
    the caller degrades the morning message gracefully rather than
    treating this as fatal."""
    candidates = await generate_candidates(session, user=user, user_language=user_language, amount=amount)
    added: list[ai_models.GeneratedWord] = []
    for entry in candidates:
        user_word = await add_candidate_to_learning(session, entry=entry, user=user, user_language=user_language)
        if user_word is not None:
            added.append(entry)
    return added


async def reject_word(session: AsyncSession, *, user: User, user_language: UserLanguage, word: str) -> None:
    """❌ Я уже знаю это слово (AI-new-words stage sections 6-7): records
    the rejection so future generate_candidates calls exclude it, WITHOUT
    creating any UserWord row - the learner never studied this word
    through Safabot, so it must not appear in "Выученные слова" (only a
    real learning->mastered progression, or the existing 🤔 Я это уже
    знаю inside an active session, does that)."""
    await rejected_words_repo.add(session, user_id=user.id, language_code=user_language.language_code, word=word)


def _topic_hint(user_language: UserLanguage, *, override: list[str] | None = None) -> str | None:
    """🎯 Темы обучения (settings-improvements stage section 22): joined
    into a single free-text "Category" line for the AI prompt - it
    already accepts a phrase there, not just one of the fixed local
    Word.category values, so a mix of preset and custom topics both work
    unchanged.

    `override` (level-and-difficulty stage, spec sections 40-58) lets
    🎯 Новые слова по теме pass the ONE topic the user just picked for this
    single generation call, instead of the profile's whole saved
    selected_topics list."""
    topics = override if override is not None else user_language.selected_topics
    return ", ".join(topics) if topics else None


def _goal_hint(user_language: UserLanguage) -> str | None:
    """Spec sections 40-58: the AI-first generation path must factor the
    learner's stated goal, not just topic/industry."""
    return user_language.learning_goal or None


def _industry_hint(user_language: UserLanguage) -> str | None:
    """AI-new-words stage section 1: a stated profession is relevant
    context regardless of the learner's stated goal (someone whose goal is
    "travel" but who happens to be a car mechanic still benefits from
    work_industry biasing the AI's word choice on request) - no longer
    gated behind learning_goal == "work"."""
    return user_language.work_industry or None


async def _top_up_via_ai(
    session: AsyncSession, *, user: User, user_language: UserLanguage, amount: int, created: list[UserWord],
    topics_override: list[str] | None = None, status: str = WordStatus.NEW,
) -> str:
    """Asks AI for the shortfall, retrying up to MAX_GENERATION_ATTEMPTS
    times if what came back was entirely (or partly) duplicates of
    something the user already has - never unbounded (spec section 12).
    Mutates `created` in place; returns the provider label to log.

    Section 6: the effective difficulty for generation is the manual pick
    when difficulty_mode == "manual", never the auto-tracked estimate -
    see services.level_progress_service.effective_difficulty.
    """
    from config import get_settings
    from services.level_progress_service import effective_difficulty

    settings = get_settings()
    provider_label = settings.ai_provider
    known_words = await _recent_known_words(session, user=user, user_language=user_language)
    category = _topic_hint(user_language, override=topics_override)
    industry = _industry_hint(user_language)
    goal = _goal_hint(user_language)
    performance_note = await _performance_note(session, user_id=user.id, user_language=user_language)

    attempts = 0
    while len(created) < amount and attempts < settings.max_generation_attempts:
        attempts += 1
        shortfall = amount - len(created)
        entries = await _generate_via_ai(
            language_code=user_language.language_code,
            translation_language=user_language.translation_language,
            level=effective_difficulty(user_language),
            amount=shortfall,
            category=category,
            industry=industry,
            goal=goal,
            known_words=known_words,
            performance_note=performance_note,
            user_id=user.id,
        )
        if not entries:
            break

        for entry in entries:
            if len(created) >= amount:
                break
            user_word = await _persist_and_add(session, entry=entry, user=user, user_language=user_language, status=status)
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
    session: AsyncSession, *, entry: ai_models.GeneratedWord, user: User, user_language: UserLanguage,
    status: str = WordStatus.NEW,
) -> UserWord | None:
    from services.level_progress_service import effective_difficulty

    word, was_created = await word_service.get_or_create_word(
        session,
        language_code=user_language.language_code,
        word=entry.word,
        part_of_speech=entry.part_of_speech,
        pronunciation=entry.pronunciation,
        phonetic=entry.phonetic,
        definition=entry.definition,
        difficulty=entry.difficulty or effective_difficulty(user_language),
        category=entry.category,
    )
    if was_created:
        for translation in entry.translations:
            await words_repo.add_translation(
                session, word_id=word.id, language_code=user_language.translation_language,
                translation=translation.translation, definition=entry.definition, usage_note=translation.usage_note,
            )
        for example in entry.examples:
            await words_repo.add_example(
                session, word_id=word.id, example_text=example.text, translation=example.translation,
                pronunciation=example.pronunciation,
            )
        if entry.part_of_speech == "verb" and entry.verb_forms:
            for form_type, form in entry.verb_forms.items():
                await words_repo.add_form(session, word_id=word.id, form_type=form_type, form=form)
    else:
        # Root cause of "перевод и пояснение не меняются после смены языка
        # интерфейса": the Word row already existed (e.g. another user
        # already added it) but may have no translation at all into THIS
        # user's translation_language yet - same on-demand backfill
        # word_service.ensure_translation already uses everywhere else.
        await word_service.ensure_translation(
            session, word, translation_language=user_language.translation_language, user_id=user.id
        )

    added = await user_word_service.add_word_to_learning(
        session, user_id=user.id, word_id=word.id, language_code=user_language.language_code, status=status
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
    category: str | None = None, industry: str | None = None, goal: str | None = None,
    known_words: list[str], performance_note: str | None = None, user_id: int,
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
            category=category,
            industry=industry,
            goal=goal,
            known_words=known_words,
            performance_note=performance_note,
            user_id=user_id,
        )
    except AIError as exc:
        logger.info("Word generation AI fallback unavailable for %r: %s", language_code, type(exc).__name__)
        return []

    return result.words


async def _performance_note(session: AsyncSession, *, user_id: int, user_language: UserLanguage) -> str | None:
    """Statistics/progress stage (spec sections 29-30): a short, plain-text
    summary of the learner's measured profile for the AI prompt - never a
    level for the AI to guess, only what services/learner_profile_service.py
    already computed from real UserWord/ReviewLog data. Never raises -
    word generation must keep working exactly as before if this fails."""
    try:
        profile = await learner_profile_service.build_learner_profile(
            session, user_id=user_id, user_language=user_language
        )
    except Exception:
        logger.exception("Learner profile build failed user_id=%s", user_id)
        return None

    parts = [
        f"accuracy={profile.accuracy:.0%}",
        f"recent_success_rate={profile.review_success_rate:.0%}",
        f"trend={profile.recent_performance}",
        f"active_words={profile.active_words}",
        f"mastered_words={profile.learned_words}",
    ]
    if profile.weak_words:
        parts.append(f"struggles with: {', '.join(profile.weak_words)}")
    if profile.strong_words:
        parts.append(f"has mastered: {', '.join(profile.strong_words)}")
    return "; ".join(parts)
