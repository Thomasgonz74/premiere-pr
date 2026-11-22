"""Regression test for the app-data-directory ACL lockdown: applied once,
only when the directory is actually created for the first time (see
config/paths.py::get_app_data_dir/_lock_down_acl)."""

from torrent2000.config import paths


def test_lockdown_runs_once_for_a_freshly_created_directory(tmp_path, monkeypatch):
    fresh_dir = tmp_path / "not-created-yet"  # tmp_path itself already exists; this child does not
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(fresh_dir))
    calls = []
    monkeypatch.setattr(paths, "_lock_down_acl", lambda path: calls.append(path))

    result = paths.get_app_data_dir()

    assert result == fresh_dir
    assert fresh_dir.is_dir()
    assert calls == [fresh_dir]


def test_lockdown_does_not_run_again_for_an_already_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))  # pytest's tmp_path already exists
    calls = []
    monkeypatch.setattr(paths, "_lock_down_acl", lambda path: calls.append(path))

    paths.get_app_data_dir()

    assert calls == []


def test_lock_down_acl_never_raises_on_a_real_directory(tmp_path):
    # Exercises the real icacls subprocess call at least once, to catch a
    # genuinely broken command line -- best-effort by design, so a failure
    # (e.g. icacls unavailable) must still not raise.
    paths._lock_down_acl(tmp_path)


def test_lock_down_acl_opens_no_console_window(tmp_path, monkeypatch):
    # The packaged app is windowed: a console child spawned without
    # CREATE_NO_WINDOW flashes a terminal on the first launch.
    monkeypatch.setenv("USERNAME", "someone")
    calls = []
    monkeypatch.setattr(paths.subprocess, "run", lambda *a, **kw: calls.append(kw))

    paths._lock_down_acl(tmp_path)

    assert calls[0]["creationflags"] == paths.subprocess.CREATE_NO_WINDOW
