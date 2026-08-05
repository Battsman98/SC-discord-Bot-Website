"""Small DB-API compatibility layer for running the SQLite cache on PostgreSQL.

The application cache deliberately uses a conservative subset of SQL.  This
adapter translates that subset so the existing persistence API can be migrated
without coupling callers to a particular database driver.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


_INSERT_ID_TABLES = {"user_inventory_items", "user_refinery_orders"}


def _translate_sql(sql: str) -> str:
    translated = sql
    translated = re.sub(
        r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
        "BIGSERIAL PRIMARY KEY",
        translated,
        flags=re.IGNORECASE,
    )
    # SQLite INTEGER accepts 64-bit Discord snowflakes and Unix timestamps.
    # PostgreSQL INTEGER is only 32-bit, so preserve SQLite's effective range.
    if re.match(r"\s*(CREATE|ALTER)\s+TABLE\b", translated, re.IGNORECASE):
        translated = re.sub(r"\bINTEGER\b", "BIGINT", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\s+COLLATE\s+NOCASE", "", translated, flags=re.IGNORECASE)
    translated = translated.replace("?", "%s")
    return translated


class PostgresCursor:
    def __init__(self, cursor: Any, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()


class PostgresConnection:
    """Expose the sqlite3 connection methods used by :mod:`src.cache`."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @classmethod
    def connect(cls, database_url: str) -> "PostgresConnection":
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - exercised in production setup
            raise RuntimeError(
                "PostgreSQL requires psycopg. Install the production requirements first."
            ) from error
        # Most cache reads intentionally run outside an explicit transaction,
        # matching sqlite3's behavior in this application.  Autocommit keeps a
        # failed standalone statement from poisoning the shared connection
        # until a later, unrelated operation happens to call rollback().
        return cls(psycopg.connect(database_url, autocommit=True))

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> PostgresCursor:
        pragma = re.fullmatch(r"\s*PRAGMA\s+table_info\((\w+)\)\s*", sql, re.IGNORECASE)
        if pragma:
            cursor = self._connection.execute(
                """
                SELECT ordinal_position - 1, column_name, data_type, 0, NULL, 0
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = %s
                ORDER BY ordinal_position
                """,
                (pragma.group(1),),
            )
            return PostgresCursor(cursor)
        if re.match(r"\s*PRAGMA\s+", sql, re.IGNORECASE):
            return PostgresCursor(self._connection.execute("SELECT 1 WHERE FALSE"))

        translated = _translate_sql(sql)
        insert = re.match(r"\s*INSERT\s+INTO\s+(\w+)", translated, re.IGNORECASE)
        wants_id = bool(insert and insert.group(1).lower() in _INSERT_ID_TABLES)
        if wants_id and " RETURNING " not in translated.upper():
            translated = f"{translated.rstrip().rstrip(';')} RETURNING id"
        cursor = self._connection.execute(translated, tuple(parameters))
        lastrowid = int(cursor.fetchone()[0]) if wants_id else None
        return PostgresCursor(cursor, lastrowid)

    def executemany(self, sql: str, parameters: Iterable[Iterable[Any]]) -> PostgresCursor:
        cursor = self._connection.cursor()
        cursor.executemany(_translate_sql(sql), parameters)
        return PostgresCursor(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self._connection.rollback()
        return False
