from pathlib import Path


CSS = (Path(__file__).resolve().parents[1] / "web" / "styles.css").read_text(encoding="utf-8")


def test_controls_and_boxes_follow_the_active_mfd_theme() -> None:
    assert "--control: color-mix(in srgb, var(--surface) 58%, #000);" in CSS
    assert "--button-surface: color-mix(in srgb, var(--accent) 14%, var(--surface));" in CSS
    assert "background: var(--control);" in CSS
    assert "background: var(--button-surface);" in CSS
    assert "border-color: color-mix(in srgb, var(--accent) 58%, transparent);" in CSS


def test_overview_uses_an_rsi_cockpit_mfd_palette() -> None:
    assert 'body[data-mfd-theme="overview"]' in CSS
    assert "--bg: #03080d;" in CSS
    assert "--surface: #0b1720;" in CSS
    assert "--accent: #36bce8;" in CSS
    assert "--accent-2: #9ce8ff;" in CSS


def test_inventory_uses_a_dedicated_rsi_mfd_palette() -> None:
    assert 'body[data-mfd-theme="rsi"]' in CSS
    assert "--surface: #0b151d;" in CSS
    assert "--accent: #32b9e6;" in CSS
    assert "--accent-2: #b4efff;" in CSS


def test_trade_uses_a_green_grey_market_mfd_palette() -> None:
    palette = CSS.split('body[data-mfd-theme="grey-market"]', 1)[1].split("}", 1)[0]

    assert "--bg: #030805;" in palette
    assert "--surface: #0b1710;" in palette
    assert "--accent: #55db72;" in palette
    assert "--accent-2: #b6ff67;" in palette
    assert "#bf62ed" not in palette


def test_intel_uses_a_unique_aegis_violet_and_signal_red_palette() -> None:
    palette = CSS.split('body[data-mfd-theme="aegis-intel"]', 1)[1].split("}", 1)[0]

    assert "--bg: #07050c;" in palette
    assert "--surface: #15101d;" in palette
    assert "--accent: #c57cff;" in palette
    assert "--accent-2: #ff5e78;" in palette


def test_legacy_amber_control_colors_are_not_hard_coded() -> None:
    assert "background: #2b2110;" not in CSS
    assert "border-color: rgba(228, 154, 24, 0.58);" not in CSS
    assert "background: #0b0c0d;" not in CSS
