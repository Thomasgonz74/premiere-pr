"""Profile tab section for engine/remote_server.py -- lets the user opt in to
checking/pausing torrents from a phone on the same local network.

Follows the section pattern documented at the top of
ui/tabs/profile_sections.py, with one deliberate live-apply exception: the
enable checkbox starts/stops the actual RemoteAccessServer immediately
(there's no meaningful "preview" of a listening socket, and leaving it
running-but-unpersisted until Save would be surprising) while
remote_access_enabled/remote_access_port themselves are still only written
to Settings on Save, exactly like every other field in this section --
write_to() below is the only thing that persists them.

_list_local_ipv4_interfaces-equivalent detection is reimplemented locally
here (see _detect_local_ipv4) rather than imported from profile_sections.py,
so this module has no dependency on that one.
"""

import secrets

import psutil
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from torrent2000.config.settings import Settings
from torrent2000.engine.remote_server import RemoteAccessServer
from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import tr


def _detect_local_ipv4() -> str:
    """First non-loopback IPv4 address found on any adapter, or "" if none --
    same technique as profile_sections.py::_list_local_ipv4_interfaces, just
    collapsed to a single best-effort address since this only needs one to
    build a URL, not a full picker."""
    for _name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if getattr(addr.family, "name", "") == "AF_INET" and not addr.address.startswith("127."):
                return addr.address
    return ""


def _add_row(form: QFormLayout, form_labels: dict[str, QLabel], key: str, field) -> None:
    label = QLabel(tr(key), form.parentWidget())
    form_labels[key] = label
    form.addRow(label, field)


class RemoteAccessSection(QGroupBox):
    """Opt-in local-network remote access: enable/disable, the URL+port+token
    a phone needs, and a way to regenerate the token."""

    def __init__(self, settings: Settings, session_manager: SessionManager, parent=None) -> None:
        super().__init__(tr("remote_access.group"), parent)
        self._settings = settings
        self._server = RemoteAccessServer(session_manager, settings)
        self._form_labels: dict[str, QLabel] = {}
        self._token_visible = False

        layout = QVBoxLayout(self)

        self.enabled_checkbox = QCheckBox(tr("remote_access.enabled_checkbox"), self)
        self.enabled_checkbox.setChecked(settings.remote_access_enabled)
        self.enabled_checkbox.toggled.connect(self._on_enabled_toggled)
        layout.addWidget(self.enabled_checkbox)

        form = QFormLayout()
        layout.addLayout(form)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit(self)
        self.url_input.setReadOnly(True)
        url_row.addWidget(self.url_input)
        self.copy_url_button = QPushButton(tr("remote_access.copy_button"), self)
        self.copy_url_button.clicked.connect(self._on_copy_url)
        url_row.addWidget(self.copy_url_button)
        _add_row(form, self._form_labels, "remote_access.url_label", url_row)

        self.port_spin = QSpinBox(self)
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(settings.remote_access_port)
        _add_row(form, self._form_labels, "remote_access.port_label", self.port_spin)

        token_row = QHBoxLayout()
        self.token_input = QLineEdit(self)
        self.token_input.setReadOnly(True)
        self.token_input.setEchoMode(QLineEdit.Password)
        token_row.addWidget(self.token_input)
        self.reveal_token_button = QPushButton(tr("remote_access.reveal_button"), self)
        self.reveal_token_button.clicked.connect(self._on_toggle_token_visibility)
        token_row.addWidget(self.reveal_token_button)
        self.copy_token_button = QPushButton(tr("remote_access.copy_button"), self)
        self.copy_token_button.clicked.connect(self._on_copy_token)
        token_row.addWidget(self.copy_token_button)
        _add_row(form, self._form_labels, "remote_access.token_label", token_row)

        regenerate_row = QHBoxLayout()
        self.regenerate_token_button = QPushButton(tr("remote_access.regenerate_button"), self)
        self.regenerate_token_button.clicked.connect(self._on_regenerate_token)
        regenerate_row.addWidget(self.regenerate_token_button)
        regenerate_row.addStretch(1)
        layout.addLayout(regenerate_row)

        self.remote_access_note = QLabel(tr("remote_access.note"), self)
        self.remote_access_note.setWordWrap(True)
        layout.addWidget(self.remote_access_note)

        # Belt-and-suspenders alongside app.py's own aboutToQuit wiring for
        # its separate long-lived instance (see engine/remote_server.py's
        # module docstring for why there can be two RemoteAccessServer
        # objects in play) -- whichever of the two actually holds the
        # socket, this makes sure IT gets shut down cleanly too.
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.aboutToQuit.connect(self._server.stop)

        self._refresh_display()

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("remote_access.group"))
        self.enabled_checkbox.setText(tr("remote_access.enabled_checkbox"))
        self.copy_url_button.setText(tr("remote_access.copy_button"))
        self.copy_token_button.setText(tr("remote_access.copy_button"))
        self.reveal_token_button.setText(tr("remote_access.hide_button" if self._token_visible else "remote_access.reveal_button"))
        self.regenerate_token_button.setText(tr("remote_access.regenerate_button"))
        self.remote_access_note.setText(tr("remote_access.note"))
        self._refresh_display()

    def write_to(self, settings: Settings) -> None:
        settings.remote_access_enabled = self.enabled_checkbox.isChecked()
        settings.remote_access_port = self.port_spin.value()

    def _on_enabled_toggled(self, checked: bool) -> None:
        # Immediate, no Save needed -- see module docstring. Only the actual
        # server process reacts here; settings.remote_access_enabled itself
        # is still only persisted via write_to() on Save.
        if checked:
            if not self._server.start():
                # Bind failed (port already in use, no permission, etc.) --
                # revert the checkbox and say so, and clear the token via the
                # same cleanup as the "off" path below, instead of letting
                # _refresh_display() show a convincing but non-functional
                # token+URL (it only checks whether a token exists, which by
                # this point it always does -- see RemoteAccessServer.start).
                self.enabled_checkbox.blockSignals(True)
                self.enabled_checkbox.setChecked(False)
                self.enabled_checkbox.blockSignals(False)
                self._clear_token()
                QMessageBox.warning(
                    self,
                    tr("remote_access.group"),
                    tr("remote_access.bind_failed_message", port=self._settings.remote_access_port),
                )
        else:
            self._server.stop()
            # self._server.stop() above is a no-op unless THIS section's own
            # instance happens to be the one holding the socket (usually
            # app.py's separate long-lived instance is -- see this module's
            # constructor and engine/remote_server.py's docstring). Without
            # this, unchecking the box would silently lie: the checkbox
            # reads "off" while the real server is still listening and the
            # still-valid token still works. Clearing the token instead
            # guarantees every request is rejected from here on (see
            # _RemoteAccessHandler._token_is_valid: an empty expected token
            # denies everything) regardless of which instance actually holds
            # the socket, since both read settings.remote_access_token fresh
            # per request off the same shared Settings object.
            self._clear_token()
        self._refresh_display()

    def _clear_token(self) -> None:
        if self._settings.remote_access_token:
            self._settings.remote_access_token = ""
            self._settings.save()

    def _on_toggle_token_visibility(self) -> None:
        self._token_visible = not self._token_visible
        self.token_input.setEchoMode(QLineEdit.Normal if self._token_visible else QLineEdit.Password)
        self.reveal_token_button.setText(tr("remote_access.hide_button" if self._token_visible else "remote_access.reveal_button"))

    def _on_copy_token(self) -> None:
        QApplication.clipboard().setText(self._settings.remote_access_token)

    def _on_copy_url(self) -> None:
        QApplication.clipboard().setText(self.url_input.text())

    def _on_regenerate_token(self) -> None:
        # Persisted immediately (not gated behind Save) -- the whole point
        # is invalidating the old token right away, and the running server
        # (whichever instance actually holds the socket) reads
        # settings.remote_access_token fresh on every request, so this takes
        # effect on its very next request with no restart needed.
        self._settings.remote_access_token = secrets.token_urlsafe(24)
        self._settings.save()
        self._refresh_display()

    def _refresh_display(self) -> None:
        token = self._settings.remote_access_token
        has_token = bool(token)
        self.token_input.setText(token)
        self.reveal_token_button.setEnabled(has_token)
        self.copy_token_button.setEnabled(has_token)

        ip = _detect_local_ipv4()
        if has_token and ip:
            self.url_input.setText(f"http://{ip}:{self._settings.remote_access_port}/?token={token}")
        elif has_token:
            self.url_input.setText(tr("remote_access.no_network_detected"))
        else:
            self.url_input.setText(tr("remote_access.not_started_yet"))
        self.copy_url_button.setEnabled(has_token and bool(ip))
