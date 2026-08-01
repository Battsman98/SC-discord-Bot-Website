from src.config import Settings
from src.web import _feedback_embed, _feedback_forum_url
from src.web_auth import WebUser


def test_feedback_forum_url_uses_configured_guild_and_channel() -> None:
    settings = Settings(
        discord_token="token",
        discord_client_id="client",
        discord_client_secret="secret",
        discord_redirect_uri="https://example.com/callback",
        discord_guild_id=123,
        commands_channel_id=None,
        exec_status_channel_id=None,
        exec_admin_role_ids=(),
        bot_admin_role_ids=(),
        bot_admin_user_ids=(),
        cz_timers_channel_id=None,
        audit_log_channel_id=None,
        command_channel_ids={},
        command_prefix="!",
        database_path=":memory:",
        http_timeout_seconds=15,
        cache_ttl_seconds=300,
    )

    assert _feedback_forum_url(settings) == (
        "https://discord.com/channels/123/1533026212463775754"
    )


def test_feedback_embed_has_structured_report_fields() -> None:
    user = WebUser(
        id=42,
        username="pilot",
        display_name="Pilot",
        avatar_url="https://cdn.example/avatar.png",
        roles=(),
        guild_permissions=0,
        can_manage_changes=False,
        can_manage_admin=False,
    )

    embed = _feedback_embed(
        report_type="issue",
        details="The button did not respond.",
        expected_action="Open the selected panel.",
        steps="Open Overview and select Trade.",
        recommendations="Add a visible selected state.",
        user=user,
    )

    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert fields["Report type"] == "Issue / Bug"
    assert fields["Reported by"] == "Pilot (`42`)"
    assert fields["Issue / Feedback"] == "The button did not respond."
    assert fields["Expected action or result"] == "Open the selected panel."
    assert fields["Steps to reproduce"] == "Open Overview and select Trade."
    assert fields["Improvement recommendations"] == "Add a visible selected state."
    assert embed["author"]["icon_url"] == "https://cdn.example/avatar.png"
