import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.postgres_compat import PostgresConnection


AUDIT_ACTION_TYPES = {
    "admin", "audit", "authentication", "blueprints", "commands", "crashes", "inventory",
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
        ("crashes", ("crash", "unhandled exception")),
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
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @classmethod
    async def create(cls, database_path: str) -> "SQLiteCache":
        if database_path.startswith(("postgres://", "postgresql://")):
            connection = PostgresConnection.connect(database_path)
        else:
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
            CREATE TABLE IF NOT EXISTS website_daily_visits (
                visit_day TEXT NOT NULL,
                visitor_hash TEXT NOT NULL,
                user_id INTEGER,
                page_views INTEGER NOT NULL DEFAULT 1,
                first_seen_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                PRIMARY KEY (visit_day, visitor_hash)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS website_active_visitors (
                visitor_hash TEXT PRIMARY KEY,
                user_id INTEGER,
                last_seen_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS website_language_samples (
                week_start TEXT NOT NULL,
                visitor_hash TEXT NOT NULL,
                language_code TEXT NOT NULL,
                sampled_at INTEGER NOT NULL,
                PRIMARY KEY (week_start, visitor_hash)
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_refinery_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                material TEXT,
                quantity REAL,
                refinery TEXT,
                method TEXT,
                location TEXT,
                crew TEXT,
                notes TEXT,
                completes_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'refining',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_refinery_orders_user_status ON user_refinery_orders(user_id, status, completes_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS item_catalog (
                item_uuid TEXT PRIMARY KEY,
                stable_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                category TEXT,
                item_type TEXT,
                company_name TEXT,
                item_size TEXT,
                source_url TEXT NOT NULL,
                source_name TEXT NOT NULL,
                game_version TEXT,
                source_updated_at TEXT,
                class_name TEXT,
                is_lootable INTEGER,
                verified_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS item_catalog_metadata (
                metadata_key TEXT PRIMARY KEY,
                metadata_value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS loot_sighting_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_uuid TEXT NOT NULL,
                item_name TEXT NOT NULL,
                normalized_item_name TEXT NOT NULL,
                location TEXT NOT NULL,
                celestial_body TEXT,
                location_type TEXT,
                game_version TEXT,
                notes TEXT,
                screenshot_url TEXT,
                source_url TEXT,
                reporter_id INTEGER NOT NULL,
                reporter_name TEXT NOT NULL,
                guild_id INTEGER,
                channel_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_id INTEGER,
                reviewer_name TEXT,
                review_message_id INTEGER,
                created_at INTEGER NOT NULL,
                reviewed_at INTEGER
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_item_catalog_normalized_name ON item_catalog(normalized_name)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_loot_sightings_item_status ON loot_sighting_reports(normalized_item_name, status, reviewed_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_scan_diagnostics (
                diagnostic_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                capture_index INTEGER NOT NULL,
                capture_token TEXT,
                category TEXT,
                item_type TEXT,
                ocr_text TEXT,
                matched_items_json TEXT NOT NULL,
                attempted_titles_json TEXT NOT NULL,
                diagnostics_json TEXT NOT NULL,
                calibration_json TEXT,
                error_text TEXT,
                queue_ms INTEGER NOT NULL DEFAULT 0,
                ocr_ms INTEGER NOT NULL DEFAULT 0,
                match_ms INTEGER NOT NULL DEFAULT 0,
                server_ms INTEGER NOT NULL DEFAULT 0,
                client_elapsed_ms INTEGER,
                client_queue_depth INTEGER,
                image_content_type TEXT NOT NULL,
                image_data BYTEA NOT NULL,
                image_size INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_scan_diagnostics_session ON inventory_scan_diagnostics(user_id, session_id, capture_index)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_scan_diagnostics_expiry ON inventory_scan_diagnostics(expires_at)"
        )
        cls._ensure_column(connection, "user_ships", "image_url", "TEXT")
        cls._ensure_column(connection, "user_ships", "notes", "TEXT")
        cls._ensure_column(connection, "user_ships", "loaner_for", "TEXT")
        cls._ensure_column(connection, "user_ships", "quantity", "INTEGER NOT NULL DEFAULT 1")
        cls._ensure_column(connection, "user_inventory_items", "quality", "REAL")
        cls._ensure_column(connection, "user_inventory_items", "item_type", "TEXT")
        cls._ensure_column(connection, "user_inventory_items", "item_size", "TEXT")
        cls._ensure_column(connection, "user_inventory_items", "volume_scu", "REAL")
        cls._ensure_column(connection, "item_catalog", "class_name", "TEXT")
        cls._ensure_column(connection, "item_catalog", "is_lootable", "INTEGER")
        cls._ensure_column(connection, "loot_sighting_reports", "celestial_body", "TEXT")
        cls._ensure_column(connection, "loot_sighting_reports", "source_url", "TEXT")
        cls._ensure_column(connection, "audit_events", "action_type", "TEXT NOT NULL DEFAULT 'other'")
        cls._backfill_audit_action_types(connection)
        connection.commit()
        return cls(connection)

    async def save_inventory_scan_diagnostic(
        self,
        *,
        diagnostic_id: str,
        session_id: str,
        user_id: int,
        capture_index: int,
        capture_token: str | None,
        category: str | None,
        item_type: str | None,
        ocr_text: str,
        matched_items: list[str],
        attempted_titles: list[tuple[str, str]],
        diagnostics: dict[str, Any],
        calibration: dict[str, Any] | None,
        error_text: str | None,
        queue_ms: int,
        ocr_ms: int,
        match_ms: int,
        server_ms: int,
        client_elapsed_ms: int | None,
        client_queue_depth: int | None,
        image_content_type: str,
        image_data: bytes,
        ttl_seconds: int = 86400,
    ) -> None:
        now = int(time.time())
        self._connection.execute(
            """
            INSERT INTO inventory_scan_diagnostics (
                diagnostic_id, session_id, user_id, capture_index, capture_token,
                category, item_type, ocr_text, matched_items_json,
                attempted_titles_json, diagnostics_json, calibration_json,
                error_text, queue_ms, ocr_ms, match_ms, server_ms,
                client_elapsed_ms, client_queue_depth, image_content_type,
                image_data, image_size, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(diagnostic_id) DO UPDATE SET
                ocr_text = excluded.ocr_text,
                matched_items_json = excluded.matched_items_json,
                attempted_titles_json = excluded.attempted_titles_json,
                diagnostics_json = excluded.diagnostics_json,
                calibration_json = excluded.calibration_json,
                error_text = excluded.error_text,
                queue_ms = excluded.queue_ms,
                ocr_ms = excluded.ocr_ms,
                match_ms = excluded.match_ms,
                server_ms = excluded.server_ms,
                image_data = excluded.image_data,
                image_size = excluded.image_size,
                expires_at = excluded.expires_at
            """,
            (
                diagnostic_id, session_id, user_id, capture_index, capture_token,
                category, item_type, ocr_text, json.dumps(matched_items),
                json.dumps(attempted_titles), json.dumps(diagnostics),
                json.dumps(calibration) if calibration is not None else None,
                error_text, queue_ms, ocr_ms, match_ms, server_ms,
                client_elapsed_ms, client_queue_depth, image_content_type,
                image_data, len(image_data), now, now + ttl_seconds,
            ),
        )
        self._connection.commit()

    async def purge_expired_inventory_scan_diagnostics(self) -> int:
        cursor = self._connection.execute(
            "DELETE FROM inventory_scan_diagnostics WHERE expires_at <= ?",
            (int(time.time()),),
        )
        self._connection.commit()
        return cursor.rowcount

    async def list_inventory_scan_sessions(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        await self.purge_expired_inventory_scan_diagnostics()
        rows = self._connection.execute(
            """
            SELECT session_id, MIN(created_at), MAX(created_at), COUNT(*),
                   SUM(image_size), SUM(CASE WHEN matched_items_json <> '[]' THEN 1 ELSE 0 END),
                   MAX(expires_at)
            FROM inventory_scan_diagnostics
            WHERE user_id = ?
            GROUP BY session_id
            ORDER BY MAX(created_at) DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [
            {
                "session_id": row[0], "started_at": row[1], "last_capture_at": row[2],
                "capture_count": row[3], "storage_bytes": row[4] or 0,
                "matched_capture_count": row[5] or 0, "expires_at": row[6],
            }
            for row in rows
        ]

    async def get_inventory_scan_session(self, user_id: int, session_id: str) -> list[dict[str, Any]]:
        await self.purge_expired_inventory_scan_diagnostics()
        rows = self._connection.execute(
            """
            SELECT diagnostic_id, capture_index, capture_token, category, item_type,
                   ocr_text, matched_items_json, attempted_titles_json, diagnostics_json,
                   calibration_json, error_text, queue_ms, ocr_ms, match_ms, server_ms,
                   client_elapsed_ms, client_queue_depth, image_content_type, image_size,
                   created_at, expires_at
            FROM inventory_scan_diagnostics
            WHERE user_id = ? AND session_id = ?
            ORDER BY capture_index, created_at
            """,
            (user_id, session_id),
        ).fetchall()
        return [
            {
                "diagnostic_id": row[0], "capture_index": row[1], "capture_token": row[2],
                "category": row[3], "item_type": row[4], "ocr_text": row[5],
                "matched_items": json.loads(row[6]), "attempted_titles": json.loads(row[7]),
                "diagnostics": json.loads(row[8]),
                "calibration": json.loads(row[9]) if row[9] else None,
                "error": row[10], "performance": {
                    "queue_ms": row[11], "ocr_ms": row[12], "match_ms": row[13],
                    "server_ms": row[14], "client_elapsed_ms": row[15],
                    "client_queue_depth": row[16],
                },
                "image_content_type": row[17], "image_size": row[18],
                "created_at": row[19], "expires_at": row[20],
                "image_url": f"/api/me/inventory/scans/images/{row[0]}",
            }
            for row in rows
        ]

    async def get_inventory_scan_image(self, user_id: int, diagnostic_id: str) -> tuple[str, bytes] | None:
        await self.purge_expired_inventory_scan_diagnostics()
        row = self._connection.execute(
            """
            SELECT image_content_type, image_data
            FROM inventory_scan_diagnostics
            WHERE user_id = ? AND diagnostic_id = ?
            """,
            (user_id, diagnostic_id),
        ).fetchone()
        return (str(row[0]), bytes(row[1])) if row else None

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

    async def add_loot_sighting_report(
        self,
        *,
        item_uuid: str,
        item_name: str,
        location: str,
        location_type: str | None,
        game_version: str | None,
        notes: str | None,
        screenshot_url: str | None,
        reporter_id: int,
        reporter_name: str,
        guild_id: int | None,
        channel_id: int | None,
        celestial_body: str | None = None,
        source_url: str | None = None,
    ) -> int:
        normalized = " ".join(item_name.casefold().replace("-", " ").split())
        cursor = self._connection.execute(
            """
            INSERT INTO loot_sighting_reports (
                item_uuid, item_name, normalized_item_name, location, celestial_body, location_type,
                game_version, notes, screenshot_url, source_url, reporter_id, reporter_name,
                guild_id, channel_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_uuid, item_name, normalized, location, celestial_body, location_type, game_version,
                notes, screenshot_url, source_url, reporter_id, reporter_name, guild_id, channel_id,
                int(time.time()),
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    async def loot_sighting_report(self, report_id: int) -> dict[str, Any] | None:
        rows = await self._loot_sighting_rows("WHERE id = ?", (report_id,))
        return rows[0] if rows else None

    async def pending_loot_sighting_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self._loot_sighting_rows(
            "WHERE status = 'pending' ORDER BY id ASC LIMIT ?", (max(1, min(limit, 500)),)
        )

    async def approved_loot_sightings(self, item_name: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized = " ".join(item_name.casefold().replace("-", " ").split())
        return await self._loot_sighting_rows(
            "WHERE normalized_item_name = ? AND status = 'approved' ORDER BY reviewed_at DESC, id DESC LIMIT ?",
            (normalized, max(1, min(limit, 25))),
        )

    async def loot_location_evidence(self, item_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Group approved observations into useful, confidence-scored POI evidence."""
        sightings = await self.approved_loot_sightings(item_name, 25)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for sighting in sightings:
            key = " ".join(str(sighting["location"]).casefold().replace("-", " ").split())
            grouped.setdefault(key, []).append(sighting)
        evidence: list[dict[str, Any]] = []
        now = int(time.time())
        for rows in grouped.values():
            reporters = {row["reporter_id"] for row in rows}
            screenshots = sum(bool(row.get("screenshot_url")) for row in rows)
            sources = sum(bool(row.get("source_url")) for row in rows)
            latest = max(int(row.get("reviewed_at") or row.get("created_at") or 0) for row in rows)
            score = 25 + min(45, len(reporters) * 15) + min(10, screenshots * 5) + min(10, sources * 5)
            if latest and now - latest <= 180 * 86400:
                score += 10
            score = min(100, score)
            confidence = "Confirmed" if score >= 80 else "Likely" if score >= 55 else "Possible"
            newest = max(rows, key=lambda row: int(row.get("reviewed_at") or 0))
            location_type = next((row.get("location_type") for row in rows if row.get("location_type")), None)
            discord_location_type = " · ".join(
                value for value in (
                    next((row.get("celestial_body") for row in rows if row.get("celestial_body")), None),
                    location_type,
                    f"{confidence} confidence ({len(rows)} report{'s' if len(rows) != 1 else ''})",
                ) if value
            )
            evidence.append({
                "location": newest["location"],
                "celestial_body": next((row.get("celestial_body") for row in rows if row.get("celestial_body")), None),
                "location_type": discord_location_type,
                "game_version": next((row.get("game_version") for row in rows if row.get("game_version")), None),
                "confidence": confidence,
                "confidence_score": score,
                "report_count": len(rows),
                "independent_reporters": len(reporters),
                "evidence_count": screenshots + sources,
                "latest_confirmed_at": latest,
                "reviewed_at": latest,
                "source_urls": list(dict.fromkeys(row["source_url"] for row in rows if row.get("source_url")))[:3],
            })
        evidence.sort(key=lambda row: (-row["confidence_score"], -row["report_count"], row["location"].casefold()))
        return evidence[:max(1, min(limit, 25))]

    async def set_loot_sighting_review_message(self, report_id: int, message_id: int) -> None:
        self._connection.execute(
            "UPDATE loot_sighting_reports SET review_message_id = ? WHERE id = ?",
            (message_id, report_id),
        )
        self._connection.commit()

    async def review_loot_sighting(
        self, report_id: int, status: str, reviewer_id: int, reviewer_name: str
    ) -> bool:
        if status not in {"approved", "rejected"}:
            raise ValueError("Loot sighting status must be approved or rejected.")
        cursor = self._connection.execute(
            """
            UPDATE loot_sighting_reports
            SET status = ?, reviewer_id = ?, reviewer_name = ?, reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (status, reviewer_id, reviewer_name, int(time.time()), report_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    async def _loot_sighting_rows(self, where: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"""
            SELECT id, item_uuid, item_name, location, celestial_body, location_type, game_version,
                   notes, screenshot_url, source_url, reporter_id, reporter_name, guild_id, channel_id,
                   status, reviewer_id, reviewer_name, review_message_id, created_at, reviewed_at
            FROM loot_sighting_reports {where}
            """,
            parameters,
        ).fetchall()
        keys = (
            "id", "item_uuid", "item_name", "location", "celestial_body", "location_type", "game_version",
            "notes", "screenshot_url", "source_url", "reporter_id", "reporter_name", "guild_id", "channel_id",
            "status", "reviewer_id", "reviewer_name", "review_message_id", "created_at", "reviewed_at",
        )
        return [dict(zip(keys, row)) for row in rows]

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

    async def record_website_visit(
        self,
        visitor_hash: str,
        user_id: int | None = None,
        now: int | None = None,
    ) -> None:
        timestamp = int(time.time()) if now is None else int(now)
        visit_day = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        self._connection.execute(
            """
            INSERT INTO website_daily_visits (
                visit_day, visitor_hash, user_id, page_views, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(visit_day, visitor_hash) DO UPDATE SET
                user_id = COALESCE(excluded.user_id, website_daily_visits.user_id),
                page_views = website_daily_visits.page_views + 1,
                last_seen_at = excluded.last_seen_at
            """,
            (visit_day, visitor_hash, user_id, timestamp, timestamp),
        )
        self._connection.commit()

    async def touch_website_activity(
        self,
        visitor_hash: str,
        user_id: int | None = None,
        now: int | None = None,
    ) -> None:
        timestamp = int(time.time()) if now is None else int(now)
        self._connection.execute(
            """
            INSERT INTO website_active_visitors (visitor_hash, user_id, last_seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT(visitor_hash) DO UPDATE SET
                user_id = COALESCE(excluded.user_id, website_active_visitors.user_id),
                last_seen_at = excluded.last_seen_at
            """,
            (visitor_hash, user_id, timestamp),
        )
        self._connection.execute(
            "DELETE FROM website_active_visitors WHERE last_seen_at < ?",
            (timestamp - 24 * 60 * 60,),
        )
        self._connection.commit()

    async def record_website_language(
        self,
        visitor_hash: str,
        language_code: str,
        now: int | None = None,
    ) -> None:
        timestamp = int(time.time()) if now is None else int(now)
        sampled_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        week_start = (sampled_date - timedelta(days=sampled_date.weekday())).isoformat()
        self._connection.execute(
            """
            INSERT INTO website_language_samples (
                week_start, visitor_hash, language_code, sampled_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(week_start, visitor_hash) DO NOTHING
            """,
            (week_start, visitor_hash, language_code, timestamp),
        )
        self._connection.commit()

    async def website_visitor_analytics(self, now: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time()) if now is None else int(now)
        today = datetime.fromtimestamp(timestamp, timezone.utc).date()
        active_window_minutes = 5
        active_row = self._connection.execute(
            """
            SELECT COUNT(DISTINCT visitor_hash),
                   COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END)
            FROM website_active_visitors
            WHERE last_seen_at >= ?
            """,
            (timestamp - active_window_minutes * 60,),
        ).fetchone()

        def totals(days: int) -> dict[str, int]:
            cutoff = (today - timedelta(days=days - 1)).isoformat()
            row = self._connection.execute(
                """
                SELECT COUNT(DISTINCT visitor_hash), COALESCE(SUM(page_views), 0),
                       COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END)
                FROM website_daily_visits
                WHERE visit_day >= ?
                """,
                (cutoff,),
            ).fetchone()
            return {
                "unique_visitors": int(row[0] or 0),
                "page_views": int(row[1] or 0),
                "signed_in_users": int(row[2] or 0),
            }

        daily_rows = self._connection.execute(
            """
            SELECT visit_day, COUNT(DISTINCT visitor_hash), SUM(page_views),
                   COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END)
            FROM website_daily_visits
            WHERE visit_day >= ?
            GROUP BY visit_day
            ORDER BY visit_day DESC
            """,
            ((today - timedelta(days=13)).isoformat(),),
        ).fetchall()
        language_rows = self._connection.execute(
            """
            SELECT language_code, COUNT(*)
            FROM website_language_samples
            WHERE sampled_at >= ?
            GROUP BY language_code
            ORDER BY COUNT(*) DESC, language_code ASC
            """,
            (timestamp - 30 * 24 * 60 * 60,),
        ).fetchall()
        return {
            "timezone": "UTC",
            "active_now": {
                "unique_visitors": int(active_row[0] or 0),
                "signed_in_users": int(active_row[1] or 0),
                "window_minutes": active_window_minutes,
            },
            "today": totals(1),
            "last_7_days": totals(7),
            "last_30_days": totals(30),
            "languages_last_30_days": [
                {"language": row[0], "samples": int(row[1] or 0)}
                for row in language_rows
            ],
            "daily": [
                {
                    "date": row[0],
                    "unique_visitors": int(row[1] or 0),
                    "page_views": int(row[2] or 0),
                    "signed_in_users": int(row[3] or 0),
                }
                for row in daily_rows
            ],
        }


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
                quantity = CASE WHEN CAST(? AS BIGINT) IS NULL THEN user_ships.quantity ELSE excluded.quantity END,
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
            quantity = sum(float(row[4] or 0) for row in group)
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

    async def item_catalog_rows(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT item_uuid, stable_id, item_name, normalized_name, category, item_type,
                   company_name, item_size, source_url, source_name, game_version,
                   source_updated_at, class_name, is_lootable, verified_at
            FROM item_catalog
            ORDER BY item_name COLLATE NOCASE
            """
        ).fetchall()
        columns = (
            "item_uuid", "stable_id", "item_name", "normalized_name", "category", "item_type",
            "company_name", "item_size", "source_url", "source_name", "game_version",
            "source_updated_at", "class_name", "is_lootable", "verified_at",
        )
        return [dict(zip(columns, row)) for row in rows]

    async def item_catalog_metadata(self) -> dict[str, Any]:
        rows = self._connection.execute(
            "SELECT metadata_key, metadata_value FROM item_catalog_metadata"
        ).fetchall()
        metadata: dict[str, Any] = {}
        for key, value in rows:
            try:
                metadata[key] = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                metadata[key] = value
        return metadata

    async def set_item_catalog_metadata(self, values: dict[str, Any]) -> None:
        self._connection.executemany(
            """
            INSERT INTO item_catalog_metadata (metadata_key, metadata_value)
            VALUES (?, ?)
            ON CONFLICT(metadata_key) DO UPDATE SET metadata_value = excluded.metadata_value
            """,
            [(str(key), json.dumps(value)) for key, value in values.items()],
        )
        self._connection.commit()

    async def replace_item_catalog(
        self,
        rows: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        required = {"item_uuid", "stable_id", "item_name", "normalized_name", "source_url"}
        if not rows or any(not required.issubset(row) for row in rows):
            raise ValueError("Item catalog replacement is empty or missing required fields.")
        now = int(time.time())
        values = [
            (
                row["item_uuid"], row["stable_id"], row["item_name"], row["normalized_name"],
                row.get("category"), row.get("item_type"), row.get("company_name"),
                row.get("item_size"), row["source_url"], row.get("source_name") or "Star Citizen Wiki",
                row.get("game_version"), row.get("source_updated_at"), now,
                row.get("class_name"), 1 if row.get("is_lootable") else 0,
            )
            for row in rows
        ]

        with self._connection:
            self._connection.execute("DELETE FROM item_catalog")
            self._connection.executemany(
                """
                INSERT INTO item_catalog (
                    item_uuid, stable_id, item_name, normalized_name, category, item_type,
                    company_name, item_size, source_url, source_name, game_version,
                    source_updated_at, verified_at, class_name, is_lootable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self._connection.executemany(
                """
                INSERT INTO item_catalog_metadata (metadata_key, metadata_value)
                VALUES (?, ?)
                ON CONFLICT(metadata_key) DO UPDATE SET metadata_value = excluded.metadata_value
                """,
                [(str(key), json.dumps(value)) for key, value in metadata.items()],
            )

    async def user_refinery_orders(self, user_id: int) -> list[dict[str, Any]]:
        self._connection.execute(
            "UPDATE user_refinery_orders SET status = 'ready', updated_at = ? WHERE user_id = ? AND status = 'refining' AND completes_at <= ?",
            (int(time.time()), user_id, int(time.time())),
        )
        self._connection.commit()
        rows = self._connection.execute(
            """
            SELECT id, label, material, quantity, refinery, method, location, crew, notes,
                   completes_at, status, created_at, updated_at
            FROM user_refinery_orders
            WHERE user_id = ?
            ORDER BY CASE status WHEN 'refining' THEN 0 WHEN 'ready' THEN 1 ELSE 2 END,
                     completes_at ASC, id DESC
            """,
            (user_id,),
        ).fetchall()
        return [
            {
                "id": row[0], "label": row[1], "material": row[2], "quantity": row[3],
                "refinery": row[4], "method": row[5], "location": row[6], "crew": row[7],
                "notes": row[8], "completes_at": row[9], "status": row[10],
                "created_at": row[11], "updated_at": row[12],
            }
            for row in rows
        ]

    async def save_user_refinery_order(self, user_id: int, values: dict[str, Any]) -> int:
        now = int(time.time())
        cursor = self._connection.execute(
            """
            INSERT INTO user_refinery_orders (
                user_id, label, material, quantity, refinery, method, location, crew, notes,
                completes_at, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'refining', ?, ?)
            """,
            (
                user_id, values["label"], values.get("material"), values.get("quantity"),
                values.get("refinery"), values.get("method"), values.get("location"),
                values.get("crew"), values.get("notes"), values["completes_at"], now, now,
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    async def update_user_refinery_order_status(self, user_id: int, order_id: int, status: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE user_refinery_orders SET status = ?, updated_at = ? WHERE user_id = ? AND id = ?",
            (status, int(time.time()), user_id, order_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def delete_user_refinery_order(self, user_id: int, order_id: int) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM user_refinery_orders WHERE user_id = ? AND id = ?",
            (user_id, order_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def close(self) -> None:
        self._connection.close()
