"""Lets the user save the current proxy/encryption/notifications/rate-limit/
discovery settings as a named profile (e.g. "voyage", "connexion mobile") and
re-apply that whole bundle in one click later, instead of reopening the
Profile tab and changing each field by hand.

Follows profile_sections.py's live-apply convention (see that module's
docstring): applying a profile is a one-click action with an immediate,
visible effect, so it saves to disk and pushes the change into the running
session right away rather than waiting for ProfileTab's Save button --
write_to() therefore has nothing left to do.
"""

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.settings_profiles import SettingsProfile, SettingsProfileStore
from torrent2000.i18n.translator import tr


class SettingsProfilesSection(QGroupBox):
    """Save/apply/delete named SettingsProfile bundles."""

    def __init__(self, settings: Settings, session_manager: SessionManager, parent=None) -> None:
        super().__init__(tr("settings_profiles.group"), parent)
        self._settings = settings
        self._session_manager = session_manager
        self._store = SettingsProfileStore()
        self._profiles_by_name: dict[str, SettingsProfile] = {}

        layout = QVBoxLayout(self)

        self.intro_label = QLabel(tr("settings_profiles.intro"), self)
        self.intro_label.setWordWrap(True)
        layout.addWidget(self.intro_label)

        form = QFormLayout()
        layout.addLayout(form)
        self.profile_combo = QComboBox(self)
        self.profile_label = QLabel(tr("settings_profiles.profile_label"), self)
        form.addRow(self.profile_label, self.profile_combo)

        button_row = QHBoxLayout()
        self.apply_button = QPushButton(tr("settings_profiles.apply_button"), self)
        self.apply_button.clicked.connect(self._on_apply_clicked)
        button_row.addWidget(self.apply_button)
        self.save_as_button = QPushButton(tr("settings_profiles.save_as_button"), self)
        self.save_as_button.clicked.connect(self._on_save_as_clicked)
        button_row.addWidget(self.save_as_button)
        self.delete_button = QPushButton(tr("settings_profiles.delete_button"), self)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._refresh_profile_combo()

    def retranslate_ui(self) -> None:
        self.setTitle(tr("settings_profiles.group"))
        self.intro_label.setText(tr("settings_profiles.intro"))
        self.profile_label.setText(tr("settings_profiles.profile_label"))
        self.apply_button.setText(tr("settings_profiles.apply_button"))
        self.save_as_button.setText(tr("settings_profiles.save_as_button"))
        self.delete_button.setText(tr("settings_profiles.delete_button"))

    def write_to(self, settings: Settings) -> None:
        pass  # every action here already applies and persists immediately

    def _refresh_profile_combo(self, select_name: str | None = None) -> None:
        profiles = self._store.list_profiles()
        self._profiles_by_name = {profile.name: profile for profile in profiles}
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in profiles:
            self.profile_combo.addItem(profile.name, profile.name)
        if select_name is not None:
            idx = self.profile_combo.findData(select_name)
            self.profile_combo.setCurrentIndex(max(0, idx))
        self.profile_combo.blockSignals(False)
        has_profiles = bool(profiles)
        self.apply_button.setEnabled(has_profiles)
        self.delete_button.setEnabled(has_profiles)

    def _selected_profile(self) -> SettingsProfile | None:
        name = self.profile_combo.currentData()
        if not name:
            return None
        return self._profiles_by_name.get(name)

    def _on_apply_clicked(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        # Same live-apply calls, in the same order, as ProfileTab's Save
        # button (see profile_tab.py's _on_save_clicked) -- applying a
        # profile is meant to behave exactly like reviewing and saving those
        # same fields by hand, just in one click.
        self._store.apply_to_settings(profile, self._settings)
        self._settings.save()
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )
        self._session_manager.set_restrict_discovery(self._settings.restrict_discovery)
        self._session_manager.set_proxy(self._settings)
        self._session_manager.set_encryption_mode(self._settings.encryption_mode)

    def _on_save_as_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, tr("settings_profiles.save_as_title"), tr("settings_profiles.save_as_label"))
        name = name.strip()
        if not ok or not name:
            return
        self._store.save_from_settings(name, self._settings)
        self._refresh_profile_combo(select_name=name)

    def _on_delete_clicked(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        reply = QMessageBox.question(
            self,
            tr("settings_profiles.delete_confirm_title"),
            tr("settings_profiles.delete_confirm_message", name=profile.name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._store.delete(profile.name)
        self._refresh_profile_combo()
