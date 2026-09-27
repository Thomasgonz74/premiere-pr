"""Quit safety for background work. A pool task can outlive app.exec(): by
the time it reports back, PySide's teardown has deleted its signals object,
and an unguarded emit logs "Uncaught exception: Signal source has been
deleted" at every such quit. And run_web_spike._shutdown -- a closure inside
main(), hence checked on its source -- must run once and stop the
auto-shutdown before anything else can pump events."""

import ast
import os
import threading
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

from torrent2000.engine import ip_blocklist, network_profile_switcher, post_complete_action_service
from torrent2000.ui.web import bridge_create_torrent

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _unzip(tmp_path, monkeypatch):
    monkeypatch.setattr(post_complete_action_service, "_cancel_event", threading.Event())
    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", "a")
    signals = post_complete_action_service._UnzipSignals()
    return post_complete_action_service._UnzipRunnable([zip_path], "hash", signals), signals


def _blocklist(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_blocklist, "_cancel_event", threading.Event())
    path = tmp_path / "blocklist.txt"
    path.write_text("1.2.3.0/24\n", encoding="utf-8")
    signals = ip_blocklist.BlocklistSignals()
    return ip_blocklist.BlocklistLoadRunnable(str(path), signals), signals


def _ssid(tmp_path, monkeypatch):
    monkeypatch.setattr(network_profile_switcher, "get_current_ssid", lambda: "home")
    signals = network_profile_switcher._SsidSignals()
    return network_profile_switcher._SsidRunnable(signals), signals


def _create_torrent(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_create_torrent, "create_torrent_file", lambda *args, **kwargs: None)
    signals = bridge_create_torrent._CreateTorrentSignals()
    runnable = bridge_create_torrent._CreateTorrentRunnable(
        "src", "out.torrent", [], False, "", signals, threading.Event()
    )
    return runnable, signals


@pytest.mark.parametrize("make_runnable", [_unzip, _blocklist, _ssid, _create_torrent])
def test_a_runnable_finishing_after_teardown_does_not_raise(make_runnable, tmp_path, monkeypatch):
    runnable, signals = make_runnable(tmp_path, monkeypatch)
    shiboken6.delete(signals)  # what PySide's teardown does once app.exec() returns

    runnable.run()  # must not raise RuntimeError


def test_quit_handler_runs_once_and_stops_auto_shutdown_first():
    tree = ast.parse((ROOT / "run_web_spike.py").read_text(encoding="utf-8"))
    shutdown = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_shutdown")
    body = [n for n in shutdown.body if not isinstance(n, ast.Nonlocal)]

    # aboutToQuit re-enters through session_manager.shutdown()'s processEvents().
    guard = body[0]
    assert isinstance(guard, ast.If) and isinstance(guard.body[0], ast.Return)
    calls = [ast.unparse(n.value) for n in body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
    assert calls[0] == "auto_shutdown_service.stop()"
    assert "cancel_blocklist_load()" in calls
