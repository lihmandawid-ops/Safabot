"""SQLAlchemy 2.x ORM models.

Only User and UserLanguage are defined here (Stage 4). Word and UserWord
(spec sections 7-8) belong to Stage 5 (Words) and are deliberately not
stubbed out here yet - an empty/placeholder table would just be dead
schema until the words feature lands, which the project's own rules
against faking unconnected work advise against.

`interface_language`, `learning_language` and `translation_language`
columns store one of the 8 codes in utils.languages.SUPPORTED_LANGUAGES,
kept as a plain string column (not a DB enum) so the value stays portable
across the SQLite -> PostgreSQL migration path (section 28).
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    interface_language: Mapped[str] = mapped_column(String(8), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    registration_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    current_level: Mapped[str] = mapped_column(String(32), nullable=False, default="beginner")
    daily_new_words_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    morning_notification_time: Mapped[time] = mapped_column(Time, nullable=False)
    afternoon_notification_time: Mapped[time] = mapped_column(Time, nullable=False)
    evening_notification_time: Mapped[time] = mapped_column(Time, nullable=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    trial_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    trial_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        String(16), nullable=False, default=SubscriptionStatus.FREE
    )
    subscription_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    languages: Mapped[list["UserLanguage"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"User(id={self.id}, telegram_id={self.telegram_id})"


class UserLanguage(Base):
    """Links a user to one language they are learning (spec section 6).

    A user has one row per language they study, e.g. ru->en and ru->de for
    the same account, each with its own level and daily word limit.
    """

    __tablename__ = "user_languages"
    __table_args__ = (
        UniqueConstraint("user_id", "language_code", name="uq_user_language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    language_code: Mapped[str] = mapped_column(String(8), nullable=False)
    translation_language: Mapped[str] = mapped_column(String(8), nullable=False)

    level: Mapped[str] = mapped_column(String(32), nullable=False, default="beginner")
    daily_word_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="languages")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"UserLanguage(user_id={self.user_id}, language_code={self.language_code!r})"
