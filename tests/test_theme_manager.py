import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.theme_ids import CCCP_THEME_ID, MACOS_THEME_ID
from torrent2000.ui.theme import theme_manager
from torrent2000.ui.theme.theme_manager import (
    DEFAULT_THEME,
    TITLE_BAR_STYLES,
    _qss_path,
    apply_theme,
    title_bar_style_for,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- title_bar_style_for: light mode -----------------------------------------


@pytest.mark.parametrize("theme_id", list(TITLE_BAR_STYLES.keys()))
def test_light_mode_returns_base_style_unchanged(theme_id):
    assert title_bar_style_for(theme_id, "light") == TITLE_BAR_STYLES[theme_id]


def test_default_appearance_mode_is_light():
    assert title_bar_style_for("luna_xp") == TITLE_BAR_STYLES["luna_xp"]


def test_unknown_theme_falls_back_to_default_theme():
    assert title_bar_style_for("does_not_exist", "light") == TITLE_BAR_STYLES[DEFAULT_THEME]


# -- title_bar_style_for: dark mode -------------------------------------------


@pytest.mark.parametrize("theme_id", ["win10_fluent", "win11_mica", MACOS_THEME_ID])
def test_dark_mode_applies_per_theme_override(theme_id):
    style = title_bar_style_for(theme_id, "dark")
    base = TITLE_BAR_STYLES[theme_id]
    override = theme_manager._DARK_TITLE_BAR_OVERRIDES[theme_id]

    assert style.caption_flat_color == override["caption_flat_color"]
    assert style.title_text_color == override["title_text_color"]
    # Fields the override dict doesn't mention stay as the base theme's.
    assert style.caption_gradient == base.caption_gradient
    assert style.button_variant == base.button_variant
    assert style.font_family == base.font_family
    assert style.window_corner_radius == base.window_corner_radius


@pytest.mark.parametrize("theme_id", ["luna_xp", "win7_aero", "win95_classic", CCCP_THEME_ID])
def test_dark_mode_leaves_themes_without_override_unchanged(theme_id):
    # XP/7/95/CCCP predate the concept of a system dark mode (see module
    # docstring) -- their caption stays exactly as in light mode.
    assert title_bar_style_for(theme_id, "dark") == TITLE_BAR_STYLES[theme_id]


# -- title_bar_style_for: dark_hc ---------------------------------------------


@pytest.mark.parametrize("theme_id", list(TITLE_BAR_STYLES.keys()))
def test_dark_hc_forces_universal_black_caption(theme_id):
    style = title_bar_style_for(theme_id, "dark_hc")

    assert style.caption_gradient is None
    assert style.caption_flat_color == "#000000"
    assert style.title_text_color == "#FFFFFF"
    assert style.minmax_fill_color == "#000000"
    assert style.minmax_hover_color == "#FFFF00"
    assert style.close_fill_color == "#000000"
    assert style.close_hover_color == "#FFFF00"
    assert style.button_glyph_color == "#FFFFFF"
    assert style.button_hover_glyph_color == "#000000"


@pytest.mark.parametrize("theme_id", list(TITLE_BAR_STYLES.keys()))
def test_dark_hc_preserves_non_color_fields_from_base_theme(theme_id):
    style = title_bar_style_for(theme_id, "dark_hc")
    base = TITLE_BAR_STYLES[theme_id]

    assert style.font_family == base.font_family
    assert style.font_bold == base.font_bold
    assert style.button_variant == base.button_variant
    assert style.button_hover_radius == base.button_hover_radius
    assert style.window_corner_radius == base.window_corner_radius
    assert style.close_glyph == base.close_glyph


def test_dark_hc_overrides_a_themes_own_dark_mode_color():
    # win11_mica has its own "dark" override, but dark_hc must still win
    # with the universal black caption, not that per-theme dark color.
    style = title_bar_style_for("win11_mica", "dark_hc")
    assert style.caption_flat_color == "#000000"


# -- _qss_path -----------------------------------------------------------------


@pytest.mark.parametrize(
    "theme_id, appearance_mode, expected_name",
    [
        ("luna_xp", "light", "luna.qss"),
        ("luna_xp", "dark", "luna_dark.qss"),
        ("win10_fluent", "dark_hc", "win10_dark_hc.qss"),
        (CCCP_THEME_ID, "light", "cccp.qss"),
        (MACOS_THEME_ID, "dark", "macos_dark.qss"),
        ("does_not_exist", "light", "luna.qss"),
    ],
)
def test_qss_path_resolves_basename_and_suffix(theme_id, appearance_mode, expected_name):
    path = _qss_path(theme_id, appearance_mode)
    assert path.name == expected_name
    assert path.parent == theme_manager.resource_path("resources/styles")


# -- apply_theme -----------------------------------------------------------------


def test_apply_theme_sets_app_stylesheet_from_matching_file(qapp, monkeypatch, tmp_path):
    styles_dir = tmp_path / "resources" / "styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "luna.qss").write_text("QWidget { color: red; }", encoding="utf-8")

    monkeypatch.setattr(theme_manager, "resource_path", lambda relative: tmp_path / relative)
    qapp.setStyleSheet("")

    apply_theme(qapp, "luna_xp", "light")

    assert qapp.styleSheet() == "QWidget { color: red; }"
    qapp.setStyleSheet("")


def test_apply_theme_picks_the_right_variant_file_for_dark_hc(qapp, monkeypatch, tmp_path):
    styles_dir = tmp_path / "resources" / "styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "cccp.qss").write_text("wrong file", encoding="utf-8")
    (styles_dir / "cccp_dark_hc.qss").write_text("QWidget { color: yellow; }", encoding="utf-8")

    monkeypatch.setattr(theme_manager, "resource_path", lambda relative: tmp_path / relative)
    qapp.setStyleSheet("")

    apply_theme(qapp, CCCP_THEME_ID, "dark_hc")

    assert qapp.styleSheet() == "QWidget { color: yellow; }"
    qapp.setStyleSheet("")


def test_apply_theme_is_a_noop_when_qss_file_is_missing(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(theme_manager, "resource_path", lambda relative: tmp_path / relative)
    qapp.setStyleSheet("QWidget { color: blue; }")

    apply_theme(qapp, "luna_xp", "light")

    assert qapp.styleSheet() == "QWidget { color: blue; }"
    qapp.setStyleSheet("")
