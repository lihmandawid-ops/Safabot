#!/usr/bin/env python3
"""Online-safe SQLite backup for Safabot (Postgres-migration PHASE 1, step 2).

Uses the stdlib sqlite3 backup API - the same mechanism the `sqlite3 ...
".backup"` CLI command uses, safe to run against a database the bot
process is still writing to (a consistent snapshot, never a raw file
copy of a live database). Never deletes or modifies the source file.

Usage (run from the app directory, same one bot.py runs from):
    python deploy/backup_sqlite.py
    python deploy/backup_sqlite.py --source /opt/safabot/app/safabot.db --backups-dir /opt/safabot/backups

Writes <backups-dir>/safabot_sqlite_<UTC timestamp>.db, then verifies it
by actually opening the COPY (never the live source again) and counting
rows per table - printed to stdout and saved as a `.counts.json`
sidecar next to the backup, so deploy/verify_migration.py can compare
against it later without needing the original SQLite file at hand.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def backup(source: Path, backups_dir: Path) -> Path:
    if not source.exists():
        print(f"ERROR: source database not found: {source}", file=sys.stderr)
        sys.exit(1)

    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = backups_dir / f"safabot_sqlite_{timestamp}.db"

    # Opening the source read-only (mode=ro) is an extra guarantee this
    # script can never itself write to the live database, on top of the
    # backup API already being safe to run concurrently with the bot.
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dest_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()

    return dest


def verify(backup_path: Path) -> dict[str, int]:
    size = backup_path.stat().st_size
    if size == 0:
        print(f"ERROR: backup file is empty: {backup_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' "
                "ORDER BY name"
            ).fetchall()
        ]
        if not tables:
            print(f"ERROR: backup opens but has no application tables: {backup_path}", file=sys.stderr)
            sys.exit(1)
        counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
    finally:
        conn.close()

    print(f"Backup verified: {backup_path} ({size:,} bytes)")
    print(f"\n{'table':<32}{'rows':>10}")
    print("-" * 42)
    for table, count in counts.items():
        print(f"{table:<32}{count:>10}")
    print("-" * 42)
    print(f"{'TOTAL':<32}{sum(counts.values()):>10}")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="safabot.db", help="Path to the live SQLite database file")
    parser.add_argument("--backups-dir", default="backups", help="Directory to write the timestamped backup into")
    args = parser.parse_args()

    dest = backup(Path(args.source), Path(args.backups_dir))
    counts = verify(dest)

    counts_path = dest.with_suffix(".counts.json")
    counts_path.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")

    print(f"\nBackup file:  {dest}")
    print(f"Row counts:   {counts_path}")
    print("\nDo not delete this backup until the PostgreSQL migration has been verified and production has run on it for a full rollback-window period.")


if __name__ == "__main__":
    main()
