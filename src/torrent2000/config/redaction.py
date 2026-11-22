"""Shared secret redaction for any Settings dict about to leave the live
config file -- an export, or a timestamped backup snapshot. Mirrors which
fields settings_history.py already excludes from its own diff log
(`proxy`, `remote_access_token` and `webhook_url`), so all three places
agree on what counts as sensitive.
"""

from urllib.parse import urlsplit, urlunsplit


def redact_settings_dict(data: dict) -> dict:
    """Mutates and returns `data` (as produced by dataclasses.asdict(settings)
    or json.loads() of a config file) with proxy.password,
    remote_access_token and webhook_url zeroed out, and the query string of
    every RSS feed URL dropped (private-tracker passkeys ride there, same
    rule as rss_feed_service._redact_url for logs). Safe to call on a dict
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
            parts = urlsplit(feed["url"])
            feed["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return data
