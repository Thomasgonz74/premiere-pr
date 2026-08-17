import hashlib
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.update_checker import UpdateChecker, _find_installer_asset


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _fake_response(body: bytes):
    context = MagicMock()
    context.read.return_value = body
    context.__enter__.return_value = context
    context.__exit__.return_value = False
    return context


def _run_and_wait(app, timeout_s=1.0, until=None):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.01)


def _checker_with_assets(assets):
    settings = Settings()
    checker = UpdateChecker(settings)
    checker._latest_assets = assets
    return checker


# ------------------------------------------------------------ _find_installer_asset


def test_find_installer_asset_prefers_setup_named_exe():
    assets = [
        {"name": "Torrent2000.exe", "browser_download_url": "https://x/Torrent2000.exe", "digest": "sha256:aaa"},
        {"name": "Torrent2000-Setup.exe", "browser_download_url": "https://x/Setup.exe", "digest": "sha256:bbb"},
    ]
    assert _find_installer_asset(assets)["name"] == "Torrent2000-Setup.exe"


def test_find_installer_asset_falls_back_to_any_exe():
    assets = [{"name": "checksums.txt", "browser_download_url": "https://x/checksums.txt", "digest": ""},
              {"name": "Torrent2000.exe", "browser_download_url": "https://x/Torrent2000.exe", "digest": "sha256:aaa"}]
    assert _find_installer_asset(assets)["name"] == "Torrent2000.exe"


def test_find_installer_asset_returns_none_when_nothing_matches():
    assets = [{"name": "release-notes.txt", "browser_download_url": "https://x/notes.txt", "digest": ""}]
    assert _find_installer_asset(assets) is None


# ------------------------------------------------------- download_verified_installer


def test_matching_digest_writes_verified_file_and_emits_local_path(qapp):
    payload = b"fake installer bytes"
    digest = hashlib.sha256(payload).hexdigest()
    checker = _checker_with_assets(
        [{"name": "Torrent2000-Setup.exe", "browser_download_url": "https://x/Setup.exe", "digest": f"sha256:{digest}"}]
    )
    verified = []
    failed = []
    checker.installer_verified.connect(verified.append)
    checker.installer_verification_failed.connect(failed.append)

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response(payload),
    ):
        checker.download_verified_installer()
        _run_and_wait(qapp, until=lambda: verified or failed)

    assert failed == []
    assert len(verified) == 1
    local_path = verified[0]
    assert os.path.exists(local_path)
    with open(local_path, "rb") as f:
        assert f.read() == payload


def test_mismatched_digest_emits_verification_failed_and_keeps_no_file(qapp):
    payload = b"fake installer bytes"
    wrong_digest = hashlib.sha256(b"different bytes").hexdigest()
    checker = _checker_with_assets(
        [{"name": "Torrent2000-Setup.exe", "browser_download_url": "https://x/Setup.exe", "digest": f"sha256:{wrong_digest}"}]
    )
    verified = []
    failed = []
    checker.installer_verified.connect(verified.append)
    checker.installer_verification_failed.connect(failed.append)

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response(payload),
    ):
        checker.download_verified_installer()
        _run_and_wait(qapp, until=lambda: verified or failed)

    assert verified == []
    assert len(failed) == 1


def test_missing_digest_emits_verification_failed_without_downloading(qapp):
    checker = _checker_with_assets(
        [{"name": "Torrent2000-Setup.exe", "browser_download_url": "https://x/Setup.exe", "digest": ""}]
    )
    verified = []
    failed = []
    checker.installer_verified.connect(verified.append)
    checker.installer_verification_failed.connect(failed.append)

    with patch("torrent2000.engine.url_fetch.urllib.request.urlopen") as mock_urlopen:
        checker.download_verified_installer()
        _run_and_wait(qapp, until=lambda: verified or failed)
        mock_urlopen.assert_not_called()

    assert verified == []
    assert len(failed) == 1


def test_download_verified_installer_passes_settings_proxy_to_fetch_url(qapp):
    payload = b"fake installer bytes"
    digest = hashlib.sha256(payload).hexdigest()
    settings = Settings()
    settings.proxy.enabled = True
    settings.proxy.proxy_type = "http_pw"
    settings.proxy.host = "proxy.example.com"
    settings.proxy.port = 3128
    settings.proxy.username = "alice"
    settings.proxy.password = "s3cret"
    checker = UpdateChecker(settings)
    checker._latest_assets = [
        {"name": "Torrent2000-Setup.exe", "browser_download_url": "https://x/Setup.exe", "digest": f"sha256:{digest}"}
    ]
    verified = []
    checker.installer_verified.connect(verified.append)

    captured_proxies = []

    def fake_fetch_url(url, user_agent, timeout_seconds, extra_headers=None, proxy=None):
        captured_proxies.append(proxy)
        return payload

    with patch("torrent2000.engine.update_checker.fetch_url", fake_fetch_url):
        checker.download_verified_installer()
        _run_and_wait(qapp, until=lambda: verified)

    assert captured_proxies == [settings.proxy]
    assert len(verified) == 1


def test_download_verified_installer_cleans_up_stale_installers(qapp):
    """Orphans left by a previous run (rejected/dismissed download, or a copy
    that was still locked by a just-launched installer) must not accumulate
    forever -- each new verified download sweeps them first."""
    stale = Path(tempfile.gettempdir()) / "torrent2000_update_deadbeef_OldSetup.exe"
    stale.write_bytes(b"leftover from a previous run")
    try:
        payload = b"fake installer bytes"
        digest = hashlib.sha256(payload).hexdigest()
        checker = _checker_with_assets(
            [{"name": "Torrent2000-Setup.exe", "browser_download_url": "https://x/Setup.exe", "digest": f"sha256:{digest}"}]
        )
        verified = []
        checker.installer_verified.connect(verified.append)

        with patch(
            "torrent2000.engine.url_fetch.urllib.request.urlopen",
            return_value=_fake_response(payload),
        ):
            checker.download_verified_installer()
            _run_and_wait(qapp, until=lambda: verified)

        assert len(verified) == 1
        assert not stale.exists()
        assert os.path.exists(verified[0])
        os.remove(verified[0])
    finally:
        stale.unlink(missing_ok=True)


def test_no_installer_asset_emits_verification_failed(qapp):
    checker = _checker_with_assets([{"name": "release-notes.txt", "browser_download_url": "https://x/notes.txt", "digest": ""}])
    failed = []
    checker.installer_verification_failed.connect(failed.append)

    checker.download_verified_installer()
    _run_and_wait(qapp, timeout_s=0.3)

    assert len(failed) == 1


# ------------------------------------------------------------- MainWindow wiring


def test_subprocess_popen_never_called_without_explicit_yes_click(qapp):
    from torrent2000.ui.main_window import MainWindow
    from PySide6.QtWidgets import QMessageBox

    settings = Settings()
    settings.save = MagicMock()
    update_checker = UpdateChecker(settings)
    win = MainWindow(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        settings, MagicMock(), MagicMock(), MagicMock(), update_checker,
    )

    try:
        with patch("torrent2000.ui.main_window.subprocess.Popen") as mock_popen:
            with patch.multiple(
                QMessageBox,
                exec=MagicMock(return_value=0),
                clickedButton=lambda self: self.buttons()[1],  # "later"/"no", not the launch button
            ):
                win._on_installer_verified(r"C:\fake\Torrent2000-Setup.exe")
            mock_popen.assert_not_called()

            with patch.multiple(
                QMessageBox,
                exec=MagicMock(return_value=0),
                clickedButton=lambda self: self.buttons()[0],  # explicit "launch" click
            ):
                win._on_installer_verified(r"C:\fake\Torrent2000-Setup.exe")
            mock_popen.assert_called_once_with([r"C:\fake\Torrent2000-Setup.exe"])
    finally:
        win.close()


def test_on_installer_verified_deletes_temp_file_when_not_launched(qapp):
    """Regression test: picking "later" (or dismissing the dialog) must not
    orphan the SHA-256-verified installer copy in %TEMP% forever."""
    from torrent2000.ui.main_window import MainWindow
    from PySide6.QtWidgets import QMessageBox

    settings = Settings()
    settings.save = MagicMock()
    update_checker = UpdateChecker(settings)
    win = MainWindow(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        settings, MagicMock(), MagicMock(), MagicMock(), update_checker,
    )

    real_temp_path = Path(tempfile.gettempdir()) / "torrent2000_update_testfile_Setup.exe"
    real_temp_path.write_bytes(b"verified installer bytes")

    try:
        with patch("torrent2000.ui.main_window.subprocess.Popen") as mock_popen:
            with patch.multiple(
                QMessageBox,
                exec=MagicMock(return_value=0),
                clickedButton=lambda self: self.buttons()[1],  # "later"/"no", not the launch button
            ):
                win._on_installer_verified(str(real_temp_path))
            mock_popen.assert_not_called()
        assert not real_temp_path.exists()
    finally:
        real_temp_path.unlink(missing_ok=True)
        win.close()
