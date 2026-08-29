from io import BytesIO

from fastapi import UploadFile

from src.bot import (
    BOT_MANAGER_ROLE_NAME,
    VISITOR_CATEGORY_NAME,
    VISITOR_CHANNEL_SPECS,
    VISITOR_COMMAND_CHANNELS,
    build_feedback_template_embed,
    build_visitor_command_example_embeds,
)
from src.web import _feedback_embed, _provided_feedback_images
from src.web_auth import WebUser


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


def test_feedback_submission_ignores_empty_optional_file_placeholder() -> None:
    empty_upload = UploadFile(filename="", file=BytesIO())

    # Keep this regression focused on the browser's empty multipart placeholder:
    # it must not count as an attachment or fail MIME validation.
    provided = _provided_feedback_images([empty_upload])

    assert provided == []


def test_bot_feedback_template_gives_users_a_complete_example() -> None:
    embed = build_feedback_template_embed()
    fields = {field.name: field.value for field in embed.fields}

    assert embed.title == "Example: Guide button does not display the selected information"
    assert fields["Report type"] == "Issue / Bug"
    assert "Getting Started" in fields["Issue / Feedback"]
    assert "Trade guide" in fields["Expected action or result"]
    assert "screenshots" in fields["Helpful attachments"]


def test_visitor_hub_includes_public_bot_and_social_channels() -> None:
    assert VISITOR_CATEGORY_NAME == "Discord Bot Hub"
    assert VISITOR_CHANNEL_SPECS["bot-commands"] == "text"
    assert VISITOR_CHANNEL_SPECS["general-chat"] == "text"
    assert VISITOR_CHANNEL_SPECS["visitor-lounge"] == "voice"
    assert VISITOR_COMMAND_CHANNELS["ship"] == "ship-search"
    assert VISITOR_COMMAND_CHANNELS["trade routing"] == "trade-tools"
    assert VISITOR_COMMAND_CHANNELS["miningadd"] == "mining-tools"
    assert not any(name.startswith("admin") or name.startswith("audit") for name in VISITOR_COMMAND_CHANNELS)


def test_every_visitor_command_channel_has_a_response_example() -> None:
    examples = build_visitor_command_example_embeds()

    assert set(VISITOR_COMMAND_CHANNELS.values()) <= set(examples)
    assert all(embed.title and "Example" in embed.title for embed in examples.values())

    blueprint = examples["blueprints-and-missions"]
    assert "/blueprint name: NDB-28 Repeater" in blueprint.description
    assert "select `name`" in blueprint.description
    assert "Titanium=750, Gold=820, Lindinium=910" in blueprint.description
    assert "qualities" in blueprint.description
    assert "/blueprint query:" not in blueprint.description
    assert "/wikelo" in "\n".join(field.value for field in blueprint.fields)
    assert "Wikelo reputation awarded" in "\n".join(field.value for field in blueprint.fields)

    trade = examples["trade-tools"]
    assert "investment: 500000" in trade.description
    assert "budget:" not in trade.description

    item = examples["item-locator"]
    assert "/item search name: FS-9 LMG" in item.description


def test_bot_manager_role_name_is_stable_for_discord_and_website_access() -> None:
    assert BOT_MANAGER_ROLE_NAME == "Bot Manager"
