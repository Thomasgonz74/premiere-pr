"""Targeted tests for PeerListTable.refresh() -- populates columns from a
hand-built list of PeerInfo, and shows a dedicated message instead of a
silently empty table when there are no peers."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.engine.torrent_item import PeerInfo
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.peer_list_table import PeerListTable


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def table():
    widget = PeerListTable()
    yield widget
    widget.deleteLater()


def test_refresh_populates_a_row_per_peer(table):
    peers = [
        PeerInfo(ip="203.0.113.5:51413", client="qBittorrent/4.6", progress=0.75, down_speed=51200, up_speed=1024),
        PeerInfo(ip="198.51.100.9:6881", client="libtorrent/2.0", progress=1.0, down_speed=0, up_speed=204800),
    ]

    table.refresh(peers)

    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "203.0.113.5:51413"
    assert table.item(0, 1).text() == "qBittorrent/4.6"
    assert table.item(0, 2).text() == "75.0%"
    assert table.item(0, 3).text() == "50.00 Ko/s"
    assert table.item(0, 4).text() == "1.00 Ko/s"
    assert table.item(1, 0).text() == "198.51.100.9:6881"
    assert table.item(1, 2).text() == "100.0%"
    assert table.item(1, 3).text() == "0 o/s"


def test_refresh_replaces_rows_entirely_on_each_call(table):
    table.refresh([PeerInfo(ip="1.2.3.4:1000", client="A", progress=0.1, down_speed=1, up_speed=1)])
    assert table.rowCount() == 1

    table.refresh(
        [
            PeerInfo(ip="1.2.3.4:1000", client="A", progress=0.1, down_speed=1, up_speed=1),
            PeerInfo(ip="5.6.7.8:2000", client="B", progress=0.2, down_speed=2, up_speed=2),
        ]
    )
    assert table.rowCount() == 2
    assert table.item(1, 0).text() == "5.6.7.8:2000"


def test_refresh_with_no_peers_shows_dedicated_message_instead_of_empty_table(table):
    table.refresh([])

    assert table.rowCount() == 1
    message_item = table.item(0, 0)
    assert message_item.text() == tr("peer_list.no_peers")


def test_refresh_clears_the_message_row_once_peers_reappear(table):
    table.refresh([])
    assert table.rowCount() == 1

    table.refresh([PeerInfo(ip="1.2.3.4:1000", client="A", progress=0.5, down_speed=10, up_speed=10)])

    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "1.2.3.4:1000"
