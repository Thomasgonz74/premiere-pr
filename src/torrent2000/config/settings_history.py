"""Restorable history of Settings.save() calls.

Append-only JSONL diff log written to get_config_backups_dir()/history.jsonl --
reuses the exact folder/retention pattern already established by
bridge_profile_security.py's _backup_current_config() (timestamped, capped,
best-effort, silently skipped when there's nothing to compare against yet),
just applied as a running diff log instead of full-file snapshots.

Sensitive fields (the whole `proxy` sub-object -- host/username/password --
the remote-access API token and the webhook URL) are never written to this file,
and RSS feed URLs only with their passkey blanked (config/redaction.py).
"""

import json
import os
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from torrent2000.config.paths import get_config_backups_dir, retry_if_dir_vanished
from torrent2000.config.redaction import _redact_feed_url

if TYPE_CHECKING:
    from torrent2000.config.settings import Settings

_HISTORY_FILENAME = "history.jsonl"
_MAX_HISTORY_ENTRIES = 200  # ponytail: flat line cap, revisit if that's ever too short
# Same reasoning as engine/decision_journal.py's _TRIM_THRESHOLD_BYTES: the
# size comes from f.tell(), the file is only re-read (Defender scans a
# freshly written file on open) once it is about twice 200 typical lines.
_TRIM_THRESHOLD_BYTES = 64 * 1024

# `proxy` carries host/username/password; `remote_access_token` is a bearer
# secret for the local remote-access HTTP server; `webhook_url` is one for
# whatever it posts to. None is ever diffed or persisted here, whole field
# excluded rather than trying to redact within it.
_EXCLUDED_FIELDS = {"proxy", "remote_access_token", "webhook_url"}


def _history_path() -> Path:
    return get_config_backups_dir() / _HISTORY_FILENAME


def _redact_feeds(data: dict) -> dict:
    """A copy of `data` whose feed URLs lost their passkey, as in an export.
    A feed whose URL this changed says so ("url_redacted"), so a restore
    never writes it back."""
    if not isinstance(data.get("rss_feeds"), list):
        return data
    feeds = []
    for feed in data["rss_feeds"]:
        if isinstance(feed, dict) and isinstance(feed.get("url"), str):
            url = _redact_feed_url(feed["url"])
            if url != feed["url"]:
                feed = {**feed, "url": url, "url_redacted": True}
        feeds.append(feed)
    return {**data, "rss_feeds": feeds}


def _with_live_feed_urls(old_feeds: list, live_feeds: list) -> list:
    """The restored feeds. A URL kept whole in history.jsonl comes back as
    recorded; a redacted one is taken from the live feed it matches -- same
    redacted URL, else same position on the same host -- and its feed is
    dropped if none does, rather than written back without its passkey."""
    from torrent2000.config.settings import RssFeedSubscription, _from_dict

    old_feeds = [feed for feed in old_feeds if isinstance(feed, dict)]
    unclaimed = dict(enumerate(live_feeds))
    urls = {i: feed.get("url", "") for i, feed in enumerate(old_feeds) if not feed.get("url_redacted")}
    redacted = [i for i in range(len(old_feeds)) if i not in urls]
    for i in redacted:
        j = next((j for j, live in unclaimed.items() if _redact_feed_url(live.url) == old_feeds[i]["url"]), None)
        if j is not None:
            urls[i] = unclaimed.pop(j).url
    for i in redacted:
        live = unclaimed.get(i)
        if i not in urls and live is not None and urlsplit(live.url).hostname == urlsplit(old_feeds[i]["url"]).hostname:
            urls[i] = unclaimed.pop(i).url
    return [_from_dict(RssFeedSubscription, {**feed, "url": urls[i]}) for i, feed in enumerate(old_feeds) if i in urls]


def record_settings_change(old_data: dict, new_data: dict) -> None:
    """Appends one JSONL line diffing old_data -> new_data (both as produced
    by dataclasses.asdict(settings)), keeping only top-level fields that
    actually changed and dropping excluded/sensitive ones. No-op if nothing
    changed. Best-effort: never raises, matches _backup_current_config()'s
    silently-skipped-on-failure convention.
    """
    old_data, new_data = _redact_feeds(old_data), _redact_feeds(new_data)
    changes = {}
    for key, new_value in new_data.items():
        if key in _EXCLUDED_FIELDS:
            continue
        old_value = old_data.get(key)
        if old_value != new_value:
            changes[key] = {"old": old_value, "new": new_value}
    if not changes:
        return
    entry = {"timestamp": datetime.now().isoformat(timespec="seconds"), "changes": changes}

    def _write() -> int:
        with _history_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return f.tell()

    try:
        # config_backups/ holds no open handle, so the user can delete it mid-run.
        size = retry_if_dir_vanished(_write)
    except OSError:
        return
    if size > _TRIM_THRESHOLD_BYTES:
        _trim_history()


def _trim_history() -> None:
    """Back to the last _MAX_HISTORY_ENTRIES lines (only the line count is
    capped, not the size), through a tmp file + os.replace() so a crash
    mid-trim never leaves a truncated history."""
    path = _history_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= _MAX_HISTORY_ENTRIES:
        return
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text("\n".join(lines[-_MAX_HISTORY_ENTRIES:]) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        return


def read_settings_history(limit: int = 50) -> list[dict]:
    """Returns up to `limit` history entries, most recent first. Malformed
    lines (e.g. a truncated write) are skipped rather than failing the read.
    """
    path = _history_path()
    if not path.exists():
        return []
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    entries.reverse()
    return entries[:limit]


def restore_settings_snapshot(entry: dict, settings: "Settings") -> None:
    """Reapplies the pre-change ("old") value of every field recorded in
    `entry` onto `settings` -- i.e. undoes that one save -- then persists via
    Settings.save() (which itself journals this restore as a new history
    entry, same as any other save). Fields no longer part of Settings (an
    entry from an older schema version) are silently dropped, matching
    _from_dict's own unknown-key handling. Excluded/sensitive fields are
    never in `entry` to begin with, so nothing to skip there beyond the
    defensive check below.
    """
    from torrent2000.config.settings import BandwidthSchedule, _from_dict

    valid_fields = {f.name for f in fields(settings)}
    for key, change in entry.get("changes", {}).items():
        if key not in valid_fields or key in _EXCLUDED_FIELDS:
            continue
        old_value = change.get("old")
        # Nested dataclass fields are stored as plain dict/list (asdict
        # output) in history.jsonl -- rebuild real instances the same way
        # Settings.load() does, so callers get back a normal Settings object.
        if key == "bandwidth_schedule":
            old_value = _from_dict(BandwidthSchedule, old_value or {})
        elif key == "rss_feeds":
            old_value = _with_live_feed_urls(old_value or [], settings.rss_feeds)
        setattr(settings, key, old_value)
    settings.save()
