#!/usr/bin/env python3
"""Post-migration integrity check for Safabot's SQLite -> PostgreSQL
migration (Postgres-migration PHASE 1, steps 9-10).

Never considers the migration successful just because PostgreSQL starts
- it re-derives the row counts from the SQLite backup (or reads the
`.counts.json` sidecar deploy/backup_sqlite.py already wrote) and
compares every table's count against the live target database, then
runs a handful of migration-specific integrity checks the raw counts
alone wouldn't catch: payments idempotency key uniqueness, the
duplicate-notification UNIQUE constraint, and Telegram user id
uniqueness.

Exits non-zero (and prints exactly what disagreed) if anything doesn't
match - a clean run is the only thing this script will call a pass.

Usage:
    python deploy/verify_migration.py \\
        --counts-file backups/safabot_sqlite_20260101_120000.counts.json \\
        --target-url "postgresql+asyncpg://safabot_app:PASSWORD@localhost:5432/safabot"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models import Base  # noqa: E402


def counts_from_sqlite(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' "
                "ORDER BY name"
            ).fetchall()
        ]
        return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
    finally:
        conn.close()


async def counts_from_postgres(target_url: str) -> dict[str, int]:
    engine = create_async_engine(target_url)
    try:
        async with engine.connect() as conn:
            counts = {}
            for table in Base.metadata.sorted_tables:
                counts[table.name] = await conn.scalar(select(func.count()).select_from(table))
            return counts
    finally:
        await engine.dispose()


async def integrity_checks(target_url: str) -> list[str]:
    """Checks that go beyond raw row counts - things a count match alone
    wouldn't catch (e.g. two source rows landing on the same key)."""
    problems: list[str] = []
    engine = create_async_engine(target_url)
    try:
        async with engine.connect() as conn:
            total_payments = await conn.scalar(text("SELECT COUNT(*) FROM payments"))
            distinct_charges = await conn.scalar(text("SELECT COUNT(DISTINCT telegram_charge_id) FROM payments"))
            if total_payments != distinct_charges:
                problems.append(
                    f"payments.telegram_charge_id is not unique after migration: "
                    f"{total_payments} rows but only {distinct_charges} distinct charge ids "
                    f"- Telegram Stars idempotency would be broken."
                )

            total_users = await conn.scalar(text("SELECT COUNT(*) FROM users"))
            distinct_telegram_ids = await conn.scalar(text("SELECT COUNT(DISTINCT telegram_id) FROM users"))
            if total_users != distinct_telegram_ids:
                problems.append(
                    f"users.telegram_id is not unique after migration: "
                    f"{total_users} rows but only {distinct_telegram_ids} distinct telegram ids."
                )

            total_notifs = await conn.scalar(text("SELECT COUNT(*) FROM notification_logs"))
            distinct_notif_keys = await conn.scalar(
                text("SELECT COUNT(DISTINCT (user_id, notification_type, scheduled_date)) FROM notification_logs")
            )
            if total_notifs != distinct_notif_keys:
                problems.append(
                    f"notification_logs' (user_id, notification_type, scheduled_date) is not unique "
                    f"after migration: {total_notifs} rows but only {distinct_notif_keys} distinct keys "
                    f"- duplicate-notification protection would be broken."
                )
    finally:
        await engine.dispose()
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counts-file", help="Path to a .counts.json file written by deploy/backup_sqlite.py")
    parser.add_argument("--sqlite-file", help="Alternative to --counts-file: recompute counts directly from a SQLite backup file")
    parser.add_argument("--target-url", required=True, help="PostgreSQL DSN to verify against")
    args = parser.parse_args()

    if not args.counts_file and not args.sqlite_file:
        print("ERROR: pass either --counts-file or --sqlite-file.", file=sys.stderr)
        sys.exit(1)

    if args.counts_file:
        source_counts = json.loads(Path(args.counts_file).read_text())
    else:
        source_counts = counts_from_sqlite(Path(args.sqlite_file))

    target_counts = asyncio.run(counts_from_postgres(args.target_url))

    print(f"{'table':<32}{'sqlite':>10}{'postgres':>10}{'':>6}")
    print("-" * 58)
    mismatches: list[str] = []
    all_tables = sorted(set(source_counts) | set(target_counts))
    for table in all_tables:
        src = source_counts.get(table, 0)
        tgt = target_counts.get(table, 0)
        status = "OK" if src == tgt else "MISMATCH"
        print(f"{table:<32}{src:>10}{tgt:>10}{status:>10}")
        if src != tgt:
            mismatches.append(f"{table}: sqlite={src} postgres={tgt}")

    print("\n==> Running integrity checks (idempotency keys, duplicate-notification uniqueness)...")
    problems = asyncio.run(integrity_checks(args.target_url))
    for problem in problems:
        print(f"  FAIL: {problem}")
    if not problems:
        print("  All integrity checks passed.")

    if mismatches or problems:
        print("\nVERIFICATION FAILED. Do not switch production to this PostgreSQL database.")
        for m in mismatches:
            print(f"  Row count mismatch: {m}")
        sys.exit(1)

    print("\nVERIFICATION PASSED: every table's row count matches, all integrity checks passed.")
    print("Only after this passes is it safe to update DATABASE_URL and restart the bot.")


if __name__ == "__main__":
    main()
