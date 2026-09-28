"""Capture every web-UI theme x appearance mode x view of the REAL app, or
measure them, for visual review of the 34 themes.

Builds the full SpikeWindow (all QWebChannel bridges) offscreen, with
TORRENT2000_DATA_DIR pointed at a scratch dir so the user's real config is
never touched, injects demo rows through the pages' own render functions
(tests/theme_probe.py: the same data and metrics the pytest suite uses), then
either captures each view through the Chrome DevTools protocol or measures
readability in the page.

Why DevTools and not QWidget.grab(): a per-pixel translucent host grabs fully
black, and the harness needs the real composited pixels of the full window.

Usage (from the repo root):
  python scripts/theme_review/capture.py [--only=<theme>]... [--view=<view>]... [--out=<dir>] [--resume]
  python scripts/theme_review/capture.py [--only=<theme>]... --metrics=<file.json>
Output: <out>/<theme>/<mode>__<view>.png (+ manifest.json), default out dir
%TEMP%/torrent2000_theme_review/shots. Parallel runs need their own
T2K_DEVTOOLS_PORT and T2K_SHOTS_DATADIR.
Then: compare_metrics.py <before.json> <after.json>, and
pairs.py <ref_dir> <new_dir> <out_dir> for side-by-side planches.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import tempfile  # noqa: E402

SCRATCH = Path(os.environ.get("T2K_REVIEW_DIR", str(Path(tempfile.gettempdir()) / "torrent2000_theme_review")))
# Parallel runs (one per theme) each need their own output dir, data dir and
# DevTools port: --out=<dir>, T2K_SHOTS_DATADIR, T2K_DEVTOOLS_PORT.
_out = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")]
OUT_DIR = Path(_out[0]) if _out else SCRATCH / "shots"
DATA_DIR = Path(os.environ.get("T2K_SHOTS_DATADIR", str(SCRATCH / "datadir")))
REPO = Path(__file__).resolve().parents[2]

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Software rendering: the offscreen GPU path loses its D3D context under
# repeated readbacks (Chromium "ProduceSkia non-existent mailbox" storms).
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")
DEVTOOLS_PORT = int(os.environ.get("T2K_DEVTOOLS_PORT", "9223"))
os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", f"127.0.0.1:{DEVTOOLS_PORT}")
os.environ["TORRENT2000_DATA_DIR"] = str(DATA_DIR)
RESUME = "--resume" in sys.argv
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
from theme_probe import INJECT_JS, METRICS_JS  # noqa: E402  (one definition for harness and tests)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from torrent2000.config.paths import get_history_db_path, get_rss_seen_db_path, get_stats_db_path  # noqa: E402
from torrent2000.config.settings import Settings  # noqa: E402
from torrent2000.engine.anthem_player import AnthemPlayer  # noqa: E402
from torrent2000.engine.auto_shutdown_service import AutoShutdownService  # noqa: E402
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler  # noqa: E402
from torrent2000.engine.clipboard_watcher_service import ClipboardWatcherService  # noqa: E402
from torrent2000.engine.decision_journal import DecisionJournalService  # noqa: E402
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor  # noqa: E402
from torrent2000.engine.known_disk_service import KnownDiskService, KnownDiskStore  # noqa: E402
from torrent2000.engine.network_profile_switcher import NetworkProfileStore  # noqa: E402
from torrent2000.engine.remote_server import RemoteAccessServer  # noqa: E402
from torrent2000.engine.routing_rules import RoutingRuleStore  # noqa: E402
from torrent2000.engine.rss_feed_service import RssFeedService  # noqa: E402
from torrent2000.engine.rss_seen_store import RssSeenStore  # noqa: E402
from torrent2000.engine.session_manager import SessionManager  # noqa: E402
from torrent2000.engine.settings_profiles import SettingsProfileStore  # noqa: E402
from torrent2000.engine.share_limits import ShareLimitService  # noqa: E402
from torrent2000.engine.tag_service import TagService  # noqa: E402
from torrent2000.engine.torrent_search_service import TorrentSearchSourceStore  # noqa: E402
from torrent2000.engine.update_checker import UpdateChecker  # noqa: E402
from torrent2000.i18n.translator import set_language  # noqa: E402
from torrent2000.stats.history_service import HistoryService  # noqa: E402
from torrent2000.stats.history_store import HistoryStore  # noqa: E402
from torrent2000.stats.service import StatsService  # noqa: E402
from torrent2000.stats.store import StatsStore  # noqa: E402
from torrent2000.ui.web.spike_window import SpikeWindow  # noqa: E402

THEMES = sorted(p.name for p in (REPO / "resources" / "web" / "spike" / "themes").iterdir() if (p / "tokens.css").is_file())
MODES = ["light", "dark", "dark_hc"]
SETTLE_MS = 1000
SHOT_MS = 250


SHOTS = [
    ("add", "switchToTab('add');"),
    ("downloads", "switchToTab('downloads');"),
    ("share", "switchToTab('share');"),
    ("rss", "switchToTab('rss');"),
    ("search", "switchToTab('search');"),
    ("profile_top", "switchToTab('profile'); (function(){ const s = document.querySelector('.profile-scroll') || document.getElementById('page-profile'); if (s) s.scrollTop = 0; })();"),
    ("profile_audio", "switchToTab('profile'); (function(){ const v = document.getElementById('pgVolumeSlider'); if (v) v.scrollIntoView({block: 'center'}); })();"),
    ("profile_bottom", "switchToTab('profile'); (function(){ const s = document.querySelector('.profile-scroll') || document.getElementById('page-profile'); if (s) s.scrollTop = 100000; })();"),
    ("modal", "switchToTab('downloads'); try { alertModal('Titre du dialogue', 'Ceci est un message de dialogue de test : le lien magnet n est pas encore disponible pour ce torrent. Reessayez une fois le torrent analyse.', 'Compris'); } catch (e) { console.error(e); }"),
    ("contextmenu", "try { closeModal(); } catch (e) {} switchToTab('downloads'); try { showContextMenu(360, 220, [{label: 'Mettre en pause', onClick(){}}, {label: 'Assigner une categorie...', onClick(){}}, {separator: true}, {label: 'Retirer', onClick(){}}]); } catch (e) { console.error(e); }"),
    ("tooltip", "try { closeContextMenu(); } catch (e) {} switchToTab('downloads'); try { const h = document.querySelector('#page-downloads .info-hint'); if (h) showInfoTooltip(h); } catch (e) { console.error(e); }"),
]
# --view=<name> (repeatable) limits the capture to those views.
_views = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--view=")]
SHOTS = [s for s in SHOTS if not _views or s[0] in _views]
CLEANUP_JS = "try { hideInfoTooltip(); } catch (e) {} try { closeContextMenu(); } catch (e) {} try { closeModal(); } catch (e) {}"

# In-page objective measurements (--metrics mode): real computed colors of the
# elements the audit flagged, composited over their real ancestor backgrounds
# (gradients approximated by the mean of their color stops, same convention as
# the deterministic audit), plus a few layout facts. Any CSS color syntax is
# normalized by painting it on a 1x1 canvas.


class DevTools:
    """Minimal Chrome DevTools Protocol client on PySide6.QtWebSockets, pumped
    by QTest.qWait so it lives in the same Qt event loop as the app."""

    def __init__(self, port: int) -> None:
        from PySide6.QtWebSockets import QWebSocket
        self.port = port
        self.ws = QWebSocket()
        self.replies: dict = {}
        self.next_id = 1
        self.connected = False
        self.ws.connected.connect(self._on_connected)
        self.ws.textMessageReceived.connect(self._on_msg)

    def _on_connected(self) -> None:
        self.connected = True

    def _on_msg(self, txt: str) -> None:
        try:
            m = json.loads(txt)
        except Exception:
            return
        if "id" in m:
            self.replies[m["id"]] = m

    def connect_to_page(self, url_suffix: str = "index.html", timeout_ms: int = 15000) -> None:
        import threading
        import urllib.request
        from PySide6.QtCore import QUrl

        def http_get(url: str, timeout_s: float = 8.0):
            # The DevTools HTTP handler runs on Chromium's browser (= Qt main)
            # thread: a blocking urlopen here would deadlock until timeout.
            box: dict = {}

            def _work():
                try:
                    box["data"] = urllib.request.urlopen(url, timeout=timeout_s).read().decode("utf-8")
                except Exception as exc:  # noqa: BLE001
                    box["error"] = exc

            th = threading.Thread(target=_work, daemon=True)
            th.start()
            waited = 0.0
            while th.is_alive() and waited < timeout_s + 1:
                QTest.qWait(20)
                waited += 0.02
            if "data" not in box:
                raise RuntimeError(str(box.get("error", "timeout")))
            return box["data"]

        deadline = time.time() + timeout_ms / 1000
        target = None
        last_listing = None
        while time.time() < deadline and target is None:
            for endpoint in ("/json/list", "/json"):
                try:
                    data = json.loads(http_get(f"http://127.0.0.1:{self.port}{endpoint}"))
                except Exception as exc:
                    last_listing = f"{endpoint}: {exc}"
                    continue
                last_listing = json.dumps(data)[:1500]
                pages = [t for t in data if t.get("webSocketDebuggerUrl")]
                for t in pages:
                    if url_suffix in t.get("url", ""):
                        target = t
                        break
                if target is None and len(pages) == 1:
                    target = pages[0]
                if target is not None:
                    break
            if target is None:
                QTest.qWait(250)
        if target is None:
            raise RuntimeError("DevTools target for index.html not found; listing = " + str(last_listing))
        print("devtools target:", target.get("type"), target.get("url"), file=sys.stderr)
        self.ws.open(QUrl(target["webSocketDebuggerUrl"]))
        waited = 0
        while not self.connected and waited < timeout_ms:
            QTest.qWait(20)
            waited += 20
        if not self.connected:
            raise RuntimeError("DevTools websocket connection failed")

    def call(self, method: str, params: dict | None = None, timeout_ms: int = 15000):
        mid = self.next_id
        self.next_id += 1
        self.ws.sendTextMessage(json.dumps({"id": mid, "method": method, "params": params or {}}))
        waited = 0
        while mid not in self.replies and waited < timeout_ms:
            QTest.qWait(10)
            waited += 10
        return self.replies.pop(mid, None)

    def screenshot_png(self) -> bytes | None:
        import base64
        r = self.call("Page.captureScreenshot", {"format": "png"})
        if not r or "result" not in r or "data" not in r["result"]:
            print("captureScreenshot failed:", r, file=sys.stderr)
            return None
        return base64.b64decode(r["result"]["data"])


def run_js(page, js: str, timeout_ms: int = 5000):
    box = {"done": False, "value": None}

    def _cb(v):
        box["done"] = True
        box["value"] = v

    page.runJavaScript(js, 0, _cb)
    waited = 0
    while not box["done"] and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    return box["value"]


def main() -> int:
    app = QApplication(sys.argv)
    settings = Settings.load()
    settings.first_launch_seen = True
    set_language(settings.language)
    session_manager = SessionManager(settings)
    share_limit_service = ShareLimitService(session_manager, settings)
    stats_service = StatsService(StatsStore(get_stats_db_path()), session_manager, settings)
    history_service = HistoryService(HistoryStore(get_history_db_path()), session_manager)
    rss_feed_service = RssFeedService(session_manager, settings, RssSeenStore(get_rss_seen_db_path()))
    bandwidth_scheduler = BandwidthScheduler(session_manager, settings)
    disk_space_monitor = DiskSpaceMonitor(session_manager, settings)
    remote_access_server = RemoteAccessServer(session_manager, settings)
    auto_shutdown_service = AutoShutdownService(session_manager, settings)
    known_disk_store = KnownDiskStore()
    known_disk_service = KnownDiskService(known_disk_store, settings)
    decision_journal_service = DecisionJournalService(session_manager, known_disk_service, disk_space_monitor,
                                                      share_limit_service=share_limit_service,
                                                      auto_shutdown_service=auto_shutdown_service,
                                                      rss_feed_service=rss_feed_service)
    window = SpikeWindow(
        session_manager, settings, share_limit_service,
        stats_service=stats_service, history_service=history_service, rss_feed_service=rss_feed_service,
        bandwidth_scheduler=bandwidth_scheduler, disk_space_monitor=disk_space_monitor,
        remote_access_server=remote_access_server, routing_rule_store=RoutingRuleStore(),
        settings_profile_store=SettingsProfileStore(), auto_shutdown_service=auto_shutdown_service,
        anthem_player=AnthemPlayer(0), update_checker=UpdateChecker(settings), known_disk_store=known_disk_store,
        known_disk_service=known_disk_service, network_profile_store=NetworkProfileStore(),
        decision_journal_service=decision_journal_service, tag_service=TagService(),
        clipboard_watcher_service=ClipboardWatcherService(settings),
        torrent_search_source_store=TorrentSearchSourceStore(),
    )
    view = window._view
    page = view.page()
    # Opaque host for the color audit: a per-pixel translucent window captures
    # black offscreen. Only desktop-showing glass is lost, which no offscreen
    # capture could show anyway.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    window.setAttribute(Qt.WA_TranslucentBackground, False)
    view.setAttribute(Qt.WA_TranslucentBackground, False)
    page.setBackgroundColor(QColor("#808080"))
    window.show()
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
    themes = [t for t in THEMES if not only or t in only]

    deadline = time.time() + 30
    ready = False
    while time.time() < deadline:
        QTest.qWait(250)
        v = run_js(page, "(function(){ return !!(document.getElementById('searchSourceAddBtn') && document.getElementById('profileGeneralContainer').children.length); })()")
        if v is True:
            ready = True
            break
    if not ready:
        print("PAGE NOT READY after 30 s", file=sys.stderr)
        return 2
    QTest.qWait(500)
    print("inject:", run_js(page, INJECT_JS), file=sys.stderr)
    QTest.qWait(300)
    metrics_out = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--metrics=")]
    if metrics_out:
        results = {}
        t0 = time.time()
        # Warm-up: the first theme measured used to report a Downloads page not
        # laid out yet (name column 0 px, mosaics unfitted). One throwaway pass.
        run_js(page, f"setActiveTheme({themes[0]!r});")
        run_js(page, "setAppearanceMode('light');")
        QTest.qWait(SETTLE_MS * 3)
        run_js(page, METRICS_JS, timeout_ms=15000)
        QTest.qWait(SETTLE_MS)
        for ti, theme in enumerate(themes):
            run_js(page, f"setActiveTheme({theme!r});")
            results[theme] = {}
            for mode in MODES:
                run_js(page, f"setAppearanceMode({mode!r});")
                QTest.qWait(SETTLE_MS)
                raw = run_js(page, METRICS_JS, timeout_ms=15000)
                try:
                    results[theme][mode] = json.loads(raw) if raw else {"error": "no result"}
                except Exception as exc:  # noqa: BLE001
                    results[theme][mode] = {"error": f"{exc}: {raw!r}"[:300]}
            print(f"[{ti + 1}/{len(themes)}] {theme} metrics ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
        Path(metrics_out[0]).write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"METRICS DONE -> {metrics_out[0]}", file=sys.stderr)
        remote_access_server.stop()
        session_manager.shutdown()
        window.close()
        QTimer.singleShot(0, app.quit)
        app.exec()
        return 0

    devtools = DevTools(DEVTOOLS_PORT)
    devtools.connect_to_page()
    print("devtools connected", file=sys.stderr)

    manifest_path = OUT_DIR / "manifest.json"
    manifest = []
    if RESUME and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = []
    expected = len(MODES) * len(SHOTS)
    t0 = time.time()
    for ti, theme in enumerate(themes):
        if RESUME:
            have = list((OUT_DIR / theme).glob("*.png")) if (OUT_DIR / theme).is_dir() else []
            if len(have) >= expected:
                print(f"[{ti + 1}/{len(themes)}] {theme} already complete, skipped", file=sys.stderr)
                continue
            manifest = [m for m in manifest if m["theme"] != theme]
        run_js(page, f"setActiveTheme({theme!r});")
        for mode in MODES:
            run_js(page, f"setAppearanceMode({mode!r});")
            QTest.qWait(SETTLE_MS)
            (OUT_DIR / theme).mkdir(parents=True, exist_ok=True)
            for shot, js in SHOTS:
                run_js(page, js)
                QTest.qWait(SHOT_MS)
                png = devtools.screenshot_png()
                path = OUT_DIR / theme / f"{mode}__{shot}.png"
                if not png:
                    print(f"GRAB FAILED {theme}/{mode}/{shot}", file=sys.stderr)
                else:
                    path.write_bytes(png)
                    manifest.append({"theme": theme, "mode": mode, "shot": shot, "path": str(path)})
            run_js(page, CLEANUP_JS)
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(f"[{ti + 1}/{len(themes)}] {theme} done ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)

    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"DONE: {len(manifest)} screenshots in {time.time() - t0:.0f}s -> {OUT_DIR}", file=sys.stderr)

    remote_access_server.stop()
    session_manager.shutdown()
    window.close()
    QTimer.singleShot(0, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
