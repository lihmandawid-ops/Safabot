"""SQLAlchemy 2.x ORM models.

Word and UserWord (spec sections 7-8 of the original brief) belong to
Stage 5 (Words) and are deliberately not stubbed out here yet - an empty
placeholder table would just be dead schema until the words feature
lands, which the project's own rules against faking unconnected work
advise against.

Language is the source of truth for the 8 supported language codes
(seeded via database/seed.py and migrations/versions accordingly).
User.interface_language and UserLanguage.language_code/translation_language
are foreign keys into it, so a typo'd or unsupported code is rejected by
the database itself rather than silently accepted.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SubscriptionStatus(str, enum.Enum):
    """Section 24/25/26: where a user currently stands on PRO access."""

    TRIAL = "trial"
    FREE = "free"
    PRO = "pro"
    EXPIRED = "expired"


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

    level: Mapped[str] = mapped_column(String(32), nullable=False, default="beginner")
    daily_new_words: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    morning_time: Mapped[time] = mapped_column(Time, nullable=False)
    afternoon_time: Mapped[time] = mapped_column(Time, nullable=False)
    evening_time: Mapped[time] = mapped_column(Time, nullable=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    trial_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    trial_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        String(16), nullable=False, default=SubscriptionStatus.FREE
    )
    subscription_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    subscription_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    languages: Mapped[list["UserLanguage"]] = relationship(
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

    level: Mapped[str] = mapped_column(String(32), nullable=False, default="beginner")
    daily_new_words: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="languages")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"UserLanguage(user_id={self.user_id}, language_code={self.language_code!r})"
