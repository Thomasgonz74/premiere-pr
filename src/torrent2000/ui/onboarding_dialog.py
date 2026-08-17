"""One-time welcome dialog shown on the very first launch, pointing new
users at the Profile tab's privacy/network settings (proxy, encryption,
network discovery) -- otherwise nothing in the app's default "Add" tab
signals that those settings exist."""

from PySide6.QtWidgets import QMessageBox

from torrent2000.config.settings import Settings
from torrent2000.i18n.translator import tr


def maybe_show_onboarding(parent, settings: Settings) -> None:
    if settings.first_launch_seen:
        return
    box = QMessageBox(parent)
    box.setWindowTitle(tr("onboarding.title"))
    box.setText(tr("onboarding.message"))
    box.addButton(tr("onboarding.ok_button"), QMessageBox.AcceptRole)
    box.exec()
    settings.first_launch_seen = True
    settings.save()
