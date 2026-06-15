import pytest

from src.config import Settings


def test_settings_require_discord_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)

    with pytest.raises(RuntimeError):
        Settings.from_env(load_env_file=False)


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")

    settings = Settings.from_env(load_env_file=False)

    assert settings.discord_token == "token"
    assert settings.discord_guild_id == 123
    assert settings.cache_ttl_seconds == 60
