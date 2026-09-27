"""Applies a routing rule's optional post-completion action (catalogue idea
"action de fin de telechargement personnalisable") once a torrent finishes:
move the finished files elsewhere, or unzip any .zip files found among them.

Deliberately NOT arbitrary command execution -- see
routing_rules.RoutingRule.post_complete_action's own docstring for why only
a closed set of safe, local file operations is supported.

Event-driven (SessionManager.torrent_finished), same pattern as
AntivirusScanService -- no QTimer of its own. Only ever looks at
TorrentRecord.matched_rule_name, set by the fully-automatic add paths
(watch folder, RSS) -- a manually-added torrent never has one, so this
service is simply a no-op for it.
"""

import logging
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject

from torrent2000.engine.routing_rules import RoutingRuleStore
from torrent2000.engine.session_manager import SessionManager

logger = logging.getLogger(__name__)


class PostCompleteActionService(QObject):
    def __init__(
        self, session_manager: SessionManager, routing_rule_store: RoutingRuleStore, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._routing_rule_store = routing_rule_store
        session_manager.torrent_finished.connect(self._on_torrent_finished)

    def _on_torrent_finished(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        if record is None or not record.matched_rule_name:
            return
        rule = next(
            (r for r in self._routing_rule_store.list_rules() if r.name == record.matched_rule_name), None
        )
        if rule is None or rule.post_complete_action == "none":
            return
        if rule.post_complete_action == "move" and rule.post_complete_move_to:
            self._session_manager.move_storage(info_hash, rule.post_complete_move_to)
        elif rule.post_complete_action == "unzip":
            self._unzip_files(record.save_path, info_hash)

    def _unzip_files(self, save_path: str, info_hash: str) -> None:
        for entry in self._session_manager.get_torrent_files(info_hash):
            if not entry.path.lower().endswith(".zip"):
                continue
            zip_path = Path(save_path) / entry.path
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(zip_path.parent)
            except (OSError, zipfile.BadZipFile):
                logger.exception("Post-complete unzip failed for %s (info_hash=%s)", zip_path, info_hash)
