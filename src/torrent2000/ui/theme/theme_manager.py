"""Multi-theme support: 5 shapes (Windows XP -- the default/base look --
7, 10, 11, and 95) each combinable with 3 appearance modes (light, dark,
dark high-contrast).

QSS handles the body chrome (buttons, tabs, inputs...) per (theme,
appearance) pair via a dedicated stylesheet file. The custom title bar
(native OS chrome can't be restyled -- see widgets/app_title_bar.py) is
parameterized through TitleBarStyle: XP/7/95 keep their characteristic
colorful caption regardless of appearance mode (matching how those real OS
eras had no concept of a system dark mode), while 10/11's flat caption
darkens for "dark" and turns solid black for "dark_hc"; button glyph
rendering (colored-box vs modern-flat) and window corner rounding (11 only)
are also per-theme.
"""

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDir
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from torrent2000.utils.resource_path import resource_path

DEFAULT_THEME = "luna_xp"
DEFAULT_APPEARANCE_MODE = "light"

THEME_LABELS: list[tuple[str, str]] = [
    ("Windows XP (Luna)", "luna_xp"),
    ("Windows 7 (Aero)", "win7_aero"),
    ("Windows 10", "win10_fluent"),
    ("Windows 11", "win11_mica"),
    ("Windows 95", "win95_classic"),
]

APPEARANCE_MODE_LABELS: list[tuple[str, str]] = [
    ("Clair", "light"),
    ("Sombre", "dark"),
    ("Sombre (contraste élevé)", "dark_hc"),
]

_APPEARANCE_SUFFIX = {"light": "", "dark": "_dark", "dark_hc": "_dark_hc"}

_QSS_BASENAMES = {
    "luna_xp": "luna",
    "win7_aero": "win7",
    "win10_fluent": "win10",
    "win11_mica": "win11",
    "win95_classic": "win95",
}


@dataclass(frozen=True)
class TitleBarStyle:
    caption_gradient: Optional[tuple[str, str]]  # (left, right) horizontal gradient, or None for flat
    caption_flat_color: str  # used when caption_gradient is None
    title_text_color: str
    font_family: str
    font_bold: bool
    button_variant: str  # "xp" | "modern"
    button_hover_radius: int  # hover-highlight corner radius, "modern" variant only
    window_corner_radius: int  # 0 = square window corners
    minmax_fill_color: str = "#3D6FC9"  # "xp" variant only
    minmax_hover_color: str = "#5C8CE0"
    close_fill_color: str = "#D42A2A"
    close_hover_color: str = "#F04A3C"
    button_glyph_color: str = "#FFFFFF"  # "xp" variant only ("modern" tracks title_text_color instead)
    # Overrides button_glyph_color while hovering, "xp" variant only. None
    # means "same as button_glyph_color" (every existing theme's validated
    # hover look is unchanged). Only dark_hc sets this, because its yellow
    # hover fill needs a black glyph to stay legible -- a white glyph on
    # yellow would fail contrast, which a high-contrast mode can't afford.
    button_hover_glyph_color: Optional[str] = None


TITLE_BAR_STYLES: dict[str, TitleBarStyle] = {
    "luna_xp": TitleBarStyle(
        caption_gradient=("#3169C6", "#0A246A"),
        caption_flat_color="#0A246A",
        title_text_color="#FFFFFF",
        font_family="Tahoma",
        font_bold=True,
        button_variant="xp",
        button_hover_radius=0,
        window_corner_radius=0,
    ),
    "win7_aero": TitleBarStyle(
        # Glassy light-blue Aero gradient.
        caption_gradient=("#DBEAFB", "#7EB0E8"),
        caption_flat_color="#8CB6E8",
        title_text_color="#000000",
        font_family="Segoe UI",
        font_bold=False,
        button_variant="modern",
        button_hover_radius=0,
        window_corner_radius=6,
    ),
    "win10_fluent": TitleBarStyle(
        caption_gradient=None,
        caption_flat_color="#FFFFFF",
        title_text_color="#000000",
        font_family="Segoe UI",
        font_bold=False,
        button_variant="modern",
        button_hover_radius=0,
        window_corner_radius=0,
    ),
    "win11_mica": TitleBarStyle(
        caption_gradient=None,
        caption_flat_color="#F3F3F3",
        title_text_color="#000000",
        font_family="Segoe UI",
        font_bold=False,
        button_variant="modern",
        button_hover_radius=4,
        window_corner_radius=8,
    ),
    "win95_classic": TitleBarStyle(
        # Flat navy, no gradient -- 95's caption was solid, not glassy.
        caption_gradient=None,
        caption_flat_color="#000080",
        title_text_color="#FFFFFF",
        font_family="MS Sans Serif",
        font_bold=True,
        button_variant="xp",
        button_hover_radius=0,
        window_corner_radius=0,
        # 95's caption buttons are all uniform light gray, not blue/red.
        minmax_fill_color="#C0C0C0",
        minmax_hover_color="#D4D0C8",
        close_fill_color="#C0C0C0",
        close_hover_color="#D4D0C8",
        button_glyph_color="#000000",
    ),
}

# Only flat-caption themes (10/11) actually darken their title bar for dark
# mode -- XP/7/95's colorful captions are kept as-is in "dark" (those OS eras
# had no system dark mode of their own, so there is no authentic "dark
# caption" to reproduce; only the body chrome below the caption changes).
_DARK_TITLE_BAR_OVERRIDES = {
    "win10_fluent": {"caption_flat_color": "#202020", "title_text_color": "#FFFFFF"},
    "win11_mica": {"caption_flat_color": "#202020", "title_text_color": "#FFFFFF"},
}


def title_bar_style_for(theme_id: str, appearance_mode: str = DEFAULT_APPEARANCE_MODE) -> TitleBarStyle:
    base = TITLE_BAR_STYLES.get(theme_id, TITLE_BAR_STYLES[DEFAULT_THEME])
    if appearance_mode == "dark_hc":
        # True high-contrast: every theme's caption becomes solid black with
        # white text, matching the real OS "High Contrast Black" convention,
        # regardless of the theme's normal caption look. The "xp" button
        # variant's colored min/max/close squares (XP's blue, 95's gray) are
        # also folded into the same black/white/yellow scheme -- otherwise
        # they'd keep their normal-mode theme colors while everything else
        # (caption, body chrome via the *_dark_hc.qss files) goes stark
        # black/white/yellow, breaking the high-contrast look's consistency.
        return dataclasses.replace(
            base,
            caption_gradient=None,
            caption_flat_color="#000000",
            title_text_color="#FFFFFF",
            minmax_fill_color="#000000",
            minmax_hover_color="#FFFF00",
            close_fill_color="#000000",
            close_hover_color="#FFFF00",
            button_glyph_color="#FFFFFF",
            button_hover_glyph_color="#000000",
        )
    if appearance_mode == "dark":
        overrides = _DARK_TITLE_BAR_OVERRIDES.get(theme_id)
        if overrides:
            return dataclasses.replace(base, **overrides)
    return base


def _qss_path(theme_id: str, appearance_mode: str) -> Path:
    basename = _QSS_BASENAMES.get(theme_id, _QSS_BASENAMES[DEFAULT_THEME])
    suffix = _APPEARANCE_SUFFIX.get(appearance_mode, "")
    return resource_path("resources/styles") / f"{basename}{suffix}.qss"


def apply_theme(app: QApplication, theme_id: str, appearance_mode: str = DEFAULT_APPEARANCE_MODE) -> None:
    qss_path = _qss_path(theme_id, appearance_mode)
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def init_theme_runtime(app: QApplication) -> None:
    """One-time setup: register the search path used by QSS `image: url(...)`
    references, and set the app-wide window icon. Call once at startup,
    independently of which theme ends up applied."""
    assets_dir = resource_path("assets")
    if assets_dir.exists():
        QDir.addSearchPath("theme", str(assets_dir))

    icon_path = resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
