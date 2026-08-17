"""Persists a user-assigned category/label per torrent (info_hash -> category
name), independent of libtorrent's own resume data -- categories are a pure
UI/organizational concept libtorrent has no notion of.

Writes are synchronous (unlike ShareLimitService's debounced saves): category
changes are rare, deliberate user actions (assign a label from a menu), not a
high-frequency stream of status-tick updates, so there's no burst to coalesce.
"""

import json
import os

from torrent2000.config.paths import get_categories_path


class TorrentCategoryService:
    def __init__(self) -> None:
        self._categories: dict[str, str] = {}
        self._load()

    def set(self, info_hash: str, category: str) -> None:
        self._categories[info_hash] = category
        self._save()

    def get(self, info_hash: str) -> str:
        return self._categories.get(info_hash, "")

    def remove(self, info_hash: str) -> None:
        if self._categories.pop(info_hash, None) is not None:
            self._save()

    def all(self) -> dict[str, str]:
        return dict(self._categories)

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_categories_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._categories, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_categories_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(data, dict):
            self._categories = {str(k): str(v) for k, v in data.items()}
