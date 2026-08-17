"""Integration coverage for AddTorrentTab's routing-rule pre-fill (see
engine/routing_rules.py and add_tab.py's _maybe_apply_routing_rule_for_file/
_maybe_apply_routing_rule_for_magnet): selecting a .torrent file or typing/
receiving a magnet URI should pre-fill dest_input from the first matching
rule, and must never touch the field (or crash) when nothing matches or the
file can't be parsed yet.
"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.ui.tabs.add_tab import AddTorrentTab

TORRENT_PATH = r"C:\path\to\file.torrent"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class _FakeAnnounceEntry:
    """Stands in for libtorrent's announce_entry -- real one exposes the
    tracker URL via a plain .url attribute (verified with
    lt.announce_entry(...).url on the installed 2.0.13.0 build), not a dict
    key like torrent_handle.trackers() uses."""

    def __init__(self, url: str) -> None:
        self.url = url


class _FakeTorrentInfo:
    def __init__(self, name: str, trackers: list[str]) -> None:
        self._name = name
        self._trackers = [_FakeAnnounceEntry(u) for u in trackers]

    def name(self) -> str:
        return self._name

    def trackers(self):
        return self._trackers


# ------------------------------------------------------------- file source


def test_selecting_a_file_prefills_dest_input_when_a_name_rule_matches():
    RoutingRuleStore().save_rule(RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux"))
    tab = AddTorrentTab(MagicMock(), Settings())

    with (
        patch("torrent2000.ui.tabs.add_tab.lt.torrent_info", return_value=_FakeTorrentInfo("Ubuntu.24.04", [])),
        patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[]),
    ):
        tab.open_torrent_file(TORRENT_PATH)

    assert tab.dest_input.text() == "D:/linux"


def test_selecting_a_file_prefills_dest_input_when_a_tracker_rule_matches():
    RoutingRuleStore().save_rule(
        RoutingRule(name="private", pattern="example.com", match_field="tracker", destination="D:/private")
    )
    tab = AddTorrentTab(MagicMock(), Settings())

    with (
        patch(
            "torrent2000.ui.tabs.add_tab.lt.torrent_info",
            return_value=_FakeTorrentInfo("Anything", ["http://tracker.example.com/announce"]),
        ),
        patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[]),
    ):
        tab.open_torrent_file(TORRENT_PATH)

    assert tab.dest_input.text() == "D:/private"


def test_selecting_a_file_with_no_matching_rule_leaves_dest_input_untouched():
    RoutingRuleStore().save_rule(RoutingRule(name="linux", pattern="fedora", match_field="name", destination="D:/fedora"))
    settings = Settings()
    tab = AddTorrentTab(MagicMock(), settings)
    original = tab.dest_input.text()

    with (
        patch("torrent2000.ui.tabs.add_tab.lt.torrent_info", return_value=_FakeTorrentInfo("Ubuntu.24.04", [])),
        patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[]),
    ):
        tab.open_torrent_file(TORRENT_PATH)

    assert tab.dest_input.text() == original == settings.default_download_dir


def test_a_file_that_cannot_be_parsed_leaves_dest_input_untouched():
    """No lt.torrent_info mock here -- TORRENT_PATH doesn't exist on disk,
    so the real libtorrent call raises (verified separately: RuntimeError,
    "No such file or directory"). Must not crash and must not touch the
    field, exactly like "no rule matched"."""
    RoutingRuleStore().save_rule(RoutingRule(name="linux", pattern="path", match_field="name", destination="D:/linux"))
    settings = Settings()
    tab = AddTorrentTab(MagicMock(), settings)
    original = tab.dest_input.text()

    with patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[]):
        tab.open_torrent_file(TORRENT_PATH)

    assert tab.dest_input.text() == original


# ----------------------------------------------------------- magnet source


def test_magnet_dn_parameter_prefills_dest_input_when_a_name_rule_matches():
    RoutingRuleStore().save_rule(RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux"))
    tab = AddTorrentTab(MagicMock(), Settings())

    tab.open_magnet("magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01&dn=Ubuntu.24.04")

    assert tab.dest_input.text() == "D:/linux"


def test_magnet_without_dn_leaves_dest_input_untouched():
    RoutingRuleStore().save_rule(RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux"))
    settings = Settings()
    tab = AddTorrentTab(MagicMock(), settings)
    original = tab.dest_input.text()

    tab.open_magnet("magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01")

    assert tab.dest_input.text() == original


def test_magnet_dn_with_no_matching_rule_leaves_dest_input_untouched():
    RoutingRuleStore().save_rule(RoutingRule(name="linux", pattern="fedora", match_field="name", destination="D:/fedora"))
    settings = Settings()
    tab = AddTorrentTab(MagicMock(), settings)
    original = tab.dest_input.text()

    tab.open_magnet("magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01&dn=Ubuntu.24.04")

    assert tab.dest_input.text() == original
