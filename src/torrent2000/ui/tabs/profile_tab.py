import json
from dataclasses import asdict
from pathlib import Path

import psutil
from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrent2000.config.paths import get_config_path
from torrent2000.config.settings import Settings
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.session_manager import SessionManager
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.leveling import UPLOAD_LEVEL_WEIGHT, weighted_total_bytes
from torrent2000.stats.models import StatsSnapshot
from torrent2000.stats.service import StatsService
from torrent2000.ui.theme.theme_manager import THEME_LABELS
from torrent2000.utils.formatting import human_size

_PROXY_TYPE_LABELS = [
    ("Aucun", "none"),
    ("SOCKS5", "socks5"),
    ("SOCKS5 (avec authentification)", "socks5_pw"),
    ("HTTP", "http"),
    ("HTTP (avec authentification)", "http_pw"),
]

_ENCRYPTION_MODE_LABELS = [
    ("Désactivé", "disabled"),
    ("Activé (par défaut)", "enabled"),
    ("Forcé (anti-bridage FAI)", "forced"),
]

_SHUTDOWN_ACTION_LABELS = [
    ("Éteindre", "shutdown"),
    ("Mettre en veille prolongée", "hibernate"),
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
    theme_changed = Signal(str)

    def __init__(
        self,
        session_manager: SessionManager,
        stats_service: StatsService,
        bandwidth_scheduler: BandwidthScheduler,
        history_service: HistoryService,
        settings: Settings,
        disk_space_monitor: DiskSpaceMonitor,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._stats_service = stats_service
        self._bandwidth_scheduler = bandwidth_scheduler
        self._settings = settings
        self._disk_space_monitor = disk_space_monitor

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
        for label, theme_id in THEME_LABELS:
            self.theme_combo.addItem(label, theme_id)
        idx = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        general_form.addRow("Thème (base Windows XP) :", self.theme_combo)

        self.notifications_checkbox = QCheckBox(
            "Notifier la fin d'un téléchargement ou d'un partage", general_box
        )
        self.notifications_checkbox.setChecked(settings.notifications_enabled)
        general_form.addRow(self.notifications_checkbox)

        layout.addWidget(general_box)

        schedule_box = QGroupBox("Planification de la bande passante", self)
        schedule_form = QFormLayout(schedule_box)

        schedule = settings.bandwidth_schedule
        self.schedule_enabled_checkbox = QCheckBox("Activer une fenêtre de débit réduit", schedule_box)
        self.schedule_enabled_checkbox.setChecked(schedule.enabled)
        schedule_form.addRow(self.schedule_enabled_checkbox)

        hours_row = QHBoxLayout()
        self.schedule_start_spin = QSpinBox(schedule_box)
        self.schedule_start_spin.setRange(0, 23)
        self.schedule_start_spin.setSuffix(" h")
        self.schedule_start_spin.setValue(schedule.start_hour)
        hours_row.addWidget(QLabel("De", schedule_box))
        hours_row.addWidget(self.schedule_start_spin)
        self.schedule_end_spin = QSpinBox(schedule_box)
        self.schedule_end_spin.setRange(0, 23)
        self.schedule_end_spin.setSuffix(" h")
        self.schedule_end_spin.setValue(schedule.end_hour)
        hours_row.addWidget(QLabel("à", schedule_box))
        hours_row.addWidget(self.schedule_end_spin)
        hours_row.addStretch(1)
        schedule_form.addRow("Fenêtre réduite :", hours_row)

        self.schedule_download_spin = QSpinBox(schedule_box)
        self.schedule_download_spin.setRange(0, 1_000_000)
        self.schedule_download_spin.setSuffix(" Ko/s (0 = illimité)")
        self.schedule_download_spin.setValue(schedule.limited_download_kbps)
        schedule_form.addRow("Téléchargement réduit :", self.schedule_download_spin)

        self.schedule_upload_spin = QSpinBox(schedule_box)
        self.schedule_upload_spin.setRange(0, 1_000_000)
        self.schedule_upload_spin.setSuffix(" Ko/s (0 = illimité)")
        self.schedule_upload_spin.setValue(schedule.limited_upload_kbps)
        schedule_form.addRow("Envoi réduit :", self.schedule_upload_spin)

        schedule_note = QLabel(
            "En dehors de cette fenêtre, les limites générales ci-dessus s'appliquent. "
            "Une fenêtre qui traverse minuit (ex. 22h à 6h) est prise en charge.",
            schedule_box,
        )
        schedule_note.setWordWrap(True)
        schedule_form.addRow(schedule_note)

        layout.addWidget(schedule_box)

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

        config_box = QGroupBox("Configuration", self)
        config_layout = QHBoxLayout(config_box)
        export_button = QPushButton("Exporter la configuration...", config_box)
        export_button.clicked.connect(self._on_export_settings)
        config_layout.addWidget(export_button)
        import_button = QPushButton("Importer une configuration...", config_box)
        import_button.clicked.connect(self._on_import_settings)
        config_layout.addWidget(import_button)
        config_layout.addStretch(1)
        layout.addWidget(config_box)

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

        self.encryption_combo = QComboBox(network_box)
        for label, value in _ENCRYPTION_MODE_LABELS:
            self.encryption_combo.addItem(label, value)
        idx = self.encryption_combo.findData(settings.encryption_mode)
        self.encryption_combo.setCurrentIndex(max(0, idx))
        self.encryption_combo.setToolTip(
            "\"Forcé\" refuse tout échange en clair (utile contre le bridage de certains "
            "fournisseurs d'accès) mais peut empêcher la connexion à des pairs qui ne "
            "supportent pas le chiffrement. \"Activé\" (par défaut) préfère le chiffrement "
            "tout en gardant un repli en clair pour rester compatible avec un maximum de pairs."
        )
        network_form.addRow("Chiffrement du protocole :", self.encryption_combo)

        layout.addWidget(network_box)

        watch_folder_box = QGroupBox("Dossier surveillé", self)
        watch_folder_form = QFormLayout(watch_folder_box)

        self.watch_folder_enabled_checkbox = QCheckBox(
            "Ajouter automatiquement les fichiers .torrent déposés dans ce dossier", watch_folder_box
        )
        self.watch_folder_enabled_checkbox.setChecked(settings.watch_folder_enabled)
        watch_folder_form.addRow(self.watch_folder_enabled_checkbox)

        watch_folder_row = QHBoxLayout()
        self.watch_folder_input = QLineEdit(settings.watch_folder_path, watch_folder_box)
        watch_folder_row.addWidget(self.watch_folder_input)
        watch_folder_browse = QPushButton("Parcourir...", watch_folder_box)
        watch_folder_browse.clicked.connect(self._on_browse_watch_folder)
        watch_folder_row.addWidget(watch_folder_browse)
        watch_folder_form.addRow("Dossier à surveiller :", watch_folder_row)

        watch_folder_note = QLabel(
            "Les fichiers .torrent traités sont déplacés dans un sous-dossier \"processed\" "
            "pour ne jamais être ajoutés deux fois.",
            watch_folder_box,
        )
        watch_folder_note.setWordWrap(True)
        watch_folder_form.addRow(watch_folder_note)

        layout.addWidget(watch_folder_box)

        disk_space_box = QGroupBox("Espace disque", self)
        disk_space_form = QFormLayout(disk_space_box)

        self.disk_space_enabled_checkbox = QCheckBox(
            "Avertir quand l'espace libre devient faible sur un dossier de téléchargement actif",
            disk_space_box,
        )
        self.disk_space_enabled_checkbox.setChecked(settings.disk_space_warning_enabled)
        disk_space_form.addRow(self.disk_space_enabled_checkbox)

        self.disk_space_threshold_spin = QSpinBox(disk_space_box)
        self.disk_space_threshold_spin.setRange(1, 1_000_000)
        self.disk_space_threshold_spin.setSuffix(" Mo")
        self.disk_space_threshold_spin.setValue(settings.disk_space_warning_threshold_mb)
        disk_space_form.addRow("Seuil d'alerte :", self.disk_space_threshold_spin)

        layout.addWidget(disk_space_box)

        shutdown_box = QGroupBox("Extinction automatique", self)
        shutdown_form = QFormLayout(shutdown_box)

        self.shutdown_enabled_checkbox = QCheckBox(
            "Éteindre l'ordinateur une fois tous les téléchargements terminés", shutdown_box
        )
        self.shutdown_enabled_checkbox.setChecked(settings.auto_shutdown_enabled)
        shutdown_form.addRow(self.shutdown_enabled_checkbox)

        self.shutdown_action_combo = QComboBox(shutdown_box)
        for label, value in _SHUTDOWN_ACTION_LABELS:
            self.shutdown_action_combo.addItem(label, value)
        idx = self.shutdown_action_combo.findData(settings.auto_shutdown_action)
        self.shutdown_action_combo.setCurrentIndex(max(0, idx))
        shutdown_form.addRow("Action :", self.shutdown_action_combo)

        self.shutdown_delay_spin = QSpinBox(shutdown_box)
        self.shutdown_delay_spin.setRange(0, 3600)
        self.shutdown_delay_spin.setSuffix(" s")
        self.shutdown_delay_spin.setValue(settings.auto_shutdown_delay_seconds)
        shutdown_form.addRow("Délai avant extinction (annulable) :", self.shutdown_delay_spin)

        shutdown_note = QLabel(
            "Désactivé par défaut. Un compte à rebours annulable s'affiche avant toute "
            "extinction ou mise en veille réelle.",
            shutdown_box,
        )
        shutdown_note.setWordWrap(True)
        shutdown_form.addRow(shutdown_note)

        layout.addWidget(shutdown_box)

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

        history_box = QGroupBox("Historique des torrents retirés", self)
        history_layout = QVBoxLayout(history_box)
        self.history_table = QTableWidget(0, 5, history_box)
        self.history_table.setHorizontalHeaderLabels(["Nom", "Taille", "Téléchargé", "Envoyé", "Date"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setMaximumHeight(160)
        history_layout.addWidget(self.history_table)
        layout.addWidget(history_box)

        self._history_service = history_service
        history_service.entry_added.connect(self._refresh_history)
        self._refresh_history()

        layout.addStretch(1)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_button = QPushButton("Enregistrer", self)
        self.save_button.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_button)
        layout.addLayout(save_row)

        self._disk_space_monitor.low_space_warning.connect(self._on_low_space_warning)

    def _on_browse_dest(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination", self.dest_input.text())
        if directory:
            self.dest_input.setText(directory)

    def _on_browse_watch_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier à surveiller", self.watch_folder_input.text()
        )
        if directory:
            self.watch_folder_input.setText(directory)

    def _on_low_space_warning(self, save_path: str, message: str) -> None:
        QMessageBox.warning(self, "Espace disque faible", message)

    def _on_theme_changed(self, index: int) -> None:
        theme_id = self.theme_combo.itemData(index)
        if not theme_id:
            return
        # Applied immediately (live preview) rather than gated behind the
        # "Enregistrer" button -- a theme picker only really makes sense as
        # an instant switch, and it's low-stakes enough to persist right away.
        self._settings.theme = theme_id
        self._settings.save()
        self.theme_changed.emit(theme_id)

    def _on_export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la configuration", "torrent2000_config.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(asdict(self._settings), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Échec de l'export", str(exc))
            return
        QMessageBox.information(self, "Export réussi", f"Configuration exportée vers :\n{path}")

    def _on_import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer une configuration", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Échec de l'import", str(exc))
            return
        # Written straight to the real config file rather than trying to
        # live-patch every open widget/service -- simpler and avoids partial
        # application bugs. Applied fully on next launch.
        get_config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        QMessageBox.information(
            self, "Import réussi", "Configuration importée. Redémarrez Torrent 2000 pour l'appliquer."
        )

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
        self._settings.notifications_enabled = self.notifications_checkbox.isChecked()

        self._settings.bandwidth_schedule.enabled = self.schedule_enabled_checkbox.isChecked()
        self._settings.bandwidth_schedule.start_hour = self.schedule_start_spin.value()
        self._settings.bandwidth_schedule.end_hour = self.schedule_end_spin.value()
        self._settings.bandwidth_schedule.limited_download_kbps = self.schedule_download_spin.value()
        self._settings.bandwidth_schedule.limited_upload_kbps = self.schedule_upload_spin.value()

        self._settings.restrict_discovery = self.restrict_discovery_checkbox.isChecked()

        self._settings.proxy.enabled = self.proxy_enabled_checkbox.isChecked()
        self._settings.proxy.proxy_type = self.proxy_type_combo.currentData()
        self._settings.proxy.host = self.proxy_host_input.text().strip()
        self._settings.proxy.port = self.proxy_port_spin.value()
        self._settings.proxy.username = self.proxy_username_input.text()
        self._settings.proxy.password = self.proxy_password_input.text()
        self._settings.proxy.force_proxy = self.force_proxy_checkbox.isChecked()
        self._settings.network_interface = self.interface_combo.currentData() or ""
        self._settings.encryption_mode = self.encryption_combo.currentData()

        self._settings.watch_folder_enabled = self.watch_folder_enabled_checkbox.isChecked()
        self._settings.watch_folder_path = self.watch_folder_input.text().strip()

        self._settings.disk_space_warning_enabled = self.disk_space_enabled_checkbox.isChecked()
        self._settings.disk_space_warning_threshold_mb = self.disk_space_threshold_spin.value()

        self._settings.auto_shutdown_enabled = self.shutdown_enabled_checkbox.isChecked()
        self._settings.auto_shutdown_action = self.shutdown_action_combo.currentData()
        self._settings.auto_shutdown_delay_seconds = self.shutdown_delay_spin.value()

        self._settings.save()
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )
        self._session_manager.set_restrict_discovery(self._settings.restrict_discovery)
        self._session_manager.set_proxy(self._settings)
        self._session_manager.set_network_interface(self._settings.network_interface)
        self._session_manager.set_encryption_mode(self._settings.encryption_mode)
        self._bandwidth_scheduler.settings_changed()
        # Watch folder / disk space warning / auto-shutdown are read straight
        # off self._settings by their respective services on their next timer
        # tick -- no live-apply call is needed for those.

    def _refresh_history(self) -> None:
        entries = self._history_service.all_entries()
        self.history_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.history_table.setItem(row, 0, QTableWidgetItem(entry.name))
            self.history_table.setItem(row, 1, QTableWidgetItem(human_size(entry.total_size)))
            self.history_table.setItem(row, 2, QTableWidgetItem(human_size(entry.total_downloaded)))
            self.history_table.setItem(row, 3, QTableWidgetItem(human_size(entry.total_uploaded)))
            self.history_table.setItem(row, 4, QTableWidgetItem(entry.finished_at))

    def _on_snapshot_updated(self, snap: StatsSnapshot) -> None:
        self.level_label.setText(f"Niveau {snap.level}")
        self.level_progress_bar.setValue(int(snap.progress_to_next * 1000))
        weighted = weighted_total_bytes(snap.total_downloaded, snap.total_uploaded)
        self.level_progress_bar.setFormat(f"{human_size(weighted)} / {human_size(snap.next_threshold)}")
        self.totals_label.setText(
            f"Téléchargé : {human_size(snap.total_downloaded)} -- Envoyé : {human_size(snap.total_uploaded)} "
            f"(compté à {int(UPLOAD_LEVEL_WEIGHT * 100)}% pour le niveau)"
        )
