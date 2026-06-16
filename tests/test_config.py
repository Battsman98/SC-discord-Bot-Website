import pytest

from src.config import Settings


def test_settings_require_discord_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)

    with pytest.raises(RuntimeError):
        Settings.from_env(load_env_file=False)


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123")
    monkeypatch.setenv("COMMANDS_CHANNEL_ID", "456")
    monkeypatch.setenv("EXEC_STATUS_CHANNEL_ID", "789")
    monkeypatch.setenv("EXEC_ADMIN_ROLE_IDS", "111,222")
    monkeypatch.setenv("CZ_TIMERS_CHANNEL_ID", "333")
    monkeypatch.setenv("SC_TRADE_TOOLS_TOKEN", "token")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")

    settings = Settings.from_env(load_env_file=False)

    assert settings.discord_token == "token"
    assert settings.discord_guild_id == 123
    assert settings.commands_channel_id == 456
    assert settings.exec_status_channel_id == 789
    assert settings.exec_admin_role_ids == (111, 222)
    assert settings.cz_timers_channel_id == 333
    assert settings.sc_trade_tools_token == "token"
    assert settings.cache_ttl_seconds == 60
