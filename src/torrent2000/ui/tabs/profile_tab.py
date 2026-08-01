import psutil
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.stats.models import StatsSnapshot
from torrent2000.stats.service import StatsService
from torrent2000.utils.formatting import human_size

_PROXY_TYPE_LABELS = [
    ("Aucun", "none"),
    ("SOCKS5", "socks5"),
    ("SOCKS5 (avec authentification)", "socks5_pw"),
    ("HTTP", "http"),
    ("HTTP (avec authentification)", "http_pw"),
]


def _list_local_ipv4_interfaces() -> list[tuple[str, str]]:
    """Returns (display_label, ip_address) pairs for non-loopback IPv4
    adapters, so the user can bind outgoing torrent traffic to a specific
    network adapter (e.g. a VPN's virtual adapter) for IP masking."""
    entries = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if getattr(addr.family, "name", "") == "AF_INET" and not addr.address.startswith("127."):
                entries.append((f"{name} ({addr.address})", addr.address))
                break
    return entries


class ProfileTab(QWidget):
    def __init__(
        self, session_manager: SessionManager, stats_service: StatsService, settings: Settings, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._stats_service = stats_service
        self._settings = settings

        layout = QVBoxLayout(self)

        general_box = QGroupBox("Paramètres généraux", self)
        general_form = QFormLayout(general_box)

        dest_row = QHBoxLayout()
        self.dest_input = QLineEdit(settings.default_download_dir, general_box)
        dest_row.addWidget(self.dest_input)
        dest_browse = QPushButton("Parcourir...", general_box)
        dest_browse.clicked.connect(self._on_browse_dest)
        dest_row.addWidget(dest_browse)
        general_form.addRow("Dossier de destination par défaut :", dest_row)

        self.download_limit_spin = QSpinBox(general_box)
        self.download_limit_spin.setRange(0, 1_000_000)
        self.download_limit_spin.setSuffix(" Ko/s (0 = illimité)")
        self.download_limit_spin.setValue(settings.download_rate_limit_kbps)
        general_form.addRow("Limite de téléchargement :", self.download_limit_spin)

        self.upload_limit_spin = QSpinBox(general_box)
        self.upload_limit_spin.setRange(0, 1_000_000)
        self.upload_limit_spin.setSuffix(" Ko/s (0 = illimité)")
        self.upload_limit_spin.setValue(settings.upload_rate_limit_kbps)
        general_form.addRow("Limite d'envoi :", self.upload_limit_spin)

        self.danger_threshold_spin = QSpinBox(general_box)
        self.danger_threshold_spin.setRange(0, 100)
        self.danger_threshold_spin.setValue(settings.danger_auto_exclude_threshold)
        general_form.addRow("Seuil d'auto-exclusion des fichiers dangereux :", self.danger_threshold_spin)

        self.theme_combo = QComboBox(general_box)
        self.theme_combo.addItem("Windows XP (Luna)", "luna_xp")
        self.theme_combo.setCurrentIndex(0)
        general_form.addRow("Thème :", self.theme_combo)

        layout.addWidget(general_box)

        security_box = QGroupBox("Sécurité", self)
        security_layout = QVBoxLayout(security_box)
        defender_button = QPushButton("Ouvrir les exclusions Windows Security...", security_box)
        defender_button.clicked.connect(self._on_open_defender_settings)
        security_layout.addWidget(defender_button)
        security_note = QLabel(
            "Ouvre le panneau des exclusions de Windows Security. Torrent 2000 n'ajoute "
            "jamais d'exclusion automatiquement -- c'est à vous de le faire si vous le souhaitez.",
            security_box,
        )
        security_note.setWordWrap(True)
        security_layout.addWidget(security_note)
        layout.addWidget(security_box)

        network_box = QGroupBox("Confidentialité", self)
        network_box_layout = QVBoxLayout(network_box)

        privacy_intro = QLabel(
            "Par défaut, Torrent 2000 réduit les informations identifiantes envoyées aux "
            "autres utilisateurs et limite la diffusion de votre présence sur le réseau "
            "(DHT, PEX et LSD désactivés).\n\n"
            "Attention : aucun logiciel ne peut masquer votre adresse IP réelle aux autres "
            "utilisateurs d'un torrent sans faire transiter votre trafic par un relais "
            "externe (VPN ou proxy) -- c'est une contrainte du protocole BitTorrent "
            "lui-même, pas une limitation de cette application. Si vous disposez déjà "
            "d'un VPN ou d'un proxy, configurez-le ci-dessous pour masquer réellement "
            "votre adresse IP.",
            network_box,
        )
        privacy_intro.setWordWrap(True)
        network_box_layout.addWidget(privacy_intro)

        self.restrict_discovery_checkbox = QCheckBox(
            "Réduire la diffusion de ma présence sur le réseau (désactive DHT, PEX et LSD)",
            network_box,
        )
        self.restrict_discovery_checkbox.setChecked(settings.restrict_discovery)
        self.restrict_discovery_checkbox.setToolTip(
            "Le DHT publie votre adresse IP dans un réseau public de plusieurs milliers "
            "de nœuds, bien au-delà des seuls participants de vos torrents. Le PEX et le "
            "LSD diffusent aussi votre présence à des pairs supplémentaires. Désactiver "
            "ces trois mécanismes réduit la portée de cette diffusion, mais ne masque pas "
            "votre IP aux pairs avec lesquels vous échangez directement des données -- "
            "seul un proxy/VPN ci-dessous peut faire cela."
        )
        network_box_layout.addWidget(self.restrict_discovery_checkbox)

        network_form = QFormLayout()
        network_box_layout.addLayout(network_form)

        self.proxy_enabled_checkbox = QCheckBox("Activer le proxy", network_box)
        self.proxy_enabled_checkbox.setChecked(settings.proxy.enabled)
        network_form.addRow(self.proxy_enabled_checkbox)

        self.proxy_type_combo = QComboBox(network_box)
        for label, value in _PROXY_TYPE_LABELS:
            self.proxy_type_combo.addItem(label, value)
        idx = self.proxy_type_combo.findData(settings.proxy.proxy_type)
        self.proxy_type_combo.setCurrentIndex(max(0, idx))
        network_form.addRow("Type de proxy :", self.proxy_type_combo)

        self.proxy_host_input = QLineEdit(settings.proxy.host, network_box)
        self.proxy_host_input.setPlaceholderText("proxy.example.com")
        network_form.addRow("Hôte :", self.proxy_host_input)

        self.proxy_port_spin = QSpinBox(network_box)
        self.proxy_port_spin.setRange(0, 65535)
        self.proxy_port_spin.setValue(settings.proxy.port)
        network_form.addRow("Port :", self.proxy_port_spin)

        self.proxy_username_input = QLineEdit(settings.proxy.username, network_box)
        network_form.addRow("Utilisateur :", self.proxy_username_input)

        self.proxy_password_input = QLineEdit(settings.proxy.password, network_box)
        self.proxy_password_input.setEchoMode(QLineEdit.Password)
        network_form.addRow("Mot de passe :", self.proxy_password_input)

        self.force_proxy_checkbox = QCheckBox(
            "Empêcher toute connexion directe si le proxy est indisponible (coupe-circuit)",
            network_box,
        )
        self.force_proxy_checkbox.setChecked(settings.proxy.force_proxy)
        self.force_proxy_checkbox.setToolTip(
            "Coupe-circuit : si le proxy tombe ou refuse la connexion, Torrent 2000 "
            "bloque le trafic au lieu de se rabattre silencieusement sur une connexion "
            "directe qui exposerait votre adresse IP réelle."
        )
        network_form.addRow(self.force_proxy_checkbox)

        self.interface_combo = QComboBox(network_box)
        self.interface_combo.addItem("Toutes les interfaces (par défaut)", "")
        self._interfaces = _list_local_ipv4_interfaces()
        for label, ip in self._interfaces:
            self.interface_combo.addItem(label, ip)
        idx = self.interface_combo.findData(settings.network_interface)
        self.interface_combo.setCurrentIndex(max(0, idx))
        network_form.addRow("Interface réseau / VPN :", self.interface_combo)

        layout.addWidget(network_box)

        self.leveling_box = QGroupBox("Niveau", self)
        leveling_layout = QVBoxLayout(self.leveling_box)
        self.level_label = QLabel("Niveau 0", self.leveling_box)
        leveling_layout.addWidget(self.level_label)
        self.level_progress_bar = QProgressBar(self.leveling_box)
        self.level_progress_bar.setRange(0, 1000)
        leveling_layout.addWidget(self.level_progress_bar)
        self.totals_label = QLabel("Téléchargé : 0 o -- Envoyé : 0 o", self.leveling_box)
        leveling_layout.addWidget(self.totals_label)
        layout.addWidget(self.leveling_box)

        stats_service.snapshot_updated.connect(self._on_snapshot_updated)
        self._on_snapshot_updated(stats_service.current_snapshot())

        layout.addStretch(1)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_button = QPushButton("Enregistrer", self)
        self.save_button.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_button)
        layout.addLayout(save_row)

    def _on_browse_dest(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination", self.dest_input.text())
        if directory:
            self.dest_input.setText(directory)

    def _on_open_defender_settings(self) -> None:
        # Opens the Windows Security app to its exclusions page. The user adds
        # any exclusion themselves -- this app never writes to Defender's
        # exclusion list programmatically.
        QDesktopServices.openUrl(QUrl("windowsdefender://threatsettings"))

    def _on_save_clicked(self) -> None:
        self._settings.default_download_dir = self.dest_input.text().strip() or self._settings.default_download_dir
        self._settings.download_rate_limit_kbps = self.download_limit_spin.value()
        self._settings.upload_rate_limit_kbps = self.upload_limit_spin.value()
        self._settings.danger_auto_exclude_threshold = self.danger_threshold_spin.value()

        self._settings.restrict_discovery = self.restrict_discovery_checkbox.isChecked()

        self._settings.proxy.enabled = self.proxy_enabled_checkbox.isChecked()
        self._settings.proxy.proxy_type = self.proxy_type_combo.currentData()
        self._settings.proxy.host = self.proxy_host_input.text().strip()
        self._settings.proxy.port = self.proxy_port_spin.value()
        self._settings.proxy.username = self.proxy_username_input.text()
        self._settings.proxy.password = self.proxy_password_input.text()
        self._settings.proxy.force_proxy = self.force_proxy_checkbox.isChecked()
        self._settings.network_interface = self.interface_combo.currentData() or ""

        self._settings.save()
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )
        self._session_manager.set_restrict_discovery(self._settings.restrict_discovery)
        self._session_manager.set_proxy(self._settings)
        self._session_manager.set_network_interface(self._settings.network_interface)

    def _on_snapshot_updated(self, snap: StatsSnapshot) -> None:
        self.level_label.setText(f"Niveau {snap.level}")
        self.level_progress_bar.setValue(int(snap.progress_to_next * 1000))
        self.level_progress_bar.setFormat(
            f"{human_size(snap.total_downloaded + snap.total_uploaded)} / {human_size(snap.next_threshold)}"
        )
        self.totals_label.setText(
            f"Téléchargé : {human_size(snap.total_downloaded)} -- Envoyé : {human_size(snap.total_uploaded)}"
        )
