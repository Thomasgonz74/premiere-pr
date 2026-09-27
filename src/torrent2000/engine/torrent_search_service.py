"""Opt-in torrent search across user-configured sources (catalogue idea
"recherche de torrents integree") -- NOT a built-in torrent search engine:
ships with ZERO default sources, by design (this app takes no position on
where a user finds content, unlike the rest of the app which only ever
talks to trackers/sources the user explicitly configures).

Each source is a name + a URL template containing a literal "{query}"
placeholder, expected to return an RSS 2.0 response -- the exact format
engine/rss_feed_service.py already parses. Many indexers/trackers expose a
search-as-RSS endpoint; reusing that parser here means zero new dependency
and zero site-specific HTML scraping to write or maintain (which would
break the moment any one site changed its markup).

Persistence mirrors engine/torrent_categories.py's exact tmp-file +
os.replace() pattern.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from urllib.parse import quote

from torrent2000.config.paths import get_torrent_search_sources_path
from torrent2000.config.settings import ProxySettings
from torrent2000.engine.rss_feed_service import parse_rss_items
from torrent2000.engine.url_fetch import FetchError, fetch_url

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_SECONDS = 15
USER_AGENT = "Torrent2000-Search/1"


@dataclass
class TorrentSearchSource:
    name: str
    url_template: str = ""  # must contain a literal "{query}" placeholder to ever match anything
    enabled: bool = True


class TorrentSearchSourceStore:
    def __init__(self) -> None:
        self._sources: list[TorrentSearchSource] = []
        self._load()

    def list_sources(self) -> list[TorrentSearchSource]:
        return list(self._sources)

    def save_source(self, source: TorrentSearchSource) -> None:
        # Same name = same slot, mirrors routing_rules.RoutingRuleStore.save_rule.
        self._sources = [s for s in self._sources if s.name != source.name]
        self._sources.append(source)
        self._save()

    def delete(self, name: str) -> None:
        self._sources = [s for s in self._sources if s.name != name]
        self._save()

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_torrent_search_sources_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps([asdict(s) for s in self._sources], ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_torrent_search_sources_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, list):
            return
        for entry in data:
            try:
                self._sources.append(TorrentSearchSource(**entry))
            except TypeError:
                continue  # malformed/outdated entry -- skip rather than crash on startup


def build_search_url(url_template: str, query: str) -> str:
    return url_template.replace("{query}", quote(query))


def search_source(
    source: TorrentSearchSource, query: str, proxy: "ProxySettings | None" = None
) -> list[dict]:
    """Returns [{"title", "link", "source"}, ...] for one source. Never
    raises -- a failing/unreachable/malformed source just contributes zero
    results rather than aborting the whole search (see search_all)."""
    if "{query}" not in source.url_template:
        return []
    url = build_search_url(source.url_template, query)
    try:
        data = fetch_url(url, USER_AGENT, SEARCH_TIMEOUT_SECONDS, proxy=proxy)
    except FetchError:
        logger.warning("Torrent search source %r failed to fetch", source.name)
        return []
    items = parse_rss_items(data)
    return [{"title": item["title"], "link": item["link"], "source": source.name} for item in items]


def search_all(
    sources: list[TorrentSearchSource], query: str, proxy: "ProxySettings | None" = None
) -> list[dict]:
    """Sequential across sources (a handful of user-configured sources,
    each already timeout-bounded by fetch_url -- not worth the complexity
    of parallelizing for this scale). Runs on a QThreadPool worker, never
    the GUI thread -- see ui/web/bridge_search.py."""
    results: list[dict] = []
    for source in sources:
        if not source.enabled:
            continue
        results.extend(search_source(source, query, proxy=proxy))
    return results
