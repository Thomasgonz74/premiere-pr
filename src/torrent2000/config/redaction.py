"""Shared secret redaction for any Settings dict about to leave the live
config file -- an export, or a timestamped backup snapshot -- and for any
URL about to reach a log line (redact_url_for_log). Mirrors which
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
# A base64url token ("aB3_x-9..."), whose "-"/"_" would cut it into runs too
# short for the pattern above. A lowercase letter right before a capital sets
# it apart from a title slug ("The-Mandalorian-Season2-1080p").
# ponytail: heuristic, ~3% of random 22-char tokens have no such pair (or no
# digit) and stay; a camelCase slug with a digit is blanked.
_SECRET_PATH_B64 = re.compile(r"(?=[\w-]*\d)(?=[\w-]*[a-z][A-Z])[A-Za-z0-9_-]{20,}", re.ASCII)
# A dashed UUID, whose hex runs are too short for _SECRET_PATH_RUN.
_SECRET_PATH_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


def _redact_feed_url(url: str) -> str:
    """Blanks only what looks like a passkey, so a public feed's own query
    (search, category...) survives the round trip and two feeds stay two.
    A URL urlsplit refuses (an unclosed IPv6 bracket) is blanked whole:
    raising here made every later Settings.save() raise too."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    path = _SECRET_PATH_RUN.sub("", _SECRET_PATH_B64.sub("", _SECRET_PATH_UUID.sub("", parts.path)))
    query = _QUERY_PARAM.sub(
        lambda m: f"{m.group(1)}=" if _SECRET_PARAM.search(m.group(1)) else m.group(0), parts.query
    )
    # Drop any "user:password@" -- keeps host, port and IPv6 brackets as typed.
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, path, query, parts.fragment))


def redact_url_for_log(url: str) -> str:
    """_redact_feed_url without the query string or fragment at all: what a
    log line or the decision journal may show of a feed or item URL."""
    parts = urlsplit(_redact_feed_url(url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


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
