import json
import sqlite3
import time
from pathlib import Path
from typing import Any


AUDIT_ACTION_TYPES = {
    "admin", "audit", "authentication", "blueprints", "commands", "inventory",
    "items", "mining", "other", "ships", "timers", "trade", "updates",
}


def normalize_audit_action_type(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "blueprint": "blueprints", "command": "commands", "inventory search": "inventory",
        "item": "items", "item locator": "items", "ship": "ships", "timer": "timers",
        "cz timer": "timers", "exec": "timers", "commodity": "trade", "trade routing": "trade",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in AUDIT_ACTION_TYPES else None


def audit_action_type(title: str, fields: dict[str, Any]) -> str:
    command = str(fields.get("Command") or fields.get("Action") or "").strip().lower().removeprefix("/")
    first_command = command.split()[0] if command else ""
    explicit = normalize_audit_action_type(first_command) or normalize_audit_action_type(command)
    if explicit:
        return explicit

    text = " ".join([title, command]).lower()
    keywords = (
        ("authentication", ("login", "logout", "oauth", "authentication")),
        ("inventory", ("inventory",)),
        ("blueprints", ("blueprint", "crafting")),
        ("mining", ("mining", "material location")),
        ("ships", ("ship", "hangar", "pledge")),
        ("trade", ("trade", "commodity")),
        ("items", ("item locator", "item search")),
        ("timers", ("timer", "executive", "exec ", "contested zone", "cz ")),
        ("audit", ("audit",)),
        ("updates", ("updates", "patch notes", "server status", "sneak peek", "leak")),
        ("admin", ("admin", "command blocked")),
        ("commands", ("command",)),
    )
    for action_type, terms in keywords:
        if any(term in text for term in terms):
            return action_type
    return "other"


class SQLiteCache:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    async def create(cls, database_path: str) -> "SQLiteCache":
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
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
                action_type TEXT NOT NULL DEFAULT 'other',
                fields_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_blueprints (
                user_id INTEGER NOT NULL,
                blueprint_name TEXT NOT NULL,
                category TEXT,
                source_name TEXT,
                source_url TEXT,
                saved_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, blueprint_name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_ships (
                user_id INTEGER NOT NULL,
                ship_name TEXT NOT NULL,
                ownership_type TEXT NOT NULL,
                manufacturer TEXT,
                role TEXT,
                source_name TEXT,
                source_url TEXT,
                image_url TEXT,
                notes TEXT,
                loaner_for TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                saved_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, ship_name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                category TEXT,
                location TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 1,
                quality REAL,
                item_type TEXT,
                item_size TEXT,
                volume_scu REAL,
                notes TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )
        cls._ensure_column(connection, "user_ships", "image_url", "TEXT")
        cls._ensure_column(connection, "user_ships", "notes", "TEXT")
        cls._ensure_column(connection, "user_ships", "loaner_for", "TEXT")
        cls._ensure_column(connection, "user_ships", "quantity", "INTEGER NOT NULL DEFAULT 1")
        cls._ensure_column(connection, "user_inventory_items", "quality", "REAL")
        cls._ensure_column(connection, "user_inventory_items", "item_type", "TEXT")
        cls._ensure_column(connection, "user_inventory_items", "item_size", "TEXT")
        cls._ensure_column(connection, "user_inventory_items", "volume_scu", "REAL")
        cls._ensure_column(connection, "audit_events", "action_type", "TEXT NOT NULL DEFAULT 'other'")
        cls._backfill_audit_action_types(connection)
        connection.commit()
        return cls(connection)

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    @staticmethod
    def _backfill_audit_action_types(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT id, title, fields_json FROM audit_events WHERE action_type IS NULL OR action_type = 'other'"
        ).fetchall()
        for event_id, title, fields_json in rows:
            try:
                fields = json.loads(fields_json)
            except (TypeError, json.JSONDecodeError):
                fields = {}
            action_type = audit_action_type(str(title), fields if isinstance(fields, dict) else {})
            connection.execute(
                "UPDATE audit_events SET action_type = ? WHERE id = ?",
                (action_type, event_id),
            )

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

    async def add_audit_event(
        self,
        title: str,
        fields: dict[str, Any],
        action_type: str | None = None,
    ) -> None:
        now = int(time.time())
        clean_fields = {str(key): str(value) for key, value in fields.items()}
        clean_action_type = normalize_audit_action_type(action_type) or audit_action_type(title, clean_fields)
        self._connection.execute(
            """
            INSERT INTO audit_events (created_at, title, action_type, fields_json)
            VALUES (?, ?, ?, ?)
            """,
            (now, title, clean_action_type, json.dumps(clean_fields)),
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

    async def recent_audit_events(
        self,
        limit: int = 10,
        action_type: str | None = None,
        sort_order: str = "newest",
    ) -> list[dict[str, Any]]:
        clean_action_type = normalize_audit_action_type(action_type)
        where = "WHERE action_type = ?" if clean_action_type else ""
        values: list[Any] = [clean_action_type] if clean_action_type else []
        order_clause = (
            "action_type ASC, id DESC"
            if sort_order == "action"
            else f"id {'ASC' if sort_order == 'oldest' else 'DESC'}"
        )
        values.append(max(1, min(limit, 100)))
        rows = self._connection.execute(
            f"""
            SELECT id, created_at, title, action_type, fields_json
            FROM audit_events
            {where}
            ORDER BY {order_clause}
            LIMIT ?
            """,
            values,
        ).fetchall()
        return [
            {
                "id": row[0],
                "created_at": row[1],
                "title": row[2],
                "action_type": row[3],
                "fields": json.loads(row[4]),
            }
            for row in rows
        ]


    async def user_blueprints(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT blueprint_name, category, source_name, source_url, saved_at
            FROM user_blueprints
            WHERE user_id = ?
            ORDER BY blueprint_name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
        return [
            {
                "name": row[0],
                "category": row[1],
                "source_name": row[2],
                "source_url": row[3],
                "saved_at": row[4],
            }
            for row in rows
        ]

    async def save_user_blueprint(
        self,
        user_id: int,
        blueprint_name: str,
        category: str | None,
        source_name: str | None,
        source_url: str | None,
    ) -> None:
        now = int(time.time())
        self._connection.execute(
            """
            INSERT INTO user_blueprints (user_id, blueprint_name, category, source_name, source_url, saved_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, blueprint_name) DO UPDATE SET
                category = excluded.category,
                source_name = excluded.source_name,
                source_url = excluded.source_url,
                saved_at = excluded.saved_at
            """,
            (user_id, blueprint_name, category, source_name, source_url, now),
        )
        self._connection.commit()

    async def delete_user_blueprint(self, user_id: int, blueprint_name: str) -> None:
        self._connection.execute(
            "DELETE FROM user_blueprints WHERE user_id = ? AND blueprint_name = ?",
            (user_id, blueprint_name),
        )
        self._connection.commit()

    async def user_ships(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT ship_name, ownership_type, manufacturer, role, source_name, source_url, image_url, notes, loaner_for, quantity, saved_at
            FROM user_ships
            WHERE user_id = ?
            ORDER BY loaner_for IS NOT NULL, ship_name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
        return [
            {
                "name": row[0],
                "ownership_type": row[1],
                "manufacturer": row[2],
                "role": row[3],
                "source_name": row[4],
                "source_url": row[5],
                "image_url": row[6],
                "notes": row[7],
                "loaner_for": row[8],
                "quantity": max(1, int(row[9] or 1)),
                "saved_at": row[10],
            }
            for row in rows
        ]

    async def save_user_ship(
        self,
        user_id: int,
        ship_name: str,
        ownership_type: str,
        manufacturer: str | None,
        role: str | None,
        source_name: str | None,
        source_url: str | None,
        image_url: str | None = None,
        notes: str | None = None,
        loaner_for: str | None = None,
        quantity: int | None = None,
    ) -> None:
        now = int(time.time())
        self._connection.execute(
            """
            INSERT INTO user_ships (
                user_id, ship_name, ownership_type, manufacturer, role, source_name, source_url,
                image_url, notes, loaner_for, quantity, saved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 1), ?)
            ON CONFLICT(user_id, ship_name) DO UPDATE SET
                ownership_type = excluded.ownership_type,
                manufacturer = excluded.manufacturer,
                role = excluded.role,
                source_name = excluded.source_name,
                source_url = excluded.source_url,
                image_url = excluded.image_url,
                notes = excluded.notes,
                loaner_for = excluded.loaner_for,
                quantity = CASE WHEN ? IS NULL THEN user_ships.quantity ELSE excluded.quantity END,
                saved_at = excluded.saved_at
            """,
            (user_id, ship_name, ownership_type, manufacturer, role, source_name, source_url, image_url, notes, loaner_for, quantity, now, quantity),
        )
        self._connection.commit()

    async def delete_user_ship(self, user_id: int, ship_name: str) -> None:
        self._connection.execute(
            "DELETE FROM user_ships WHERE user_id = ? AND ship_name = ?",
            (user_id, ship_name),
        )
        self._connection.commit()

    async def delete_user_loaners_for_ship(self, user_id: int, ship_name: str) -> None:
        self._connection.execute(
            "DELETE FROM user_ships WHERE user_id = ? AND loaner_for = ?",
            (user_id, ship_name),
        )
        self._connection.commit()

    async def user_inventory_items(
        self,
        user_id: int,
        location: str | None = None,
        category: str | None = None,
        query: str | None = None,
        sort_by: str = "name",
        item_type: str | None = None,
        item_size: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        values: list[Any] = [user_id]
        if location:
            clauses.append("LOWER(TRIM(location)) = LOWER(TRIM(?))")
            values.append(location)
        if category:
            clauses.append("LOWER(TRIM(category)) = LOWER(TRIM(?))")
            values.append(category)
        if item_type:
            clauses.append("LOWER(TRIM(item_type)) = LOWER(TRIM(?))")
            values.append(item_type)
        if item_size:
            clauses.append("LOWER(TRIM(item_size)) = LOWER(TRIM(?))")
            values.append(item_size)
        if query:
            clauses.append("(item_name LIKE ? OR notes LIKE ?)")
            pattern = f"%{query}%"
            values.extend([pattern, pattern])

        order_by = {
            "location": "location COLLATE NOCASE, category COLLATE NOCASE, item_name COLLATE NOCASE",
            "category": "category COLLATE NOCASE, item_name COLLATE NOCASE, location COLLATE NOCASE",
            "quantity": "quantity DESC, item_name COLLATE NOCASE",
            "updated": "updated_at DESC, item_name COLLATE NOCASE",
            "name": "item_name COLLATE NOCASE, location COLLATE NOCASE",
        }.get(sort_by, "item_name COLLATE NOCASE, location COLLATE NOCASE")

        rows = self._connection.execute(
            f"""
            SELECT id, item_name, category, location, quantity, quality, item_type, item_size, volume_scu, notes, updated_at
            FROM user_inventory_items
            WHERE {" AND ".join(clauses)}
            ORDER BY {order_by}
            """,
            values,
        ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "category": row[2],
                "location": row[3],
                "quantity": row[4],
                "quality": row[5],
                "item_type": row[6],
                "item_size": row[7],
                "volume_scu": row[8],
                "notes": row[9],
                "updated_at": row[10],
            }
            for row in rows
        ]

    async def save_user_inventory_item(
        self,
        user_id: int,
        item_name: str,
        category: str | None,
        location: str,
        quantity: float,
        quality: float | None = None,
        item_type: str | None = None,
        item_size: str | None = None,
        volume_scu: float | None = None,
        notes: str | None = None,
    ) -> int:
        now = int(time.time())
        cursor = self._connection.execute(
            """
            INSERT INTO user_inventory_items (
                user_id, item_name, category, location, quantity, quality, item_type, item_size, volume_scu, notes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, item_name, category, location, quantity, quality, item_type, item_size, volume_scu, notes, now),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    async def update_user_inventory_item(
        self,
        user_id: int,
        item_id: int,
        item_name: str,
        category: str | None,
        location: str,
        quantity: float,
        quality: float | None = None,
        item_type: str | None = None,
        item_size: str | None = None,
        volume_scu: float | None = None,
        notes: str | None = None,
    ) -> bool:
        now = int(time.time())
        cursor = self._connection.execute(
            """
            UPDATE user_inventory_items
            SET item_name = ?, category = ?, location = ?, quantity = ?, quality = ?, item_type = ?, item_size = ?, volume_scu = ?,
                notes = ?, updated_at = ?
            WHERE user_id = ? AND id = ?
            """,
            (item_name, category, location, quantity, quality, item_type, item_size, volume_scu, notes, now, user_id, item_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def merge_user_inventory_duplicates(self, user_id: int) -> int:
        rows = self._connection.execute(
            """
            SELECT id, item_name, category, location, quantity, quality, item_type, item_size, volume_scu, notes
            FROM user_inventory_items
            WHERE user_id = ?
            ORDER BY updated_at DESC, id ASC
            """,
            (user_id,),
        ).fetchall()
        groups: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            key = (self._inventory_merge_key(row[1]), self._inventory_merge_key(row[3]))
            if not key[0] or not key[1]:
                continue
            groups.setdefault(key, []).append(row)

        removed = 0
        now = int(time.time())
        for group in groups.values():
            if len(group) < 2:
                continue
            keeper = group[0]
            duplicates = group[1:]
            quantity = max(float(row[4] or 0) for row in group)
            quality = next((row[5] for row in group if row[5] is not None), None)
            category = next((row[2] for row in group if row[2]), None)
            item_type = next((row[6] for row in group if row[6]), None)
            item_size = next((row[7] for row in group if row[7]), None)
            volume_scu = next((row[8] for row in group if row[8] is not None), None)
            notes = self._merge_inventory_notes(row[9] for row in group)
            self._connection.execute(
                """
                UPDATE user_inventory_items
                SET category = ?, quantity = ?, quality = ?, item_type = ?, item_size = ?, volume_scu = ?, notes = ?, updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (category, quantity, quality, item_type, item_size, volume_scu, notes, now, user_id, keeper[0]),
            )
            duplicate_ids = [row[0] for row in duplicates]
            placeholders = ",".join("?" for _ in duplicate_ids)
            self._connection.execute(
                f"DELETE FROM user_inventory_items WHERE user_id = ? AND id IN ({placeholders})",
                [user_id, *duplicate_ids],
            )
            removed += len(duplicate_ids)
        self._connection.commit()
        return removed

    def _inventory_merge_key(self, value: str | None) -> str:
        return " ".join("".join(char.lower() if char.isalnum() else " " for char in str(value or "")).split())

    def _merge_inventory_notes(self, values) -> str | None:
        notes: list[str] = []
        seen: set[str] = set()
        for value in values:
            for line in str(value or "").splitlines():
                cleaned = line.strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                notes.append(cleaned)
        return "\n".join(notes) if notes else None

    async def transfer_user_inventory_item(self, user_id: int, item_id: int, location: str) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE user_inventory_items
            SET location = ?, updated_at = ?
            WHERE user_id = ? AND id = ?
            """,
            (location, int(time.time()), user_id, item_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def delete_user_inventory_item(self, user_id: int, item_id: int) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM user_inventory_items WHERE user_id = ? AND id = ?",
            (user_id, item_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def clear_user_inventory_items(self, user_id: int, location: str | None = None) -> int:
        if location:
            cursor = self._connection.execute(
                """
                DELETE FROM user_inventory_items
                WHERE user_id = ? AND LOWER(TRIM(location)) = LOWER(TRIM(?))
                """,
                (user_id, location),
            )
        else:
            cursor = self._connection.execute(
                "DELETE FROM user_inventory_items WHERE user_id = ?",
                (user_id,),
            )
        self._connection.commit()
        return cursor.rowcount

    async def user_inventory_facets(self, user_id: int) -> dict[str, list[str]]:
        def values_for(column: str) -> list[str]:
            rows = self._connection.execute(
                f"""
                SELECT DISTINCT {column}
                FROM user_inventory_items
                WHERE user_id = ? AND {column} IS NOT NULL AND TRIM({column}) != ''
                ORDER BY {column} COLLATE NOCASE
                """,
                (user_id,),
            ).fetchall()
            return [row[0] for row in rows]

        return {
            "locations": values_for("location"),
            "categories": values_for("category"),
            "item_types": values_for("item_type"),
            "item_sizes": values_for("item_size"),
        }

    async def close(self) -> None:
        self._connection.close()
