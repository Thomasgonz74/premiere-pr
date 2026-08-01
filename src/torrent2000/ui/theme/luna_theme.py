from PySide6.QtCore import QDir
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from torrent2000.utils.resource_path import resource_path


def apply_luna_theme(app: QApplication) -> None:
    # Registered so the QSS can reference bundled images as "theme:name.png"
    # regardless of cwd or whether the app is frozen (PyInstaller) -- a plain
    # relative url() in a stylesheet loaded from a string is not reliably
    # resolvable otherwise.
    assets_dir = resource_path("assets")
    if assets_dir.exists():
        QDir.addSearchPath("theme", str(assets_dir))

    qss_path = resource_path("resources/styles/luna.qss")
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    icon_path = resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
