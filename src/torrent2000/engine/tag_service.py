"""Persists user-assigned free-form tags per torrent (info_hash -> list of
tag strings), independent of libtorrent's own resume data -- same "pure
UI/organizational concept" as engine/torrent_categories.py, whose exact
persistence pattern this mirrors, just with multiple tags per torrent
instead of a single category.

Writes are synchronous (unlike ShareLimitService's debounced saves): tag
changes are rare, deliberate user actions, not a high-frequency stream of
status-tick updates, so there's no burst to coalesce.
"""

import json
import os

from torrent2000.config.paths import get_tags_path


class TagService:
    def __init__(self) -> None:
        self._tags: dict[str, list[str]] = {}
        self._load()

    def add(self, info_hash: str, tag: str) -> None:
        tag = tag.strip()
        if not tag:
            return
        existing = self._tags.setdefault(info_hash, [])
        if tag not in existing:
            existing.append(tag)
            self._save()

    def remove(self, info_hash: str, tag: str) -> None:
        existing = self._tags.get(info_hash)
        if existing is None or tag not in existing:
            return
        existing.remove(tag)
        if not existing:
            del self._tags[info_hash]
        self._save()

    def get(self, info_hash: str) -> list[str]:
        return list(self._tags.get(info_hash, []))

    def all_tags(self) -> list[str]:
        """Every distinct tag currently in use, across all torrents --
        sorted, for a stable filter-dropdown/autocomplete order."""
        return sorted({tag for tags in self._tags.values() for tag in tags})

    def clear(self, info_hash: str) -> None:
        if self._tags.pop(info_hash, None) is not None:
            self._save()

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_tags_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._tags, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_tags_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return
        loaded: dict[str, list[str]] = {}
        for info_hash, tags in data.items():
            if isinstance(tags, list):
                loaded[str(info_hash)] = [str(t) for t in tags]
        self._tags = loaded
