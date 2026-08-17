import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.ui.widgets.drop_zone import DropZoneWidget


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def drop_zone():
    widget = DropZoneWidget()
    yield widget
    widget.deleteLater()


class _FakeUrl:
    def __init__(self, local_file: str) -> None:
        self._local_file = local_file

    def toLocalFile(self) -> str:
        return self._local_file


class _FakeMimeData:
    def __init__(self, urls) -> None:
        self._urls = urls

    def hasUrls(self) -> bool:
        return bool(self._urls)

    def urls(self):
        return self._urls


class _FakeDragDropEvent:
    """Stand-in for QDragEnterEvent/QDropEvent exposing only the surface
    dragEnterEvent()/dropEvent() actually touch (mimeData(),
    acceptProposedAction(), ignore()). Constructing the real Qt event
    classes directly (no live drag session, no QApplication event loop
    delivering them) segfaults this PySide6 build, so a real event is not
    an option here -- this fake is what makes the widget's logic testable
    at all under offscreen QPA."""

    def __init__(self, local_files) -> None:
        self._mime = _FakeMimeData([_FakeUrl(f) for f in local_files])
        self.accepted = False
        self.ignored = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


# -- dragEnterEvent -----------------------------------------------------------


def test_drag_enter_accepts_a_dot_torrent_file(drop_zone):
    event = _FakeDragDropEvent(["C:/downloads/example.torrent"])
    drop_zone.dragEnterEvent(event)
    assert event.accepted
    assert not event.ignored


def test_drag_enter_accepts_case_insensitively(drop_zone):
    event = _FakeDragDropEvent(["C:/downloads/EXAMPLE.TORRENT"])
    drop_zone.dragEnterEvent(event)
    assert event.accepted


def test_drag_enter_ignores_non_torrent_file(drop_zone):
    event = _FakeDragDropEvent(["C:/downloads/readme.txt"])
    drop_zone.dragEnterEvent(event)
    assert event.ignored
    assert not event.accepted


def test_drag_enter_ignores_when_no_urls(drop_zone):
    event = _FakeDragDropEvent([])
    drop_zone.dragEnterEvent(event)
    assert event.ignored
    assert not event.accepted


def test_drag_enter_accepts_when_a_torrent_file_is_among_other_urls(drop_zone):
    event = _FakeDragDropEvent(["C:/downloads/readme.txt", "C:/downloads/example.torrent"])
    drop_zone.dragEnterEvent(event)
    assert event.accepted


# -- dropEvent ------------------------------------------------------------------


def test_drop_emits_signal_with_the_torrent_path(drop_zone):
    received = []
    drop_zone.torrent_file_dropped.connect(received.append)

    event = _FakeDragDropEvent(["C:/downloads/example.torrent"])
    drop_zone.dropEvent(event)

    assert received == [os.path.normpath("C:/downloads/example.torrent")]
    assert event.accepted


def test_drop_normalizes_forward_slashes_to_native_separators(drop_zone):
    """QUrl.toLocalFile() returns forward slashes on Windows; the emitted
    path must use native backslashes so a dropped file's path matches what
    Browse... (QFileDialog) would have produced."""
    received = []
    drop_zone.torrent_file_dropped.connect(received.append)

    event = _FakeDragDropEvent(["C:/downloads/example.torrent"])
    drop_zone.dropEvent(event)

    assert received == ["C:\\downloads\\example.torrent"]
    assert "/" not in received[0]


def test_drop_ignores_and_does_not_emit_for_non_torrent_file(drop_zone):
    received = []
    drop_zone.torrent_file_dropped.connect(received.append)

    event = _FakeDragDropEvent(["C:/downloads/readme.txt"])
    drop_zone.dropEvent(event)

    assert received == []
    assert event.ignored
    assert not event.accepted


def test_drop_stops_at_the_first_torrent_file(drop_zone):
    received = []
    drop_zone.torrent_file_dropped.connect(received.append)

    event = _FakeDragDropEvent(["C:/downloads/a.torrent", "C:/downloads/b.torrent"])
    drop_zone.dropEvent(event)

    assert received == [os.path.normpath("C:/downloads/a.torrent")]
