"""Coverage for ClipboardWatcherService: emits magnetDetected only when
enabled and only for a genuinely new magnet: clipboard value (see
engine/clipboard_watcher_service.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.clipboard_watcher_service import ClipboardWatcherService


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _service(enabled=True):
    settings = Settings()
    settings.clipboard_magnet_detection_enabled = enabled
    service = ClipboardWatcherService(settings)
    detected = []
    service.magnetDetected.connect(detected.append)
    return service, detected


def test_disabled_by_default(qapp):
    settings = Settings()
    assert settings.clipboard_magnet_detection_enabled is False


def test_magnet_copied_while_enabled_is_detected(qapp):
    service, detected = _service(enabled=True)

    QApplication.clipboard().setText("magnet:?xt=urn:btih:abc")
    qapp.processEvents()

    assert detected == ["magnet:?xt=urn:btih:abc"]


def test_non_magnet_text_is_ignored(qapp):
    service, detected = _service(enabled=True)

    QApplication.clipboard().setText("just some regular text")
    qapp.processEvents()

    assert detected == []


def test_disabled_setting_ignores_even_a_real_magnet(qapp):
    service, detected = _service(enabled=False)

    QApplication.clipboard().setText("magnet:?xt=urn:btih:def")
    qapp.processEvents()

    assert detected == []


def test_the_same_magnet_copied_twice_in_a_row_is_only_detected_once(qapp):
    service, detected = _service(enabled=True)

    QApplication.clipboard().setText("magnet:?xt=urn:btih:repeat")
    qapp.processEvents()
    QApplication.clipboard().setText("magnet:?xt=urn:btih:repeat")
    qapp.processEvents()

    assert detected == ["magnet:?xt=urn:btih:repeat"]
