import sqlite3

from scripts.run_render import (
    DEFAULT_MAINTENANCE_RESTART_SECONDS,
    clean_expired_cache,
    maintenance_restart_seconds,
    rolling_restart_web,
)


def test_clean_expired_cache_preserves_live_cache_and_user_data(tmp_path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE cache_entries (cache_key TEXT PRIMARY KEY, value_json TEXT, expires_at INTEGER)"
    )
    connection.execute("CREATE TABLE user_data (value TEXT)")
    connection.execute("INSERT INTO cache_entries VALUES ('expired', '{}', 99)")
    connection.execute("INSERT INTO cache_entries VALUES ('active', '{}', 101)")
    connection.execute("INSERT INTO user_data VALUES ('keep me')")
    connection.commit()
    connection.close()

    assert clean_expired_cache(str(database_path), now=100) == 1

    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT cache_key FROM cache_entries").fetchall() == [("active",)]
    assert connection.execute("SELECT value FROM user_data").fetchall() == [("keep me",)]
    connection.close()


def test_clean_expired_cache_accepts_missing_database(tmp_path) -> None:
    assert clean_expired_cache(str(tmp_path / "missing.sqlite3"), now=100) == 0


def test_clean_expired_cache_can_skip_compaction_while_web_is_online(tmp_path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE cache_entries (cache_key TEXT PRIMARY KEY, value_json TEXT, expires_at INTEGER)"
    )
    connection.execute("INSERT INTO cache_entries VALUES ('expired', '{}', 99)")
    connection.commit()
    connection.close()

    assert clean_expired_cache(str(database_path), now=100, compact=False) == 1


def test_rolling_web_restart_uses_sighup_without_stopping_listener(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.signals = []

        def poll(self):
            return None

        def send_signal(self, value) -> None:
            self.signals.append(value)

    process = FakeProcess()
    monkeypatch.setattr("scripts.run_render.signal.SIGHUP", 99, raising=False)

    assert rolling_restart_web(process) is True
    assert process.signals == [99]


def test_maintenance_restart_defaults_and_validates(monkeypatch) -> None:
    monkeypatch.delenv("MAINTENANCE_RESTART_SECONDS", raising=False)
    assert maintenance_restart_seconds() == DEFAULT_MAINTENANCE_RESTART_SECONDS

    monkeypatch.setenv("MAINTENANCE_RESTART_SECONDS", "3600")
    assert maintenance_restart_seconds() == 3600

    monkeypatch.setenv("MAINTENANCE_RESTART_SECONDS", "invalid")
    assert maintenance_restart_seconds() == DEFAULT_MAINTENANCE_RESTART_SECONDS

    monkeypatch.setenv("MAINTENANCE_RESTART_SECONDS", "1")
    assert maintenance_restart_seconds() == 60
