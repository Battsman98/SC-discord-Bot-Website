from src.bot import build_feedback_template_embed
from src.web import _feedback_embed
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


def test_bot_feedback_template_gives_users_a_complete_example() -> None:
    embed = build_feedback_template_embed()
    fields = {field.name: field.value for field in embed.fields}

    assert embed.title == "Example: Guide button does not display the selected information"
    assert fields["Report type"] == "Issue / Bug"
    assert "Getting Started" in fields["Issue / Feedback"]
    assert "Trade guide" in fields["Expected action or result"]
    assert "screenshots" in fields["Helpful attachments"]
