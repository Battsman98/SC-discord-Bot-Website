"""Copy the existing application SQLite database into PostgreSQL once.

Usage:
    python scripts/migrate_sqlite_to_postgres.py data/bot.sqlite3 "$DATABASE_URL"

Run this before directing either production service to the new database. Rows
that already exist are left unchanged, making an interrupted copy safe to retry.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.cache import SQLiteCache


def migrate(sqlite_path: Path, database_url: str) -> dict[str, int]:
    async def initialize_schema() -> None:
        cache = await SQLiteCache.create(database_url)
        await cache.close()

    asyncio.run(initialize_schema())
    source = sqlite3.connect(sqlite_path)
    destination = psycopg.connect(database_url)
    copied: dict[str, int] = {}
    try:
        tables = [
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
            rows = source.execute(
                f'SELECT * FROM "{table}"'  # table names come from sqlite_master
            ).fetchall()
            if not columns or not rows:
                copied[table] = 0
                continue
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            )
            with destination.cursor() as cursor:
                cursor.executemany(statement, rows)
            copied[table] = len(rows)

        for table in ("audit_events", "user_inventory_items", "user_refinery_orders"):
            if table not in tables:
                continue
            destination.execute(
                sql.SQL(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    "GREATEST(COALESCE(MAX(id), 0), 1), COALESCE(MAX(id), 0) > 0) FROM {}"
                ).format(sql.Identifier(table)),
                (table,),
            )
        destination.commit()
        return copied
    except Exception:
        destination.rollback()
        raise
    finally:
        source.close()
        destination.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("database_url")
    args = parser.parse_args()
    if not args.sqlite_path.is_file():
        parser.error(f"SQLite database does not exist: {args.sqlite_path}")
    copied = migrate(args.sqlite_path, args.database_url)
    for table, count in copied.items():
        print(f"{table}: {count} source rows processed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
