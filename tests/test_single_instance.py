import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from torrent2000.engine.single_instance import _SERVER_NAME, SingleInstanceGuard


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _cleanup_stale_server():
    # Best-effort safety net in case a previous run crashed mid-test and
    # left _SERVER_NAME registered (a no-op on Windows, where the OS already
    # releases named pipes when their owning process exits -- see
    # SingleInstanceGuard._start_listening).
    QLocalServer.removeServer(_SERVER_NAME)
    yield
    QLocalServer.removeServer(_SERVER_NAME)


@pytest.fixture
def make_guard():
    # SingleInstanceGuard keeps itself alive via a reference cycle (its
    # QLocalServer is both a Qt-parented child and a strong Python
    # attribute, and the server's newConnection connection holds a
    # reference back to the guard) -- by design, since production code
    # keeps exactly one guard alive for the whole app lifetime and relies
    # on process exit to tear it down. Within a single test process that
    # cycle means the guard/server only get collected whenever the cyclic
    # GC next happens to run, so relying on that for test isolation would
    # be flaky (the next test's guard could intermittently see the previous
    # one's server still listening). Closing explicitly here makes each
    # test deterministic instead.
    guards = []

    def _make():
        guard = SingleInstanceGuard()
        guards.append(guard)
        return guard

    yield _make

    for guard in guards:
        guard.close()


def _pump_until(app, condition, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_first_guard_becomes_primary(make_guard):
    primary = make_guard()

    assert primary.try_become_primary("") is True
    assert primary._server is not None
    assert primary._server.isListening()


def test_second_guard_detects_primary_and_forwards_argument(qapp, make_guard):
    primary = make_guard()
    assert primary.try_become_primary("") is True

    received = []
    primary.argument_received.connect(received.append)

    secondary = make_guard()
    assert secondary.try_become_primary("C:/downloads/example.torrent") is False

    assert _pump_until(qapp, lambda: received)
    assert received == ["C:/downloads/example.torrent"]


def test_forwards_empty_argument_when_second_launch_has_none(qapp, make_guard):
    primary = make_guard()
    assert primary.try_become_primary("") is True

    received = []
    primary.argument_received.connect(received.append)

    secondary = make_guard()
    assert secondary.try_become_primary("") is False

    assert _pump_until(qapp, lambda: received)
    assert received == [""]


# ---------------------------------------------------------- stale-server recovery
#
# Simulating a genuinely crashed previous instance isn't practical from a
# single test process, so these drive the exact recovery path
# (_start_listening's "listen() fails -> removeServer() -> retry once")
# directly by making the first listen() call fail, rather than trying to
# reproduce stale-socket OS state.


def test_recovers_by_removing_the_stale_server_and_retrying_listen(make_guard):
    guard = make_guard()
    listen_calls = []
    real_listen = QLocalServer.listen

    def fake_listen(self, name):
        listen_calls.append(name)
        if len(listen_calls) == 1:
            return False  # first attempt: as if a stale server is still registered
        return real_listen(self, name)

    with (
        patch.object(QLocalServer, "listen", fake_listen),
        patch.object(QLocalServer, "removeServer", wraps=QLocalServer.removeServer) as mock_remove_server,
    ):
        assert guard.try_become_primary("") is True

    assert listen_calls == [_SERVER_NAME, _SERVER_NAME]
    mock_remove_server.assert_called_once_with(_SERVER_NAME)
    assert guard._server.isListening()


def test_still_returns_true_without_raising_if_listen_fails_even_after_retry(make_guard):
    guard = make_guard()

    with (
        patch.object(QLocalServer, "listen", return_value=False),
        patch.object(QLocalServer, "removeServer", return_value=True),
    ):
        assert guard.try_become_primary("") is True

    assert guard._server is not None
    assert guard._server.isListening() is False
