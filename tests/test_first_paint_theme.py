"""The web UI's very first frame already uses the saved theme and mode (no
Luna XP light flash until app.js's getSettings round-trip)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import shiboken6
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from theme_probe import run_js, wait_until
from torrent2000.config.settings import Settings
from torrent2000.ui.web.spike_window import _index_url

# Injected before any page markup is parsed: records what the first rendered
# frame used. A frame (and its rAF) waits for render-blocking sheets, so an
# unloaded sheet here means the first paint came before the theme.
_FIRST_FRAME_JS = """
requestAnimationFrame(() => {
  const link = document.getElementById("themeTokensLink");
  window.__firstFrame = [link.getAttribute("href"), !!link.sheet, document.documentElement.getAttribute("data-theme")];
});
"""


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


# synthwave has no dark palette: its saved "dark" is shown as light from the
# first frame on, as theme_switcher.js does for every later switch.
@pytest.mark.parametrize("theme, expected_attr", [("win11_mica", "dark"), ("synthwave", None)])
def test_first_frame_uses_the_saved_theme_and_mode(theme, expected_attr):
    # An id missing from the theme list never reaches the page (404 sheet).
    assert _index_url(Settings(theme="not-a-theme", appearance_mode="light")).query() == ""

    view = QWebEngineView()
    script = QWebEngineScript()
    script.setSourceCode(_FIRST_FRAME_JS)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    view.page().scripts().insert(script)
    view.setUrl(_index_url(Settings(theme=theme, appearance_mode="dark")))
    view.show()
    try:
        wait_until(view, "!!window.__firstFrame")
        first_frame = json.loads(run_js(view, "JSON.stringify(window.__firstFrame)"))
        assert first_frame == [f"themes/{theme}/tokens.css", True, expected_attr]
    finally:
        # Same teardown as the theme tests: Chromium's C++ side must be gone
        # before interpreter shutdown.
        view.close()
        view.deleteLater()
        waited = 0
        while shiboken6.isValid(view) and waited < 10_000:
            QTest.qWait(50)
            waited += 50
