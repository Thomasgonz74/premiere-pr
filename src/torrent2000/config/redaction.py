"""Shared secret redaction for any Settings dict about to leave the live
config file -- an export, or a timestamped backup snapshot. Mirrors which
fields settings_history.py already excludes from its own diff log
(`proxy`, `remote_access_token` and `webhook_url`), so all three places
agree on what counts as sensitive.
"""

import re
from urllib.parse import urlsplit, urlunsplit

# Query parameters private trackers carry a passkey in (passkey, torrent_pass,
# apikey, rsskey, authkey, token, Gazelle's auth, TorrentDay/IPT's tp...).
# ponytail: name heuristic, a tracker using another name keeps its key in the
# export -- add the name here.
_SECRET_PARAM = re.compile(r"pass|token|secret|key$|^(auth|pk|tp|sid)$", re.IGNORECASE)
_QUERY_PARAM = re.compile(r"([^&;=]+)=([^&;]*)")
# A long run of mixed letters and digits in the path: a passkey put there
# (TorrentLeech /rss/<passkey>, UNIT3D /rss/<id>.<rsskey>, AnimeBytes...).
_SECRET_PATH_RUN = re.compile(r"(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{20,}")


def _redact_feed_url(url: str) -> str:
    """Blanks only what looks like a passkey, so a public feed's own query
    (search, category...) survives the round trip and two feeds stay two."""
    parts = urlsplit(url)
    path = _SECRET_PATH_RUN.sub("", parts.path)
    query = _QUERY_PARAM.sub(
        lambda m: f"{m.group(1)}=" if _SECRET_PARAM.search(m.group(1)) else m.group(0), parts.query
    )
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def redact_settings_dict(data: dict) -> dict:
    """Mutates and returns `data` (as produced by dataclasses.asdict(settings)
    or json.loads() of a config file) with proxy.password,
    remote_access_token and webhook_url zeroed out, and the passkey of every
    RSS feed URL blanked (see _redact_feed_url). Safe to call on a dict
    missing any of these keys (nothing to redact yet)."""
    proxy = data.get("proxy")
    if isinstance(proxy, dict) and "password" in proxy:
        proxy["password"] = ""
    # A Discord/Slack/ntfy webhook URL is a bearer secret: whoever has it can post.
    for key in ("remote_access_token", "webhook_url"):
        if key in data:
            data[key] = ""
    feeds = data.get("rss_feeds")
    for feed in feeds if isinstance(feeds, list) else ():
        if isinstance(feed, dict) and isinstance(feed.get("url"), str):
            feed["url"] = _redact_feed_url(feed["url"])
    return data
