#!/usr/bin/env python3
"""One-shot SQLite -> PostgreSQL data migration for Safabot (Postgres-
migration PHASE 1, steps 6-8).

Never writes to the source database - only ever SELECTs from it. Reuses
the project's OWN Alembic migration history to build the target schema
(never a fresh create_all()), then copies every table's rows across in
dependency order using SQLAlchemy's `Base.metadata.sorted_tables` (the
same ordering the ORM's own foreign keys already imply, no hand-written
table list to keep in sync), preserving every primary key exactly as it
was in SQLite, then resets each PostgreSQL sequence so the next normal
insert continues from the right number instead of colliding.

Refuses to run against a target that already has data, unless --force
is passed - this script is meant to run against a freshly-migrated
(alembic upgrade head, empty) PostgreSQL database exactly once per
environment, never as a repeatable sync.

Usage:
    python deploy/migrate_to_postgres.py \\
        --source-url "sqlite+aiosqlite:///backups/safabot_sqlite_20260101_120000.db" \\
        --target-url "postgresql+asyncpg://safabot_app:PASSWORD@localhost:5432/safabot"

Always migrate from a BACKUP file (deploy/backup_sqlite.py's output),
never from the live database the bot is still writing to - a backup is
an atomic snapshot; the live file can change mid-copy.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models import Base  # noqa: E402

CHUNK_SIZE = 1000

# migrations/versions/cc37901c0d0f_...py bulk-inserts the 8 supported
# languages directly as part of the schema migration itself (fixed
# reference data, never user-editable) - so `alembic upgrade head` alone
# already leaves an identical, correct copy of this table in the target.
# Copying it again from the source would collide on the same primary
# keys; skipping it here is not "losing data", it's recognizing the
# target already has it.
SKIP_TABLES = {"languages"}


def run_target_migrations(target_url: str) -> None:
    """Builds the target schema through the project's real Alembic
    history (never a fresh create_all()) - the exact same migrations
    already applied to every SQLite deployment, so the resulting schema
    is provably identical, not a hand-recreated approximation."""
    print("==> Running Alembic migrations against the target database...")
    env = {**os.environ, "DATABASE_URL": target_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
    )
    if result.returncode != 0:
        print("ERROR: alembic upgrade head failed against the target database.", file=sys.stderr)
        sys.exit(1)
    print("    Schema is up to date.")


async def _target_is_empty(target_url: str) -> bool:
    engine = create_async_engine(target_url)
    try:
        async with engine.connect() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name in SKIP_TABLES:
                    continue
                count = await conn.scalar(select(func.count()).select_from(table))
                if count:
                    return False
        return True
    finally:
        await engine.dispose()


async def migrate_data(source_url: str, target_url: str) -> dict[str, int]:
    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(target_url)
    counts: dict[str, int] = {}

    try:
        async with source_engine.connect() as src_conn, target_engine.begin() as tgt_conn:
            # Base.metadata.sorted_tables is already topologically sorted
            # by foreign key so every parent row (users, languages, words)
            # lands before the child rows that reference it - no
            # hand-maintained table order to drift out of sync with the
            # real schema.
            for table in Base.metadata.sorted_tables:
                if table.name in SKIP_TABLES:
                    print(f"  {table.name:<32}{'skipped (seeded by migrations)':>34}")
                    continue

                result = await src_conn.execute(select(table))
                rows = [dict(row._mapping) for row in result.fetchall()]
                counts[table.name] = len(rows)
                if not rows:
                    print(f"  {table.name:<32}{'0 rows (skipped)':>20}")
                    continue

                for i in range(0, len(rows), CHUNK_SIZE):
                    chunk = rows[i : i + CHUNK_SIZE]
                    await tgt_conn.execute(table.insert(), chunk)

                # Explicit-PK inserts don't advance PostgreSQL's identity
                # sequence - the very next ordinary insert (a real new
                # user registering) would otherwise collide with the
                # highest id just copied in.
                pk_cols = [c for c in table.primary_key.columns if c.autoincrement is not False]
                for pk in pk_cols:
                    await tgt_conn.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk.name}'), "
                            f"COALESCE((SELECT MAX({pk.name}) FROM {table.name}), 1), "
                            f"(SELECT MAX({pk.name}) FROM {table.name}) IS NOT NULL)"
                        )
                    )
                print(f"  {table.name:<32}{len(rows):>10} rows")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-url", required=True, help="SQLite DSN of a BACKUP file, e.g. sqlite+aiosqlite:///backups/safabot_sqlite_....db")
    parser.add_argument("--target-url", required=True, help="PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host:5432/safabot")
    parser.add_argument("--force", action="store_true", help="Proceed even if the target database already has data (DANGEROUS - will duplicate rows)")
    args = parser.parse_args()

    if not args.source_url.startswith("sqlite"):
        print("ERROR: --source-url must be a sqlite+aiosqlite DSN.", file=sys.stderr)
        sys.exit(1)
    if not args.target_url.startswith("postgresql"):
        print("ERROR: --target-url must be a postgresql(+asyncpg) DSN.", file=sys.stderr)
        sys.exit(1)

    run_target_migrations(args.target_url)

    if not args.force and not asyncio.run(_target_is_empty(args.target_url)):
        print(
            "ERROR: the target database already has data in it. Refusing to migrate into it "
            "(this would duplicate every row). Use a freshly-migrated, empty database, or pass "
            "--force if you have already verified it's safe to proceed.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\n==> Copying data (source -> target, in foreign-key order)...")
    counts = asyncio.run(migrate_data(args.source_url, args.target_url))

    print(f"\n{'table':<32}{'rows copied':>15}")
    print("-" * 47)
    for table, count in counts.items():
        print(f"{table:<32}{count:>15}")
    print("-" * 47)
    print(f"{'TOTAL':<32}{sum(counts.values()):>15}")
    print(
        "\nData copy complete. Do NOT switch production DATABASE_URL yet - "
        "run deploy/verify_migration.py first to confirm the target matches the backup."
    )


if __name__ == "__main__":
    main()
