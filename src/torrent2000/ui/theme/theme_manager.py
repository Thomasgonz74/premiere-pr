"""Multi-theme support: Windows XP (the default/base look), 7, 10 and 11.

QSS handles the body chrome (buttons, tabs, inputs...) per theme via a
dedicated stylesheet file. The custom title bar (native OS chrome can't be
restyled -- see widgets/app_title_bar.py) is parameterized per theme through
TitleBarStyle, since XP/7 use a gradient caption while 10/11 use a flat one,
button glyph rendering differs, and 11 additionally rounds the window's
corners.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDir
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from torrent2000.utils.resource_path import resource_path

DEFAULT_THEME = "luna_xp"

THEME_LABELS: list[tuple[str, str]] = [
    ("Windows XP (Luna)", "luna_xp"),
    ("Windows 7 (Aero)", "win7_aero"),
    ("Windows 10", "win10_fluent"),
    ("Windows 11", "win11_mica"),
]

_QSS_FILENAMES = {
    "luna_xp": "luna.qss",
    "win7_aero": "win7.qss",
    "win10_fluent": "win10.qss",
    "win11_mica": "win11.qss",
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
}


def title_bar_style_for(theme_id: str) -> TitleBarStyle:
    return TITLE_BAR_STYLES.get(theme_id, TITLE_BAR_STYLES[DEFAULT_THEME])


def _qss_path(theme_id: str) -> Path:
    filename = _QSS_FILENAMES.get(theme_id, _QSS_FILENAMES[DEFAULT_THEME])
    return resource_path("resources/styles") / filename


def apply_theme(app: QApplication, theme_id: str) -> None:
    qss_path = _qss_path(theme_id)
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
