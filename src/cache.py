import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SQLiteCache:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    async def create(cls, database_path: str) -> "SQLiteCache":
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                title TEXT NOT NULL,
                fields_json TEXT NOT NULL
            )
            """
        )
        connection.commit()
        return cls(connection)

    async def get(self, cache_key: str) -> Any | None:
        row = self._connection.execute(
            "SELECT value_json, expires_at FROM cache_entries WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

        if row is None:
            return None

        value_json, expires_at = row
        if expires_at <= int(time.time()):
            self._connection.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
            self._connection.commit()
            return None

        return json.loads(value_json)

    async def set(self, cache_key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = int(time.time()) + ttl_seconds
        self._connection.execute(
            """
            INSERT INTO cache_entries (cache_key, value_json, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                value_json = excluded.value_json,
                expires_at = excluded.expires_at
            """,
            (cache_key, json.dumps(value), expires_at),
        )
        self._connection.commit()

    async def delete(self, cache_key: str) -> None:
        self._connection.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
        self._connection.commit()

    async def add_audit_event(self, title: str, fields: dict[str, Any]) -> None:
        now = int(time.time())
        clean_fields = {str(key): str(value) for key, value in fields.items()}
        self._connection.execute(
            """
            INSERT INTO audit_events (created_at, title, fields_json)
            VALUES (?, ?, ?)
            """,
            (now, title, json.dumps(clean_fields)),
        )
        self._connection.execute(
            """
            DELETE FROM audit_events
            WHERE id NOT IN (
                SELECT id FROM audit_events
                ORDER BY id DESC
                LIMIT 1000
            )
            """
        )
        self._connection.commit()

    async def recent_audit_events(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT id, created_at, title, fields_json
            FROM audit_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 25)),),
        ).fetchall()
        return [
            {
                "id": row[0],
                "created_at": row[1],
                "title": row[2],
                "fields": json.loads(row[3]),
            }
            for row in rows
        ]

    async def close(self) -> None:
        self._connection.close()
