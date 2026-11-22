"""QWebChannel bridge backing the Add/Analysis page -- mirrors
AddTorrentTab's exact behavior (see the Phase 1+ research: duplicate
detection via libtorrent's own duplicate_is_error exception, disk-space
check before a file-based add, the magnet-needs-two-clicks-of-Demarrer
quirk) rather than reinventing any of it.

AddTorrentTab's own routing-rule auto-prefill of dest_input from the
torrent's name now IS ported (see selectTorrentFile/_on_metadata_received's
`suggestedDestination` on the scan payload) -- previously only the RSS
auto-download path (rss_feed_service.py) applied resolve_destination() by
default, an inconsistency with no real reason behind it. Unlike the RSS
path, add.js only ever uses the suggestion to prefill an empty/still-default
destination field (see addRenderScan), never overwriting something the user
already typed -- the explicit intent-preset selector below remains available
and takes priority if picked afterward.

listCategories/resolveDestination/defaultSharePolicyNote back the
intent-guided preset selector in add.js, which only ever prefills the
category/destination fields (still freely editable) when the user explicitly
picks a preset -- each one reuses an existing engine mechanism
(torrent_categories.py's free-text category, routing_rules.py's
resolve_destination(), and the Settings fields ShareLimitService already
reads for its default policy) rather than adding a new one.
"""

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.config.settings import Settings
from torrent2000.danger_scanner import FileRisk, ScanResult, scan_files
from torrent2000.engine.disk_space_monitor import free_space_mb
from torrent2000.engine.routing_rules import RoutingRuleStore, resolve_destination
from torrent2000.engine.session_manager import SessionManager, TorrentAlreadyPresentError, is_safe_move_destination
from torrent2000.engine.torrent_files import files_from_torrent_path
from torrent2000.i18n.translator import tr
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
        # temp path -> name the user dropped (or the search result's title),
        # so routing rules match that name and not "dropped_xxxx" (see
        # saveDroppedTorrent, nameTorrentFile).
        self._dropped_names: dict[str, str] = {}
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
            parts.append(tr("web.add.share_policy_hours", hours=self._settings.default_share_time_limit_hours))
        if self._settings.default_share_data_limit_mb:
            parts.append(f"{self._settings.default_share_data_limit_mb} {tr('web.units.megabyte')}")
        if self._settings.default_share_ratio_limit:
            parts.append(f"{tr('web.share_page.ratio_limit_label')} {self._settings.default_share_ratio_limit:g}")
        if not parts:
            return ""
        return tr("web.add.share_policy_note", limits=" / ".join(parts))

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
            self.statusChanged.emit(tr("add_tab.analysis_failed_message", error=exc))
            return
        self._torrent_files = files
        result = scan_files(files)
        payload = _scan_result_to_dict(result, self._threshold)
        payload["suggestedDestination"] = resolve_destination(
            self._routing_rule_store.list_rules(),
            self._settings.default_download_dir,
            name=self._dropped_names.get(path) or Path(path).stem,
        )
        self.scanReady.emit(payload)
        self.statusChanged.emit(tr("add_tab.files_analyzed", count=len(files)))

    @Slot(result="QVariantMap")
    def scanReasons(self) -> dict:
        """The analysed torrent's reasons by file index, in the current
        language: the Add page shows them again after a language switch."""
        if self._pending_magnet_hash:
            files = self._session_manager.get_torrent_files(self._pending_magnet_hash)
        else:
            files = self._torrent_files if self._torrent_path else None
        return {str(risk.file.index): risk.reasons for risk in scan_files(files or []).file_risks}

    @Slot(str, str, result=str)
    def saveDroppedTorrent(self, filename: str, base64_data: str) -> str:
        """Chromium's File API never exposes an OS filesystem path (that's an
        Electron-only extension, not present in stock QtWebEngine) -- so a
        dropped file's bytes are read client-side via FileReader and handed
        here as base64, written to a temp file, and fed into
        selectTorrentFile() unchanged so drop and browse share one code
        path, same as the native DropZoneWidget/browse_button convergence."""
        path = save_dropped_bytes_to_temp_file(filename, base64_data)
        if path:
            self._dropped_names[path] = Path(filename).stem
        return path

    @Slot(str, str)
    def nameTorrentFile(self, path: str, name: str) -> None:
        """A search result's .torrent, fetched to a "search_xxxx" temp file:
        routing rules match the result's title, as a dropped file's name."""
        if name:
            self._dropped_names[path] = name

    @Slot(str)
    def analyzeMagnet(self, uri: str) -> None:
        self._analyze_magnet(uri)

    def _analyze_magnet(self, uri: str) -> str:
        """The error, also shown through statusChanged -- "" once the magnet
        awaits its metadata (or is scanned already)."""
        uri = uri.strip()
        if not uri:
            return ""
        self._torrent_path = None
        # Replaced even if this one fails (already in the list, malformed):
        # Démarrer must never start the previous magnet without its scan.
        self._pending_magnet_hash = None
        try:
            info_hash = self._session_manager.add_torrent_from_magnet(uri, self._settings.default_download_dir)
        except TorrentAlreadyPresentError as exc:
            record = self._session_manager.get_record(exc.info_hash)
            if record is None or not record.awaiting_analysis:
                return self._show_error(tr("add_tab.duplicate_message"))
            # Still awaiting its analysis (e.g. added before a restart): pick it
            # back up -- its metadata may be in already, never to be announced again.
            self._pending_magnet_hash = exc.info_hash
            if self._session_manager.get_torrent_files(exc.info_hash):
                self._on_metadata_received(exc.info_hash)
                return ""
            info_hash = exc.info_hash
        except Exception as exc:
            return self._show_error(tr("web.add.magnet_error", error=exc))
        self._pending_magnet_hash = info_hash
        self.statusChanged.emit(tr("add_tab.awaiting_metadata"))
        return ""

    def _show_error(self, message: str) -> str:
        self.statusChanged.emit(message)
        return message

    def _on_metadata_received(self, info_hash: str) -> None:
        if info_hash != self._pending_magnet_hash:
            return
        files = self._session_manager.get_torrent_files(info_hash)
        result = scan_files(files)
        payload = _scan_result_to_dict(result, self._threshold)
        record = self._session_manager.get_record(info_hash)
        payload["suggestedDestination"] = resolve_destination(
            self._routing_rule_store.list_rules(),
            self._settings.default_download_dir,
            name=record.name if record is not None else "",
        )
        self.scanReady.emit(payload)
        self.statusChanged.emit(tr("add_tab.files_analyzed", count=len(files)))

    @Slot(str, str, str, "QVariantList", result="QVariantMap")
    def startTorrent(self, dest_path: str, magnet_uri: str, category: str, excluded_indices) -> dict:
        excluded = {int(i) for i in excluded_indices}
        dest_path = (dest_path or "").strip() or self._settings.default_download_dir
        category = (category or "").strip()

        if self._pending_magnet_hash and not self._torrent_path:
            # analyzeMagnet added it under the default folder, before any
            # destination (typed, or a routing rule's) could be known. Quiet:
            # placing it is part of the add, not a "move finished" toast.
            record = self._session_manager.get_record(self._pending_magnet_hash)
            if record is not None and Path(dest_path) != Path(record.save_path):
                # Checked before it starts: the move runs in the background,
                # and a refused or failed one (a drive root, a drive not
                # plugged in) would leave it downloading in the default folder.
                if not is_safe_move_destination(dest_path):
                    name = record.name or self._pending_magnet_hash[:12]  # no dn=, no metadata yet
                    return {"ok": False, "error": tr(
                        "notifications.move_storage_refused_message", name=name, path=dest_path
                    )}
                try:
                    Path(dest_path).mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    return {"ok": False, "error": tr("web.add.destination_unusable", error=exc.strerror or exc)}
                self._session_manager.move_storage(self._pending_magnet_hash, dest_path, quiet=True)
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
                return {"ok": False, "error": tr("add_tab.insufficient_space_message")}
            try:
                info_hash = self._session_manager.add_torrent_from_file(self._torrent_path, dest_path, excluded)
            except TorrentAlreadyPresentError:
                return {"ok": False, "error": tr("add_tab.duplicate_message")}
            except Exception as exc:
                # Surfaces the real cause (e.g. a corrupted/malformed .torrent)
                # instead of always claiming "already present", which used to
                # mask genuine failures behind a misleading fixed message.
                return {"ok": False, "error": str(exc)}
            if category:
                self._session_manager.set_torrent_category(info_hash, category)
            self._reset()
            self.started.emit()
            return {"ok": True}

        magnet_uri = (magnet_uri or "").strip()
        if magnet_uri:
            error = self._analyze_magnet(magnet_uri)
            if error:
                return {"ok": False, "error": error}
            return {"ok": False, "pending": True, "error": tr("add_tab.magnet_analysis_required_message")}

        return {"ok": False, "error": tr("add_tab.no_source_message")}

    def _reset(self) -> None:
        self._torrent_path = None
        self._torrent_files = None
        self._pending_magnet_hash = None
