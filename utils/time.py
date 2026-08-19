"""Naive-UTC time convention used throughout the learning core.

SQLite (via aiosqlite) strips tzinfo from any `DateTime(timezone=True)`
column on read-back regardless of what was written - verified empirically
against this project's engine setup. Comparing a freshly-fetched (naive)
value against `datetime.now(timezone.utc)` (aware) works for SQL-side
filtering (SQLAlchemy just binds the parameter) but raises TypeError the
moment either value is used in Python-side arithmetic together. Rather
than track which flavor a given datetime happens to be, every datetime
this project's own code creates - for storage or for "now" - is naive and
represents UTC. Never mix in `datetime.now()` (local time) or a
tz-aware value.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    """The current instant, as a naive datetime representing UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_day_bounds(now_utc: datetime, tz_name: str) -> tuple[datetime, datetime]:
    """The [start, end) of "today" in `tz_name`, expressed as naive-UTC
    datetimes - used for daily-limit and streak calculations so a
    day boundary always matches the user's own midnight, not the
    server's (spec sections 6, 22-23: crossing midnight must not corrupt
    the daily new-word count or the streak).
    """
    aware_utc = now_utc.replace(tzinfo=timezone.utc) if now_utc.tzinfo is None else now_utc
    local_now = aware_utc.astimezone(ZoneInfo(tz_name))
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_next_midnight = local_midnight + timedelta(days=1)
    start = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    end = local_next_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def local_today(now_utc: datetime, tz_name: str) -> date:
    """The calendar date of "now" in the user's own timezone."""
    aware_utc = now_utc.replace(tzinfo=timezone.utc) if now_utc.tzinfo is None else now_utc
    return aware_utc.astimezone(ZoneInfo(tz_name)).date()


def local_hour_minute(now_utc: datetime, tz_name: str) -> tuple[int, int]:
    """(hour, minute) of "now" in the user's own timezone - used by the
    notification scheduler to match against a user's stored HH:MM slot."""
    aware_utc = now_utc.replace(tzinfo=timezone.utc) if now_utc.tzinfo is None else now_utc
    local_now = aware_utc.astimezone(ZoneInfo(tz_name))
    return local_now.hour, local_now.minute
