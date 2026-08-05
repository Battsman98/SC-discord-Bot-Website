import sys
from types import SimpleNamespace

from src.postgres_compat import PostgresConnection, _translate_sql


class FakeCursor:
    def __init__(self, rows=(), rowcount=0):
        self.rows = list(rows)
        self.rowcount = rowcount

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, parameters=()):
        self.calls.append((statement, parameters))
        rows = [(42,)] if "RETURNING id" in statement else []
        return FakeCursor(rows, rowcount=1)


def test_translate_sqlite_placeholders_and_schema_syntax():
    translated = _translate_sql(
        "CREATE TABLE sample (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT); SELECT ? COLLATE NOCASE"
    )
    assert "BIGSERIAL PRIMARY KEY" in translated
    assert "user_id BIGINT" in translated
    assert "%s" in translated
    assert "NOCASE" not in translated


def test_insert_cursor_exposes_postgres_returning_id():
    raw = FakeConnection()
    connection = PostgresConnection(raw)
    cursor = connection.execute(
        "INSERT INTO user_inventory_items (user_id, item_name) VALUES (?, ?)",
        (7, "Ore"),
    )
    assert cursor.lastrowid == 42
    assert raw.calls[0][1] == (7, "Ore")
    assert raw.calls[0][0].rstrip().endswith("RETURNING id")


def test_connect_uses_autocommit_to_isolate_failed_cache_operations(monkeypatch):
    raw = FakeConnection()
    calls = []

    def connect(database_url, **kwargs):
        calls.append((database_url, kwargs))
        return raw

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))

    connection = PostgresConnection.connect("postgresql://example/cache")

    assert connection._connection is raw
    assert calls == [("postgresql://example/cache", {"autocommit": True})]
