import os
import subprocess
import sys
import time
from pathlib import Path
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


def test_second_launch_imports_only_what_the_guard_needs():
    # Fresh interpreter: this one has already imported the whole app.
    code = (
        "import sys, run_web_spike\n"
        "class _Secondary:\n"
        "    def try_become_primary(self, _argument): return False\n"
        "run_web_spike.SingleInstanceGuard = _Secondary\n"
        "assert run_web_spike.main() == 0\n"
        "heavy = ('libtorrent', 'PySide6.QtWebEngineWidgets', 'torrent2000.engine.session_manager')\n"
        "print('LOADED', [m for m in heavy if m in sys.modules])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "LOADED []" in result.stdout, result.stdout


def test_argument_sent_while_the_primary_is_still_starting_is_not_lost(qapp, make_guard, monkeypatch):
    """A second launch while the primary is listening but still starting up
    (imports, session restore, window: its event loop not running yet) must
    wait for its argument to be read instead of exiting with it unsent."""
    from torrent2000.engine import single_instance

    name = "Torrent2000SingleInstance_test_startup"
    monkeypatch.setattr(single_instance, "_SERVER_NAME", name)
    primary = make_guard()
    assert primary.try_become_primary("") is True
    received = []
    primary.argument_received.connect(received.append)

    src = str(Path(__file__).resolve().parents[1] / "src")
    code = (
        "import os, sys\n"
        "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
        f"sys.path.insert(0, {src!r})\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "from torrent2000.engine import single_instance\n"
        f"single_instance._SERVER_NAME = {name!r}\n"
        "app = QCoreApplication([])\n"
        "became_primary = single_instance.SingleInstanceGuard().try_become_primary('C:/downloads/late.torrent')\n"
        "sys.exit(1 if became_primary else 0)\n"
    )
    second = subprocess.Popen([sys.executable, "-c", code])
    time.sleep(2.5)  # the primary is busy starting up: no events processed yet

    assert _pump_until(qapp, lambda: received, timeout_s=15)
    assert second.wait(15) == 0
    assert received == ["C:/downloads/late.torrent"]
