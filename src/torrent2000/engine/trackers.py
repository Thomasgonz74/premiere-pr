"""Manual, user-driven tracker list editing.

This module intentionally offers only direct, button-triggered operations
(read the current list / add one / remove one). There is no timer, no
progress-triggered automation, and no attempt to defeat private-tracker
ratio enforcement -- it is a plain metadata editor equivalent to the
"trackers" tab already found in clients like qBittorrent or Deluge.
"""

import libtorrent as lt

from torrent2000.engine.torrent_item import TrackerInfo


def get_trackers(handle: "lt.torrent_handle") -> list[TrackerInfo]:
    result = []
    for entry in handle.trackers():
        error_value = (entry.get("last_error") or {}).get("value", 0)
        result.append(
            TrackerInfo(
                url=entry.get("url", ""),
                tier=entry.get("tier", 0),
                last_error=entry.get("message", "") if error_value else "",
            )
        )
    return result


def add_tracker(handle: "lt.torrent_handle", url: str, tier: int = 0) -> None:
    handle.add_tracker({"url": url, "tier": tier})


def remove_tracker(handle: "lt.torrent_handle", url: str) -> None:
    remaining = [entry for entry in handle.trackers() if entry.get("url") != url]
    handle.replace_trackers(remaining)
