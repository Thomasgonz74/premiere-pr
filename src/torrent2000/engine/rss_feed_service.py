"""RSS feed auto-download: periodically fetches every enabled subscription
in Settings.rss_feeds, parses it as RSS 2.0 XML, and auto-adds a torrent
(via SessionManager) for each new item whose title matches the subscription's
filter keyword.

Stdlib only -- xml.etree.ElementTree for parsing, urllib.request for
fetching -- no feedparser/requests dependency added, per this project's
intentionally small dependency footprint.

Note on XML safety: per Python's own docs
(https://docs.python.org/3/library/xml.html#xml-vulnerabilities),
xml.etree.ElementTree does not resolve external entities or DTDs at all, so
it is not vulnerable to XXE/SSRF-style attacks; it (like most stdlib XML
parsers) remains vulnerable to entity-expansion DoS ("billion laughs")
within a single crafted document. Feed URLs here are subscriptions the user
explicitly configures, the same trust model as any RSS reader -- switching
to a third-party hardened parser (e.g. defusedxml) would add a new
dependency, which is out of scope here; flagged for the maintainer to
weigh separately.

Network I/O (the feed fetch itself, and downloading a linked .torrent file)
must never block the GUI thread, so both run inside a QRunnable submitted to
QThreadPool.globalInstance(); results come back to the GUI thread through
Qt signals. Only the signal-connected slots below -- which always run on the
main thread -- ever touch the sqlite-backed seen-guid store or
SessionManager. See ui/tabs/rss_tab.py for the tab this backs.
"""

import logging
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrent2000 import APP_VERSION
from torrent2000.config.settings import ProxySettings, Settings
from torrent2000.engine.routing_rules import RoutingRuleStore, resolve_destination
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.url_fetch import FetchError, fetch_url
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 15 * 60 * 1000  # 15 minutes
FETCH_TIMEOUT_SECONDS = 20
USER_AGENT = f"Torrent2000/{APP_VERSION}"


def parse_rss_items(xml_bytes: bytes) -> list[dict]:
    """Parse an RSS 2.0 document into a list of {"title", "link", "guid"}
    dicts, one per <channel>/<item>. Pure stdlib parsing, no network or Qt
    involved, so it's directly unit-testable.

    <link> is overridden by an <enclosure url="..."> when present (many
    RSS-based torrent trackers publish the actual .torrent/magnet link via
    an enclosure rather than <link>). <guid> falls back to <link> when
    absent. Items missing both are skipped. Malformed XML yields [].
    """
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []

    items = []
    for item_el in root.findall("./channel/item"):
        title = _child_text(item_el, "title")
        link = _child_text(item_el, "link")
        enclosure = item_el.find("enclosure")
        if enclosure is not None and enclosure.get("url"):
            link = enclosure.get("url")
        guid = _child_text(item_el, "guid") or link
        if not link or not guid:
            continue
        items.append({"title": title, "link": link, "guid": guid})
    return items


def _child_text(item_el, tag: str) -> str:
    el = item_el.find(tag)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _redact_url(url: str) -> str:
    """Strip the query string (and any fragment) from a URL before it is
    ever written to a log line -- private-tracker RSS feed and item URLs
    routinely carry the user's passkey as a query parameter."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def matches_keyword(title: str, filter_keyword: str) -> bool:
    """Case-insensitive substring match; an empty keyword matches every item."""
    if not filter_keyword:
        return True
    return filter_keyword.lower() in title.lower()


class _RunnableSignals(QObject):
    """QRunnable itself can't be a QObject/emit signals, so every worker
    below is handed a shared instance of this small signal bus and emits
    through it -- Qt marshals the emit onto whatever thread the receiving
    slot lives on (the GUI thread, here)."""

    feed_fetched = Signal(str, list)  # feed_url, raw item dicts
    feed_failed = Signal(str, str)  # feed_url, error message
    torrent_downloaded = Signal(str, object, str, str)  # feed_url, item, temp_path, save_path
    torrent_download_failed = Signal(str, object, str)  # feed_url, item, error message


class _FetchFeedRunnable(QRunnable):
    def __init__(self, feed_url: str, signals: _RunnableSignals, proxy: ProxySettings | None = None) -> None:
        super().__init__()
        self._feed_url = feed_url
        self._signals = signals
        self._proxy = proxy

    def run(self) -> None:
        try:
            data = fetch_url(self._feed_url, USER_AGENT, FETCH_TIMEOUT_SECONDS, proxy=self._proxy)
        except FetchError as exc:
            self._signals.feed_failed.emit(self._feed_url, str(exc))
            return
        self._signals.feed_fetched.emit(self._feed_url, parse_rss_items(data))


class _DownloadTorrentRunnable(QRunnable):
    """Downloads a linked .torrent file to a temp path off the GUI thread.
    Adding it to the session still happens back on the main thread (see
    RssFeedService._on_torrent_downloaded)."""

    def __init__(
        self,
        feed_url: str,
        item: dict,
        save_path: str,
        signals: _RunnableSignals,
        proxy: ProxySettings | None = None,
    ) -> None:
        super().__init__()
        self._feed_url = feed_url
        self._item = item
        self._save_path = save_path
        self._signals = signals
        self._proxy = proxy

    def run(self) -> None:
        url = self._item.get("link", "")
        try:
            data = fetch_url(url, USER_AGENT, FETCH_TIMEOUT_SECONDS, proxy=self._proxy)
        except FetchError as exc:
            self._signals.torrent_download_failed.emit(self._feed_url, self._item, str(exc))
            return

        temp_path = Path(tempfile.gettempdir()) / f"torrent2000_rss_{uuid.uuid4().hex}.torrent"
        try:
            temp_path.write_bytes(data)
        except OSError as exc:
            self._signals.torrent_download_failed.emit(self._feed_url, self._item, str(exc))
            return
        self._signals.torrent_downloaded.emit(self._feed_url, self._item, str(temp_path), self._save_path)


class RssFeedService(QObject):
    items_found = Signal(str, list)  # feed_url, newly-added item dicts ({"title","link","guid"})
    feed_check_failed = Signal(str, str)  # feed_url, error message

    def __init__(
        self, session_manager: SessionManager, settings: Settings, seen_store: RssSeenStore, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._seen_store = seen_store
        self._routing_store = RoutingRuleStore()

        self._signals = _RunnableSignals()
        self._signals.feed_fetched.connect(self._on_feed_fetched)
        self._signals.feed_failed.connect(self._on_feed_failed)
        self._signals.torrent_downloaded.connect(self._on_torrent_downloaded)
        self._signals.torrent_download_failed.connect(self._on_torrent_download_failed)

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    # ------------------------------------------------------------------ API

    def check_now(self) -> None:
        """Fetch every enabled feed. Safe to call repeatedly (e.g. from a
        "Vérifier maintenant" button) -- each feed's fetch runs on a
        threadpool worker so this returns immediately."""
        for feed in self._settings.rss_feeds:
            if not feed.enabled or not feed.url:
                continue
            runnable = _FetchFeedRunnable(feed.url, self._signals, proxy=self._settings.proxy)
            QThreadPool.globalInstance().start(runnable)

    # ------------------------------------------------------------- GUI-thread slots

    def _on_feed_fetched(self, feed_url: str, items: list[dict]) -> None:
        feed_config = self._find_feed_config(feed_url)
        if feed_config is None or not feed_config.enabled:
            return  # subscription removed/disabled while the fetch was in flight

        newly_added = []
        for item in items:
            guid = item.get("guid", "")
            if not guid or self._seen_store.is_seen(guid):
                continue
            if not matches_keyword(item.get("title", ""), feed_config.filter_keyword):
                continue

            # Name-only matching: an RSS item exposes nothing but its title
            # at this point -- the actual .torrent (and therefore its
            # tracker list) hasn't been downloaded yet, so a "tracker"
            # routing rule can never match here, only a "name" one. This is
            # a real limitation of the RSS auto-download path, not something
            # worth working around (e.g. by downloading the .torrent just to
            # check its trackers before deciding whether to download it).
            save_path = resolve_destination(
                self._routing_store.list_rules(), self._settings.default_download_dir, name=item.get("title", "")
            )

            link = item.get("link", "")
            if link.startswith("magnet:"):
                self._seen_store.mark_seen(guid, feed_url, item.get("title", ""))
                try:
                    # add_torrent_from_magnet always adds paused/awaiting
                    # analysis by design (see AddTorrentTab's manual review
                    # flow) -- an RSS auto-download has no one to review the
                    # file list, so start it immediately, same as a .torrent
                    # file link already does implicitly via add_torrent_from_file.
                    info_hash = self._session_manager.add_torrent_from_magnet(link, save_path)
                    self._session_manager.start_after_analysis(info_hash)
                except Exception:
                    logger.exception("Failed to add magnet from RSS feed %s", _redact_url(feed_url))
                    continue
                newly_added.append(item)
            elif link.startswith("http://") or link.startswith("https://"):
                self._seen_store.mark_seen(guid, feed_url, item.get("title", ""))
                runnable = _DownloadTorrentRunnable(
                    feed_url, item, save_path, self._signals, proxy=self._settings.proxy
                )
                QThreadPool.globalInstance().start(runnable)
            else:
                logger.warning("Skipping RSS item with unsupported link scheme: %s", _redact_url(link))

        if newly_added:
            self.items_found.emit(feed_url, newly_added)

    def _on_feed_failed(self, feed_url: str, message: str) -> None:
        logger.warning("Failed to fetch RSS feed %s: %s", _redact_url(feed_url), message)
        self.feed_check_failed.emit(feed_url, message)

    def _on_torrent_downloaded(self, feed_url: str, item: dict, temp_path: str, save_path: str) -> None:
        try:
            self._session_manager.add_torrent_from_file(temp_path, save_path or None)
        except Exception:
            logger.exception("Failed to add torrent downloaded from RSS feed %s", _redact_url(feed_url))
            return
        self.items_found.emit(feed_url, [item])

    def _on_torrent_download_failed(self, feed_url: str, item: dict, message: str) -> None:
        logger.warning("Failed to download .torrent linked from RSS feed %s: %s", _redact_url(feed_url), message)
        self.feed_check_failed.emit(feed_url, message)

    # ------------------------------------------------------------------ helpers

    def _find_feed_config(self, feed_url: str):
        for feed in self._settings.rss_feeds:
            if feed.url == feed_url:
                return feed
        return None
