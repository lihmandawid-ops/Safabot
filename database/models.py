"""SQLAlchemy 2.x ORM models.

Language is the source of truth for the 8 supported language codes
(seeded via database/seed.py and migrations/versions accordingly).
User.interface_language and UserLanguage.language_code/translation_language
are foreign keys into it, so a typo'd or unsupported code is rejected by
the database itself rather than silently accepted.

Word/WordTranslation/WordExample/WordForm are the shared, per-language
dictionary (spec section 1: same "gehen" in German and any homograph in
another language are different rows, kept apart by the
(language_code, normalized_word) unique constraint). UserWord is one
user's personal learning state for one Word - never mutate a Word row to
reflect a single user's progress.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class _StrEnum(str, enum.Enum):
    """Base for our string-backed enums.

    Plain `class X(str, Enum)` looks like a str but Enum's default
    __str__/__format__ renders "X.MEMBER", not the value - harmless once a
    value has round-tripped through the DB (SQLAlchemy hands back a plain
    str), but a real bug the moment code does `t(f"...{status}", ...)`
    right after setting `obj.status = WordStatus.PAUSED` in the same
    session, before any reload. Overriding __str__ here makes both cases
    render identically.
    """

    def __str__(self) -> str:  # noqa: D105
        return str(self.value)


class SubscriptionStatus(_StrEnum):
    """Section 24/25/26: where a user currently stands on PRO access."""

    TRIAL = "trial"
    FREE = "free"
    PRO = "pro"
    EXPIRED = "expired"


class WordStatus(_StrEnum):
    """Section 5: lifecycle of one UserWord (never the shared Word)."""

    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    PAUSED = "paused"
    MASTERED = "mastered"
    DELETED = "deleted"


class PartOfSpeech(_StrEnum):
    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    ADVERB = "adverb"
    PRONOUN = "pronoun"
    PREPOSITION = "preposition"
    CONJUNCTION = "conjunction"
    ARTICLE = "article"
    PARTICLE = "particle"
    PHRASE = "phrase"
    OTHER = "other"


class WordSource(_StrEnum):
    """Where a UserWord's underlying Word came from (bugfix spec section
    on manual add / generation): never a separate "manual database" - just
    a tag on the same Word/UserWord rows everything else uses."""

    DICTIONARY = "dictionary"
    MANUAL = "manual"
    GENERATED = "generated"
    OCR = "ocr"
    VOICE = "voice"
    AI = "ai"


class WordCategory(_StrEnum):
    """Section 18. Thematic sets are future work; this only tags words."""

    TRAVEL = "travel"
    WORK = "work"
    BUSINESS = "business"
    DAILY_LIFE = "daily_life"
    FOOD = "food"
    FAMILY = "family"
    TECHNOLOGY = "technology"
    TRANSPORT = "transport"
    HEALTH = "health"
    EDUCATION = "education"
    OTHER = "other"


class Language(Base):
    """One of the 8 languages Safabot supports (spec section 3).

    `code` is the primary key (e.g. "en", "ru") and is what User and
    UserLanguage foreign-key against - see utils/languages.py for the
    matching display metadata (flags) used by keyboards.
    """

    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    native_name: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Language(code={self.code!r})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    interface_language: Mapped[str] = mapped_column(
        ForeignKey("languages.code"), nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    level: Mapped[str] = mapped_column(String(32), nullable=False, default="a1")
    daily_new_words: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    morning_time: Mapped[time] = mapped_column(Time, nullable=False)
    afternoon_time: Mapped[time] = mapped_column(Time, nullable=False)
    evening_time: Mapped[time] = mapped_column(Time, nullable=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Per-slot toggles (repetition-system stage section 13): the single
    # notifications_enabled switch above stays the master on/off, these
    # three let a user keep e.g. only the morning reminder without
    # touching the other two times.
    morning_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    afternoon_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evening_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 📚 Настройки повторения (repetition-system stage sections 9, 26):
    # how many words go in one automatic reminder message (4/6/8), and
    # which mode manual review defaults to. review_mode=None means
    # "always ask" - the on-demand 🔁 Повторить flow's mode picker is
    # shown every time; once set to "flashcard"/"quiz"/"mixed" that
    # picker is skipped and the saved mode is used directly.
    notification_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    review_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)

    trial_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    trial_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        String(16), nullable=False, default=SubscriptionStatus.FREE
    )
    subscription_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    subscription_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Streak (spec section 23 of the learning-core stage): last_learning_date
    # is the user's own local calendar date of their last COMPLETED learning
    # session (see services/learning_service.py) - the streak logic reads
    # and updates these three together, never individually.
    last_learning_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    languages: Mapped[list["UserLanguage"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    words: Mapped[list["UserWord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    learning_sessions: Mapped[list["LearningSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"User(id={self.id}, telegram_id={self.telegram_id})"


class UserLanguage(Base):
    """Links a user to one language they are learning (spec section 4).

    A user has one row per (learning language, translation language) pair
    they study, e.g. ru->en and ru->de for the same account, each with its
    own level and daily word count. `is_current` marks the single language
    shown as ACTIVE in the main menu (spec section 13) - repository code
    is responsible for keeping at most one True per user.
    """

    __tablename__ = "user_languages"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "language_code", "translation_language", name="uq_user_language_pair"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)
    translation_language: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)

    # `level` doubles as the "estimated level" (level-and-difficulty
    # stage): set once at onboarding, from then on it's the ONE field
    # services.level_progress_service moves forward over time as the
    # learner's accumulated stats justify it - never a second
    # "estimated_level" column duplicating it (there's nothing else that
    # needs to know a level besides this evolving estimate).
    level: Mapped[str] = mapped_column(String(32), nullable=False, default="a1")
    # difficulty_mode="automatic" means word generation uses `level`
    # directly; "manual" means it uses `learning_difficulty` instead - the
    # learner's own pick from ⚙️ Настройки → "Уровень сложности изучения
    # языка", independent of (and never overwriting) the auto-tracked
    # `level`. See services.level_progress_service.effective_difficulty().
    difficulty_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    learning_difficulty: Mapped[str] = mapped_column(String(32), nullable=False, default="a1")
    daily_new_words: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Personalization (settings-improvements stage sections 17-23): why
    # this specific language is being learned, and - only meaningful when
    # learning_goal == "work" - which industry, so word_generation_service
    # can bias both the local-pool query and the AI prompt toward
    # relevant vocabulary. All three are optional and default to "not
    # set" (None/[]) precisely so the migration adding them never forces
    # existing users to answer anything retroactively.
    learning_goal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    work_industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="languages")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"UserLanguage(user_id={self.user_id}, language_code={self.language_code!r})"


class Word(Base):
    """One dictionary entry in one language (spec section 1).

    The (language_code, normalized_word) unique constraint is what keeps
    "gehen" in German and any lookalike word in another language from
    colliding - they're simply different rows, never merged.
    """

    __tablename__ = "words"
    __table_args__ = (
        UniqueConstraint("language_code", "normalized_word", name="uq_words_language_normalized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)

    word: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_word: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    part_of_speech: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pronunciation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phonetic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_verb: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Full, language-appropriate conjugation table (repetition-system
    # stage sections 18-25): {tense_name: ["I am", "You are", ...], ...}
    # - tense names are whatever's natural for this word's own language,
    # never forced into English's four. Cached here so 🔤 Все формы only
    # ever calls DeepSeek once per verb, not on every tap.
    verb_conjugation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    translations: Mapped[list["WordTranslation"]] = relationship(
        back_populates="word", cascade="all, delete-orphan"
    )
    examples: Mapped[list["WordExample"]] = relationship(
        back_populates="word", cascade="all, delete-orphan"
    )
    forms: Mapped[list["WordForm"]] = relationship(
        back_populates="word", cascade="all, delete-orphan"
    )
    user_words: Mapped[list["UserWord"]] = relationship(back_populates="word")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Word(id={self.id}, language_code={self.language_code!r}, word={self.word!r})"


class WordTranslation(Base):
    """One sense/translation of a Word (spec section 2) - a word can have
    several, e.g. "appointment" -> "встреча" / "запись" / "назначенная встреча"."""

    __tablename__ = "word_translations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), nullable=False, index=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)

    translation: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    word: Mapped[Word] = relationship(back_populates="translations")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"WordTranslation(word_id={self.word_id}, translation={self.translation!r})"


class WordExample(Base):
    """An example sentence for a Word (spec section 3)."""

    __tablename__ = "word_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), nullable=False, index=True)

    example_text: Mapped[str] = mapped_column(Text, nullable=False)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)

    word: Mapped[Word] = relationship(back_populates="examples")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"WordExample(word_id={self.word_id})"


class WordForm(Base):
    """A grammatical form of a Word, e.g. go/goes/went/gone/going (spec
    section 17). form_type is a free string on purpose - each language's
    morphology gets its own set of form types, added as that language's
    support is built out; nothing here assumes English's shape.
    """

    __tablename__ = "word_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), nullable=False, index=True)

    form_type: Mapped[str] = mapped_column(String(64), nullable=False)
    form: Mapped[str] = mapped_column(String(255), nullable=False)
    grammatical_info: Mapped[str | None] = mapped_column(String(255), nullable=True)

    word: Mapped[Word] = relationship(back_populates="forms")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"WordForm(word_id={self.word_id}, form_type={self.form_type!r}, form={self.form!r})"


class UserWord(Base):
    """One user's personal learning state for one Word (spec sections 4/5
    of this stage's brief). Never delete this row on user-facing "delete" -
    set status=DELETED instead, so a global Word already shared by other
    users is never touched and a deleted word can be silently restored if
    the user adds it again.
    """

    __tablename__ = "user_words"
    __table_args__ = (
        UniqueConstraint("user_id", "word_id", name="uq_user_word"),
        # The learning core's hot path: "give me this user's due words,
        # in one language, ordered by how overdue they are" (spec section
        # 28 calls out (user_id, next_review_at) specifically).
        Index("ix_user_words_user_next_review", "user_id", "next_review_at"),
        Index("ix_user_words_status", "status"),
        Index("ix_user_words_language_code", "language_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), nullable=False)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=WordStatus.NEW)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetition_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_answers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    difficulty_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # How this UserWord's Word ended up in the user's learning list (bugfix
    # spec): dictionary search, typed in manually, auto-generated, or
    # ingested via OCR/voice/AI - purely informational, never branched on
    # by the learning core itself.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=WordSource.DICTIONARY)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="words")
    word: Mapped[Word] = relationship(back_populates="user_words")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"UserWord(user_id={self.user_id}, word_id={self.word_id}, status={self.status!r})"


class LearningSession(Base):
    """One 📚 Учить слова / 🔄 Повторить run (spec section 24 of the
    learning-core stage). Persisted (never held only in
    context.user_data) so a bot restart mid-session loses nothing -
    handlers/learning.py always resolves "what's next" by reading this
    row and its items, never from in-memory state.
    """

    __tablename__ = "learning_sessions"
    __table_args__ = (
        Index("ix_learning_sessions_user_lang_status", "user_id", "language_code", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")

    total_words: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_words: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[User] = relationship(back_populates="learning_sessions")
    items: Mapped[list["LearningSessionItem"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="LearningSessionItem.position"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"LearningSession(id={self.id}, user_id={self.user_id}, status={self.status!r})"


class LearningSessionItem(Base):
    """One word's slot within a LearningSession, in display order.

    `is_new_word` records whether this slot was a NEW word at the moment
    the session was built - that, not any separate counter, is what the
    daily new-word limit (spec section 6) counts against, so the limit
    stays correct even if a session is abandoned and rebuilt.
    """

    __tablename__ = "learning_session_items"
    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_session_item_position"),
        UniqueConstraint("session_id", "user_word_id", name="uq_session_item_word"),
        Index("ix_session_items_session_completed", "session_id", "completed"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_word_id: Mapped[int] = mapped_column(
        ForeignKey("user_words.id", ondelete="CASCADE"), nullable=False
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_new_word: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rating: Mapped[str | None] = mapped_column(String(16), nullable=True)

    session: Mapped[LearningSession] = relationship(back_populates="items")
    user_word: Mapped[UserWord] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"LearningSessionItem(session_id={self.session_id}, position={self.position})"


class NotificationLog(Base):
    """Records that a daily notification was sent, so the scheduler
    (spec section 29) never sends the same slot twice for the same user
    on the same local day even if the poller runs more than once or the
    process restarts mid-day.
    """

    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "notification_type", "scheduled_date", name="uq_notification_once_per_day"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # UserWord ids actually shown in this notification (repetition-system
    # stage section 15) - lets the next notification for this user avoid
    # repeating the exact same set three times running. Null for
    # notifications that predate this field or never listed real words
    # (e.g. the evening "done for today" message).
    word_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"NotificationLog(user_id={self.user_id}, "
            f"type={self.notification_type!r}, date={self.scheduled_date})"
        )


class UserPhrase(Base):
    """One phrase a user saved from 💬 Полезные фразы (native-speaker
    phrasebook stage). `phrase`/`translation`/`pronunciation` follow the
    same Latin-only-pronunciation, learning_language-vs-interface_language
    separation as everywhere else in Safabot - `language_code` is the
    LEARNING language the phrase is written in, never the interface
    language. `normalized_phrase` reuses utils.text.normalize_word's
    lowercase+whitespace-collapse rule (works for a short phrase just as
    well as a single word) so a case-only variant of an already-saved
    phrase is recognized as a duplicate instead of creating a second row.
    """

    __tablename__ = "user_phrases"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "language_code", "normalized_phrase", name="uq_user_phrase"
        ),
        Index("ix_user_phrases_user_language", "user_id", "language_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)

    phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    translation: Mapped[str] = mapped_column(String(500), nullable=False)
    pronunciation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    register: Mapped[str | None] = mapped_column(String(32), nullable=True)
    situation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"UserPhrase(id={self.id}, user_id={self.user_id}, phrase={self.phrase!r})"


class PopularPhrase(Base):
    """An AI-generated 🔥 Популярные фразы entry (✨ Сгенерировать ещё,
    native-speaker phrasebook stage) - the phrase itself and its own
    Latin-only pronunciation, both tied to `language_code` only, never to
    any viewer's interface/translation language (same separation
    utils.popular_phrases.POPULAR_PHRASES's static seed set already
    follows). Kept as its own table, separate from that static Python
    data, since the seed set is code (reviewed, stable, ships with the
    app) while these rows are runtime, per-language, ever-growing AI
    output - conflating the two would mean a code deploy could silently
    reorder or duplicate what's actually a growing database.

    phrase_service.get_translated_popular_phrases() presents both sources
    as ONE combined, stably-ordered list (every static entry first, in
    their fixed tuple order, then every PopularPhrase row in ascending id
    order) - see PopularPhraseTranslation below for why that combined
    ordering has to stay stable forever.
    """

    __tablename__ = "popular_phrases"
    __table_args__ = (
        UniqueConstraint("language_code", "normalized_phrase", name="uq_popular_phrase"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)
    phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_phrase: Mapped[str] = mapped_column(String(500), nullable=False)
    pronunciation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"PopularPhrase(id={self.id}, language_code={self.language_code!r}, phrase={self.phrase!r})"


class PopularPhraseTranslation(Base):
    """Cached translation for one entry of the COMBINED popular-phrase list
    (native-speaker phrasebook stage, 🔥 Популярные фразы bugfix + ✨
    Сгенерировать ещё) - utils.popular_phrases.POPULAR_PHRASES' static
    seed entries followed by PopularPhrase's AI-generated rows, in that
    stable combined order (see PopularPhrase's docstring). Each entry's
    phrase text and Latin pronunciation need no AI/DB round-trip; only
    the TRANSLATION varies per viewer's translation_language, so it's the
    only part cached here - one row per (language_code,
    translation_language, phrase_index) triple, filled in a single batch
    AI call the first time that pair is ever requested and reused by
    every user and every later view after that (never regenerated, never
    a live call on pagination). A freshly generated phrase's translation
    (already returned by the same AI call that created it) is written
    here directly too, so the very user who generated it never triggers
    a second translation call for their own translation_language.
    """

    __tablename__ = "popular_phrase_translations"
    __table_args__ = (
        UniqueConstraint(
            "language_code", "translation_language", "phrase_index", name="uq_popular_phrase_translation"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)
    translation_language: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)
    phrase_index: Mapped[int] = mapped_column(Integer, nullable=False)
    translation: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"PopularPhraseTranslation(language_code={self.language_code!r}, "
            f"translation_language={self.translation_language!r}, phrase_index={self.phrase_index})"
        )


class WordGenerationLog(Base):
    """One call to word_generation_service.generate_new_words (bugfix spec:
    "для контроля использования AI и затрат") - logged even when the local
    word pool covered everything and no AI provider was actually called
    (provider="local"/"none"), so usage can be audited either way.
    """

    __tablename__ = "word_generation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), nullable=False)
    requested_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # What asked for this generation (bugfix stage): "daily_quota" (the
    # normal 📚 Учить слова auto-fill), "extra_request" (➕ Ещё новые
    # слова, counted separately against MAX_EXTRA_WORDS_PER_DAY), or
    # "replacement" (🤔 Я это уже знаю's one-word swap).
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="daily_quota")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"WordGenerationLog(user_id={self.user_id}, language_code={self.language_code!r}, "
            f"requested={self.requested_amount}, generated={self.generated_amount})"
        )
