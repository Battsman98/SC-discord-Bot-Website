from pathlib import Path


CSS = (Path(__file__).resolve().parents[1] / "web" / "styles.css").read_text(encoding="utf-8")


def test_controls_and_boxes_follow_the_active_mfd_theme() -> None:
    assert "--control: color-mix(in srgb, var(--surface) 58%, #000);" in CSS
    assert "--button-surface: color-mix(in srgb, var(--accent) 14%, var(--surface));" in CSS
    assert "background: var(--control);" in CSS
    assert "background: var(--button-surface);" in CSS
    assert "border-color: color-mix(in srgb, var(--accent) 58%, transparent);" in CSS


def test_legacy_amber_control_colors_are_not_hard_coded() -> None:
    assert "background: #2b2110;" not in CSS
    assert "border-color: rgba(228, 154, 24, 0.58);" not in CSS
    assert "background: #0b0c0d;" not in CSS
