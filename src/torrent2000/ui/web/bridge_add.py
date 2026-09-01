"""QWebChannel bridge backing the Add/Analysis page -- mirrors
AddTorrentTab's exact behavior (see the Phase 1+ research: duplicate
detection via libtorrent's own duplicate_is_error exception, disk-space
check before a file-based add, the magnet-needs-two-clicks-of-Demarrer
quirk) rather than reinventing any of it.

AddTorrentTab's own routing-rule auto-prefill of dest_input from the
torrent's name/tracker is still NOT ported (it fires on every analysis,
unconditionally). What IS exposed here is narrower: listCategories/
resolveDestination/defaultSharePolicyNote back the intent-guided preset
selector in add.js, which only ever prefills the category/destination
fields (still freely editable) when the user explicitly picks a preset --
each one reuses an existing engine mechanism (torrent_categories.py's
free-text category, routing_rules.py's resolve_destination(), and the
Settings fields ShareLimitService already reads for its default policy)
rather than adding a new one.
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.config.settings import Settings
from torrent2000.danger_scanner import FileRisk, ScanResult, scan_files
from torrent2000.engine.disk_space_monitor import free_space_mb
from torrent2000.engine.routing_rules import RoutingRuleStore, resolve_destination
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_files import files_from_torrent_path
from torrent2000.ui.web.dropped_file import save_dropped_bytes_to_temp_file


def _file_risk_to_dict(risk: FileRisk) -> dict:
    return {
        "index": risk.file.index,
        "path": risk.file.path,
        "size": risk.file.size,
        "score": risk.score,
        "level": risk.level.name,
        "reasons": risk.reasons,
    }


def _scan_result_to_dict(result: ScanResult, threshold: int) -> dict:
    ordered = sorted(result.file_risks, key=lambda r: -r.score)
    return {
        "fileRisks": [_file_risk_to_dict(r) for r in ordered],
        "overallScore": result.overall_score,
        "flaggedIndices": result.flagged_indices,
        "threshold": threshold,
    }


class AddBridge(QObject):
    scanReady = Signal("QVariantMap")
    statusChanged = Signal(str)
    started = Signal()
    blockedByTheme = Signal()

    def __init__(
        self,
        session_manager: SessionManager,
        settings: Settings,
        routing_rule_store: RoutingRuleStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._routing_rule_store = routing_rule_store
        self._torrent_path: str | None = None
        self._torrent_files: list | None = None
        self._pending_magnet_hash: str | None = None
        self._threshold = settings.danger_auto_exclude_threshold
        session_manager.metadata_received.connect(self._on_metadata_received)
        session_manager.download_blocked_by_theme.connect(lambda _ih: self.blockedByTheme.emit())

    @Slot(result=str)
    def defaultDestination(self) -> str:
        return self._settings.default_download_dir

    @Slot(result=int)
    def defaultThreshold(self) -> int:
        return self._threshold

    @Slot(int)
    def setThreshold(self, value: int) -> None:
        self._threshold = value

    @Slot(result="QVariantList")
    def listCategories(self) -> list:
        """Same distinct-categories-in-use list DownloadsBridge.listCategories
        exposes -- reused here so the intent preset can prefer a category the
        user already uses over inventing a new near-duplicate name."""
        return self._session_manager.list_categories()

    @Slot(str, result=str)
    def resolveDestination(self, category: str) -> str:
        """Reuses routing_rules.resolve_destination() unchanged, with the
        preset's guessed category standing in for the torrent name -- the
        only signal available before a file/magnet has necessarily been
        analyzed yet. Returns the configured default destination unchanged
        (same as any other resolve_destination() caller) when no rule's
        pattern matches."""
        return resolve_destination(
            self._routing_rule_store.list_rules(), self._settings.default_download_dir, name=category
        )

    @Slot(result=str)
    def defaultSharePolicyNote(self) -> str:
        """Informational only: share_limits.py has no per-add-time or
        per-category default, tracking always starts once a torrent reaches
        SEEDING (see ShareLimitService.apply_default_policy_if_enabled).
        Surfaces the already-configured default in the same units it's
        stored in, so the preset can tell the user what will happen
        automatically without adding a field tied to no real mechanism."""
        if not self._settings.default_share_policy_enabled:
            return ""
        parts = []
        if self._settings.default_share_time_limit_hours:
            parts.append(f"{self._settings.default_share_time_limit_hours} h")
        if self._settings.default_share_data_limit_mb:
            parts.append(f"{self._settings.default_share_data_limit_mb} Mo")
        if self._settings.default_share_ratio_limit:
            parts.append(f"ratio {self._settings.default_share_ratio_limit:g}")
        if not parts:
            return ""
        return (
            "Politique de partage par défaut active (" + " / ".join(parts) + ") — "
            "appliquée automatiquement une fois le partage commencé."
        )

    @Slot(str)
    def selectTorrentFile(self, path: str) -> None:
        self._torrent_path = path
        # Invalidated up front (not just repopulated on success) so a stale
        # cache from a PREVIOUS successful selection is never reused if THIS
        # file fails to parse -- keeps the cache valid only for the current
        # self._torrent_path.
        self._torrent_files = None
        self._pending_magnet_hash = None
        try:
            files = files_from_torrent_path(path)
        except Exception as exc:
            self.statusChanged.emit(f"Erreur de lecture du fichier torrent : {exc}")
            return
        self._torrent_files = files
        result = scan_files(files)
        self.scanReady.emit(_scan_result_to_dict(result, self._threshold))
        self.statusChanged.emit(f"{len(files)} fichier(s) analysé(s).")

    @Slot(str, str, result=str)
    def saveDroppedTorrent(self, filename: str, base64_data: str) -> str:
        """Chromium's File API never exposes an OS filesystem path (that's an
        Electron-only extension, not present in stock QtWebEngine) -- so a
        dropped file's bytes are read client-side via FileReader and handed
        here as base64, written to a temp file, and fed into
        selectTorrentFile() unchanged so drop and browse share one code
        path, same as the native DropZoneWidget/browse_button convergence."""
        return save_dropped_bytes_to_temp_file(filename, base64_data)

    @Slot(str)
    def analyzeMagnet(self, uri: str) -> None:
        uri = uri.strip()
        if not uri:
            return
        self._torrent_path = None
        try:
            info_hash = self._session_manager.add_torrent_from_magnet(uri, self._settings.default_download_dir)
        except Exception as exc:
            self.statusChanged.emit(f"Erreur : {exc}")
            return
        self._pending_magnet_hash = info_hash
        self.statusChanged.emit("En attente des métadonnées…")

    def _on_metadata_received(self, info_hash: str) -> None:
        if info_hash != self._pending_magnet_hash:
            return
        files = self._session_manager.get_torrent_files(info_hash)
        result = scan_files(files)
        self.scanReady.emit(_scan_result_to_dict(result, self._threshold))
        self.statusChanged.emit(f"{len(files)} fichier(s) analysé(s).")

    @Slot(str, str, str, "QVariantList", result="QVariantMap")
    def startTorrent(self, dest_path: str, magnet_uri: str, category: str, excluded_indices) -> dict:
        excluded = {int(i) for i in excluded_indices}
        dest_path = (dest_path or "").strip() or self._settings.default_download_dir
        category = (category or "").strip()

        if self._pending_magnet_hash and not self._torrent_path:
            if excluded:
                self._session_manager.exclude_files(self._pending_magnet_hash, excluded)
            if category:
                self._session_manager.set_torrent_category(self._pending_magnet_hash, category)
            self._session_manager.start_after_analysis(self._pending_magnet_hash)
            self._reset()
            self.started.emit()
            return {"ok": True}

        if self._torrent_path:
            if self._torrent_files is not None:
                files = self._torrent_files
            else:
                try:
                    files = files_from_torrent_path(self._torrent_path)
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}
            total_size = sum(f.size for f in files if f.index not in excluded)
            free_mb = free_space_mb(dest_path)
            if free_mb is not None and free_mb < total_size / (1024 * 1024):
                return {"ok": False, "error": "Espace disque insuffisant sur le volume de destination."}
            try:
                info_hash = self._session_manager.add_torrent_from_file(self._torrent_path, dest_path, excluded)
            except Exception as exc:
                # Surfaces the real cause (e.g. a corrupted/malformed .torrent)
                # instead of always claiming "already present", which used to
                # mask genuine failures behind a misleading fixed message.
                return {"ok": False, "error": str(exc) or "Ce torrent est déjà présent."}
            if category:
                self._session_manager.set_torrent_category(info_hash, category)
            self._reset()
            self.started.emit()
            return {"ok": True}

        magnet_uri = (magnet_uri or "").strip()
        if magnet_uri:
            self.analyzeMagnet(magnet_uri)
            return {"ok": False, "pending": True, "error": "Analyse en cours — cliquez de nouveau sur Démarrer une fois prêt."}

        return {"ok": False, "error": "Sélectionnez un fichier .torrent ou saisissez un lien magnet."}

    def _reset(self) -> None:
        self._torrent_path = None
        self._torrent_files = None
        self._pending_magnet_hash = None
