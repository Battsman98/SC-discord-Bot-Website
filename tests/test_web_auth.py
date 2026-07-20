from src.config import Settings
from src.web_auth import WebUser, can_manage_admin_commands, can_manage_change_commands, decode_session, encode_session


def settings(
    exec_roles: tuple[int, ...] = (),
    admin_roles: tuple[int, ...] = (),
    admin_users: tuple[int, ...] = (),
) -> Settings:
    return Settings(
        discord_token="token",
        discord_client_id="client",
        discord_client_secret="secret",
        discord_redirect_uri="http://127.0.0.1:8000/auth/discord/callback",
        discord_guild_id=123,
        commands_channel_id=None,
        exec_status_channel_id=None,
        exec_admin_role_ids=exec_roles,
        bot_admin_role_ids=admin_roles,
        bot_admin_user_ids=admin_users,
        cz_timers_channel_id=None,
        audit_log_channel_id=None,
        command_channel_ids={},
        command_prefix="!",
        database_path="data/test.sqlite3",
        http_timeout_seconds=15,
        cache_ttl_seconds=300,
    )


def test_change_admin_uses_exec_roles_when_configured() -> None:
    app_settings = settings(exec_roles=(10,))

    assert can_manage_change_commands(app_settings, (10, 20), permissions=0) is True
    assert can_manage_change_commands(app_settings, (20,), permissions=0x20) is False


def test_change_admin_falls_back_to_manage_guild() -> None:
    app_settings = settings()

    assert can_manage_change_commands(app_settings, (), permissions=0x20) is True
    assert can_manage_change_commands(app_settings, (), permissions=0) is False


def test_bot_admin_uses_users_and_roles_before_fallback() -> None:
    app_settings = settings(admin_roles=(30,), admin_users=(99,))

    assert can_manage_admin_commands(app_settings, 99, (), permissions=0) is True
    assert can_manage_admin_commands(app_settings, 1, (30,), permissions=0) is True
    assert can_manage_admin_commands(app_settings, 1, (), permissions=0x20) is False


def test_session_round_trip() -> None:
    user = WebUser(
        id=42,
        username="pilot",
        display_name="Pilot",
        avatar_url=None,
        roles=(10, 20),
        guild_permissions=0x20,
        can_manage_changes=True,
        can_manage_admin=False,
    )

    encoded = encode_session(user, "secret")
    decoded = decode_session(encoded, "secret")

    assert decoded == user
    assert decode_session(encoded, "wrong-secret") is None
