"""QWebChannel bridge backing the RSS page -- mirrors RssTab exactly:
subscriptions live in settings.rss_feeds, the periodic check/fetch/add logic
itself stays entirely inside the already-constructed RssFeedService instance
passed in (this bridge never touches RssSeenStore or the network directly,
same as RssTab never did).
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.session_manager import SessionManager


def _feed_to_dict(feed: RssFeedSubscription) -> dict:
    return {"url": feed.url, "filterKeyword": feed.filter_keyword, "enabled": feed.enabled}


class RssBridge(QObject):
    itemsFound = Signal(str, "QVariantList")  # feed_url, newly-found item dicts
    feedCheckFailed = Signal(str, str)  # feed_url, error message

    def __init__(
        self, session_manager: SessionManager, rss_feed_service: RssFeedService, settings: Settings, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._rss_feed_service = rss_feed_service
        self._settings = settings

        rss_feed_service.items_found.connect(self.itemsFound.emit)
        rss_feed_service.feed_check_failed.connect(self.feedCheckFailed.emit)

    @Slot(result="QVariantList")
    def listFeeds(self) -> list:
        return [_feed_to_dict(feed) for feed in self._settings.rss_feeds]

    @Slot(str, str, result="QVariantMap")
    def addFeed(self, url: str, filter_keyword: str) -> dict:
        url = (url or "").strip()
        if not url:
            return {"ok": False, "error": "URL requise"}
        self._settings.rss_feeds.append(RssFeedSubscription(url=url, filter_keyword=filter_keyword or "", enabled=True))
        self._settings.save()
        return {"ok": True}

    @Slot(str)
    def removeFeed(self, url: str) -> None:
        # First-occurrence match by url, same as RssTab's identity-based
        # removal collapses to when subscriptions are looked up by url alone.
        for i, existing in enumerate(self._settings.rss_feeds):
            if existing.url == url:
                del self._settings.rss_feeds[i]
                self._settings.save()
                break

    @Slot(str, bool)
    def setFeedEnabled(self, url: str, enabled: bool) -> None:
        for feed in self._settings.rss_feeds:
            if feed.url == url:
                feed.enabled = enabled
                self._settings.save()
                break

    @Slot()
    def checkNow(self) -> None:
        self._rss_feed_service.check_now()
