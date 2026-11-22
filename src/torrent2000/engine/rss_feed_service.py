"""RSS feed auto-download: periodically fetches every enabled subscription
in Settings.rss_feeds, parses it as RSS 2.0 XML, and auto-adds a torrent
(via SessionManager) for each new item whose title matches the subscription's
filter keyword.

Stdlib only -- xml.etree.ElementTree for parsing, urllib.request for
fetching -- no feedparser/requests dependency added, per this project's
intentionally small dependency footprint.

Note on XML safety (re-verified empirically against a real malicious local
RSS server, not assumed from the docs alone -- see security_test/): per
Python's own docs (https://docs.python.org/3/library/xml.html#xml-vulnerabilities),
xml.etree.ElementTree does not resolve external entities or DTDs at all, so
it is not vulnerable to XXE/SSRF-style attacks -- confirmed: a crafted feed
referencing a local file via an external entity fails with ParseError and
never leaks the file's content. A "billion laughs" entity-expansion bomb
also failed harmlessly here (<1s, no memory spike) because the libexpat
this Python build links against (2.7.1) has shipped a built-in
entity-amplification limit since 2021 -- this is a property of the linked
expat version, not a guarantee of this module's own code, so it isn't
something to rely on if this ever runs against an older Python/expat.
Feed URLs here are subscriptions the user explicitly configures, the same
trust model as any RSS reader.

Network I/O (the feed fetch itself, and downloading a linked .torrent file)
must never block the GUI thread, so both run inside a QRunnable submitted to
QThreadPool.globalInstance(); results come back to the GUI thread through
Qt signals. Only the signal-connected slots below -- which always run on the
main thread -- ever touch the sqlite-backed seen-guid store or
SessionManager. See ui/tabs/rss_tab.py for the tab this backs.
"""

import logging
import re
import tempfile
import uuid
from collections import Counter
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrent2000 import APP_VERSION
from torrent2000.config.paths import get_rss_pending_magnets_path
from torrent2000.config.settings import ProxySettings, Settings
from torrent2000.danger_scanner.scanner import auto_exclude_indices, scan_files
from torrent2000.engine import persistence
from torrent2000.engine.routing_rules import RoutingRuleStore, find_matching_rule
from torrent2000.engine.torrent_files import files_from_torrent_path
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.session_manager import SessionManager, TorrentAlreadyPresentError
from torrent2000.engine.url_fetch import FetchError, fetch_url
from torrent2000.i18n.translator import tr
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 15 * 60 * 1000  # 15 minutes
FETCH_TIMEOUT_SECONDS = 20
# Tries per item and app session: one whose .torrent is gone (404) or whose
# link answers with a login page is not fetched again at every check.
# ponytail: per-session count, a restart tries again; a backoff if a
# tracker's outages outlast three checks.
MAX_ITEM_ATTEMPTS = 3
USER_AGENT = f"Torrent2000/{APP_VERSION}"


def parse_rss_items(xml_bytes: bytes) -> list[dict]:
    """Parse an RSS 2.0 document into a list of {"title", "link", "guid",
    "published"} dicts, one per <channel>/<item> -- published is the POSIX
    time of its <pubDate>, 0.0 when absent or unreadable. Pure stdlib
    parsing, no network or Qt involved, so it's directly unit-testable.

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
        try:
            published = parsedate_to_datetime(_child_text(item_el, "pubDate")).timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            published = 0.0
        items.append({"title": title, "link": link, "guid": guid, "published": published})
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


_RESOLUTION_RE = re.compile(r"(\d{3,4})p\b", re.IGNORECASE)
# The episode markers latest_episode_only ranks by. A number right after
# "S", "E", "Episode" or " - " is still not one when it is a resolution,
# bit depth or audio layout ("720p", "1080i", "10bit", "5.1"); the codec
# numbers ("x264", "H.265") never follow such a prefix.
_MARKER_START = r"(?<![a-z0-9'\u2019])"
_NOT_TECH = r"(?![\dp]|i\b|bit|[.,]\d(?!\d))"
# "S01E05", "s01.e05", "Season 2 Episode 3", "1x05" (not the "1x264" of "5.1x264").
_SEASON_EPISODE_RE = re.compile(
    _MARKER_START + r"(?:s(?:eason)?[ ._-]{0,3}(\d{1,4})[ ._-]{0,3}e(?:p(?:isode)?)?[ ._-]{0,3}(\d{1,4})"
    r"|(?<!\d[.,])(\d{1,2})x(\d{2,3}))(?!\d)",
    re.IGNORECASE,
)
# Daily shows: "2026-11-22", "2026.11.22", and "22.11.2026" (or "11.22.2026").
_YMD_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)([-._])(\d\d)\2(\d\d)(?!\d)")
_DMY_RE = re.compile(r"(?<!\d)(\d\d)([-._])(\d\d)\2((?:19|20)\d\d)(?!\d)")
# A season pack: "S02", "Season 2" -- ranked after every episode of that season.
_SEASON_RE = re.compile(_MARKER_START + r"s(?:eason)?[ ._-]?(\d{1,4})" + _NOT_TECH, re.IGNORECASE)
_WHOLE_SEASON = 10**6
# No season: "Episode.42", "Ep 7", "E05", or the anime-style "Show - 05".
_EPISODE_RE = re.compile(
    r"(?:" + _MARKER_START + r"e(?:p(?:isode)?)?[ ._-]?|\s-\s)(\d{1,4})" + _NOT_TECH, re.IGNORECASE
)


def _title_resolution(title: str) -> int | None:
    """Extracts a "720p"/"1080p"-style resolution marker from a title, or
    None if the title carries none -- an item with no resolution marker
    never fails a resolution_min/max filter (nothing to compare)."""
    match = _RESOLUTION_RE.search(title)
    return int(match.group(1)) if match else None


def _title_words(text: str) -> tuple[str, ...]:
    """Lower-cased words of a title, without a leading "[Group]" tag --
    "Show.Name" and "[Subs] Show Name" both give ("show", "name")."""
    return tuple(re.findall(r"[^\W_]+", re.sub(r"^\s*\[[^\]]*\]", "", text).lower()))


def _title_date(title: str) -> tuple[int, tuple[int, int, int] | None] | None:
    """(where it starts, (year, month, day)) of an air date in a title --
    (where it starts, None) for an ambiguous one."""
    match = _YMD_RE.search(title)
    if match:
        year, month, day = int(match.group(1)), int(match.group(3)), int(match.group(4))
    else:
        match = _DMY_RE.search(title)
        if match is None:
            return None
        first, second, year = int(match.group(1)), int(match.group(3)), int(match.group(4))
        if first != second and first <= 12 and second <= 12:
            return match.start(), None  # "05.11.2026": 5 November or May 11?
        day, month = (first, second) if first > 12 else (second, first)
    try:
        date(year, month, day)
    except ValueError:
        return None
    return match.start(), (year, month, day)


def _title_episode(title: str) -> tuple[tuple[str, ...], tuple[int, ...]] | None:
    """(show, rank) for latest_episode_only -- "Show.S02E15.720p" ->
    (("show",), (2, 15)), "Show.2026.11.22" -> (("show",), (2026, 11, 22)),
    "Show.S02" (a season pack) -> after every S02 episode, "Episode.42" or
    "Show - 42" -> (0, 42) -- or None when the title carries no marker at
    all (a special, a movie, an ambiguous "05.11.2026"), which then ranks
    by publication date instead."""
    match = _SEASON_EPISODE_RE.search(title)
    if match:
        season, episode = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        return _title_words(title[: match.start()]), (int(season), int(episode))
    dated = _title_date(title)
    if dated:
        # Nor is the "05" of an ambiguous "Show - 05.11.2026" an episode.
        return (_title_words(title[: dated[0]]), dated[1]) if dated[1] else None
    match = _SEASON_RE.search(title)
    if match:
        # "Show S2 - 05", "Show (Season 2) Episode 5": an episode of that season.
        episode = _EPISODE_RE.search(title, match.end())
        if episode and not title[match.end() : episode.start()].strip(" ._-()[]"):
            return _title_words(title[: match.start()]), (int(match.group(1)), int(episode.group(1)))
        return _title_words(title[: match.start()]), (int(match.group(1)), _WHOLE_SEASON)
    match = _EPISODE_RE.search(title)
    if match:
        return _title_words(title[: match.start()]), (0, int(match.group(1)))
    return None


def _latest_per_show(items: list[dict], taken: set[str]) -> list[tuple[dict, list[dict]]]:
    """latest_episode_only: (newest item, [its show's other items not in
    taken]) for each show among items -- in feed order, newest first; taken
    holds the guids already downloaded (or downloading), which compete but
    win a tie, so a new copy of an episode already taken loses. Items with
    an episode marker rank by it; those with none rank by publication date
    (else feed order) among the show's other unmarked items (only the
    newest one counts), under the marked show their title starts with,
    else under the words before their first number."""
    parsed = [(item, _title_episode(item.get("title", ""))) for item in items]
    shows = {episode[0] for _item, episode in parsed if episode and episode[0]}
    groups: dict[tuple, list[tuple[tuple, dict]]] = {}
    for index, (item, episode) in enumerate(parsed):
        if episode:
            key, rank = (episode[0], True), episode[1]
        else:
            words = _title_words(item.get("title", ""))
            show = max((s for s in shows if words[: len(s)] == s), key=len, default=None)
            if show is None:
                first_number = next((i for i, w in enumerate(words) if any(c.isdigit() for c in w)), len(words))
                show = words[:first_number] or words
            key, rank = (show, False), (item.get("published", 0.0), -index)
        groups.setdefault(key, []).append(((rank, item.get("guid") in taken), item))
    result = []
    for members in groups.values():
        newest = max(members, key=lambda member: member[0])[1]
        result.append((newest, [it for _rank, it in members if it is not newest and it.get("guid") not in taken]))
    return result


def filter_regex_error(*patterns: str) -> str | None:
    """User-facing message for the first advanced-filter pattern that does
    not compile, or None -- checked before saving (bridge_rss) and again
    before each feed check, for a config.json edited by hand."""
    for pattern in patterns:
        if not pattern:
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            return tr("web.rss.filter_invalid_regex", pattern=pattern, message=str(exc))
    return None


def matches_advanced_filters(title: str, feed: "RssFeedSubscription") -> bool:
    """All of feed's optional advanced filters, on top of filter_keyword
    (checked separately by the caller) -- every unset filter (empty
    string/0) imposes no constraint, same convention as filter_keyword."""
    if feed.regex_include and not re.search(feed.regex_include, title, re.IGNORECASE):
        return False
    if feed.regex_exclude and re.search(feed.regex_exclude, title, re.IGNORECASE):
        return False
    resolution = _title_resolution(title)
    if resolution is not None:
        if feed.resolution_min and resolution < feed.resolution_min:
            return False
        if feed.resolution_max and resolution > feed.resolution_max:
            return False
    return True


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
        self,
        session_manager: SessionManager,
        settings: Settings,
        seen_store: RssSeenStore,
        routing_store: RoutingRuleStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._seen_store = seen_store
        # Shared with the Profile tab's rule editor in the app (see
        # WatchFolderService.__init__).
        self._routing_store = routing_store if routing_store is not None else RoutingRuleStore()
        # Set by MemoryPressureGovernor (see engine/memory_pressure_governor.py)
        # while system memory usage is over its configured threshold -- skips
        # feed checks entirely until pressure eases, rather than skipping
        # individual steps of an in-flight check.
        self._paused = False
        # info_hash -> True for a magnet-added torrent whose danger scan +
        # auto-exclude (see danger_scanner.scanner.auto_exclude_indices)
        # hasn't run yet -- its files aren't known until metadata arrives,
        # so start_after_analysis() is deferred until _on_rss_metadata_received.
        # Saved: after a restart the restored magnet still awaits it.
        self._pending_magnet_scans: set[str] = {
            h
            for h in persistence.load_json(get_rss_pending_magnets_path(), [])
            if isinstance(h, str) and session_manager.get_record(h) is not None
        }

        # guid -> the items to mark seen with it, for each .torrent being
        # downloaded: an item is marked seen only once added, so this keeps
        # the next check from queueing it again meanwhile.
        self._downloads_in_flight: dict[str, list[dict]] = {}
        # guid -> failed adds/downloads this session, see MAX_ITEM_ATTEMPTS.
        self._failed_attempts: Counter[str] = Counter()

        self._signals = _RunnableSignals()
        self._signals.feed_fetched.connect(self._on_feed_fetched)
        self._signals.feed_failed.connect(self._on_feed_failed)
        self._signals.torrent_downloaded.connect(self._on_torrent_downloaded)
        self._signals.torrent_download_failed.connect(self._on_torrent_download_failed)
        session_manager.metadata_received.connect(self._on_rss_metadata_received)

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    # ------------------------------------------------------------------ API

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def check_now(self) -> None:
        """Fetch every enabled feed. Safe to call repeatedly (e.g. from a
        "Vérifier maintenant" button) -- each feed's fetch runs on a
        threadpool worker so this returns immediately."""
        if self._paused:
            return
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
        regex_error = filter_regex_error(feed_config.regex_include, feed_config.regex_exclude)
        if regex_error:
            # Nothing is added or marked seen: the items still download once
            # the pattern is fixed.
            logger.warning("Skipping RSS feed %s: %s", _redact_url(feed_url), regex_error)
            self.feed_check_failed.emit(feed_url, regex_error)
            return

        matching = [
            item
            for item in items
            if item.get("guid")
            and matches_keyword(item.get("title", ""), feed_config.filter_keyword)
            and matches_advanced_filters(item.get("title", ""), feed_config)
        ]
        taken = {
            item["guid"]
            for item in matching
            if item["guid"] in self._downloads_in_flight or self._seen_store.is_seen(item["guid"])
        }
        # guid of each item to add -> the older (or same-episode) items
        # skipped for it, marked seen once it is added -- never before, so a
        # failed add or download leaves the whole show for the next check.
        skipped_for: dict[str, list[dict]] = {}
        if feed_config.latest_episode_only:
            # Avoids flooding on the first check of a feed with a long
            # backlog of matching items.
            for newest, older in _latest_per_show(matching, taken):
                if newest["guid"] not in taken:
                    skipped_for[newest["guid"]] = older
                elif newest["guid"] not in self._downloads_in_flight:
                    self._mark_seen(feed_url, older)  # an older-or-equal one was taken
        else:
            skipped_for = {item["guid"]: [] for item in matching if item["guid"] not in taken}
        candidates = [
            item
            for item in matching
            if item["guid"] in skipped_for and self._failed_attempts[item["guid"]] < MAX_ITEM_ATTEMPTS
        ]

        newly_added = []
        for item in candidates:
            guid = item.get("guid", "")
            done = [item, *skipped_for[guid]]
            # Name-only matching: an RSS item exposes nothing but its title
            # at this point -- the actual .torrent (and therefore its
            # tracker list) hasn't been downloaded yet, so a "tracker"
            # routing rule can never match here, only a "name" one. This is
            # a real limitation of the RSS auto-download path, not something
            # worth working around (e.g. by downloading the .torrent just to
            # check its trackers before deciding whether to download it).
            matched_rule = find_matching_rule(
                self._routing_store.list_rules(), name=item.get("title", "")
            )
            save_path = matched_rule.destination if matched_rule else self._settings.default_download_dir

            link = item.get("link", "")
            if link.startswith("magnet:"):
                try:
                    # add_torrent_from_magnet always adds awaiting analysis
                    # (metadata only, no piece) by design (see the Add page's
                    # manual review flow) -- an RSS auto-download has no one
                    # to review the file list. start_after_analysis() is
                    # deferred to _on_rss_metadata_received() below, so the
                    # danger scan + auto-exclude can run once the file list
                    # is actually known, same cutoff the manual Add page uses.
                    info_hash = self._session_manager.add_torrent_from_magnet(link, save_path)
                    self._pending_magnet_scans.add(info_hash)
                    self._save_pending_magnet_scans()
                    if matched_rule is not None:
                        self._session_manager.set_matched_rule_name(info_hash, matched_rule.name)
                except TorrentAlreadyPresentError:
                    self._mark_seen(feed_url, done)
                    continue
                except Exception:
                    logger.exception("Failed to add magnet from RSS feed %s", _redact_url(feed_url))
                    self._failed_attempts[guid] += 1
                    continue  # not marked seen: tried again at the next check
                self._mark_seen(feed_url, done)
                newly_added.append(item)
            elif link.startswith("http://") or link.startswith("https://"):
                self._downloads_in_flight[guid] = done
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
        done = self._downloads_in_flight.pop(item.get("guid", ""), [item])
        excluded: set[int] = set()
        try:
            # The .torrent is already on disk here, so -- unlike the magnet
            # case below -- its files are known up front and can be scanned
            # before add, same cutoff the manual Add page uses.
            files = files_from_torrent_path(temp_path)
            excluded = auto_exclude_indices(scan_files(files), self._settings.danger_auto_exclude_threshold)
        except Exception:
            pass
        try:
            info_hash = self._session_manager.add_torrent_from_file(temp_path, save_path or None, excluded)
            # Re-resolved from the item's title rather than threaded through
            # _DownloadTorrentRunnable's signal -- find_matching_rule() is a
            # cheap pure lookup, and re-deriving it here avoids widening that
            # signal's signature just to carry a rule name a few seconds.
            matched_rule = find_matching_rule(self._routing_store.list_rules(), name=item.get("title", ""))
            if matched_rule is not None:
                self._session_manager.set_matched_rule_name(info_hash, matched_rule.name)
        except TorrentAlreadyPresentError:
            self._mark_seen(feed_url, done)
            return
        except Exception:
            logger.exception("Failed to add torrent downloaded from RSS feed %s", _redact_url(feed_url))
            self._failed_attempts[item.get("guid", "")] += 1
            return
        finally:
            # libtorrent has parsed the file by now (the metadata lives on in
            # the resume data) -- nothing reads it again, added or not.
            # Windows can briefly lock it; the startup sweep
            # (dropped_file.cleanup_stale_temp_torrents) catches a leftover.
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
        self._mark_seen(feed_url, done)
        self.items_found.emit(feed_url, [item])

    def _on_rss_metadata_received(self, info_hash: str) -> None:
        if info_hash not in self._pending_magnet_scans:
            return
        self._pending_magnet_scans.discard(info_hash)
        self._save_pending_magnet_scans()
        try:
            files = self._session_manager.get_torrent_files(info_hash)
            excluded = auto_exclude_indices(scan_files(files), self._settings.danger_auto_exclude_threshold)
            if excluded:
                self._session_manager.exclude_files(info_hash, excluded)
        except Exception:
            logger.exception("Failed to scan RSS-added magnet torrent %s for dangerous files", info_hash)
        self._session_manager.start_after_analysis(info_hash)

    def _save_pending_magnet_scans(self) -> None:
        persistence.save_json(get_rss_pending_magnets_path(), sorted(self._pending_magnet_scans))

    def _on_torrent_download_failed(self, feed_url: str, item: dict, message: str) -> None:
        self._downloads_in_flight.pop(item.get("guid", ""), None)  # not marked seen: tried again
        self._failed_attempts[item.get("guid", "")] += 1
        logger.warning("Failed to download .torrent linked from RSS feed %s: %s", _redact_url(feed_url), message)
        self.feed_check_failed.emit(feed_url, message)

    # ------------------------------------------------------------------ helpers

    def _mark_seen(self, feed_url: str, items: list[dict]) -> None:
        for item in items:
            self._seen_store.mark_seen(item.get("guid", ""), feed_url, item.get("title", ""), commit=False)
        self._seen_store.commit()

    def _find_feed_config(self, feed_url: str):
        for feed in self._settings.rss_feeds:
            if feed.url == feed_url:
                return feed
        return None
