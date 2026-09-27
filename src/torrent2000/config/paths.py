import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

_T = TypeVar("_T")

# Folders already created (or found) this run. Each getter below used to redo
# exists() + mkdir() on every call -- ~0.7-1.2 ms per state write (~27 % of a
# .fastresume write). Keyed by absolute path (os.path.abspath is string-only,
# unlike Path.resolve() which hits the disk) because TORRENT2000_DATA_DIR
# changes between test cases. Only resume/ and config_backups/ can vanish
# while the app runs (the root and logs/ hold open SQLite/log handles that
# Windows refuses to delete), so their write sites go through
# retry_if_dir_vanished().
_ensured_dirs: set[str] = set()


def _ensure_dir(path: Path) -> bool:
    """mkdir -p `path` once per run; True if it did not exist before."""
    key = os.path.abspath(path)
    if key in _ensured_dirs:
        return False
    just_created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    _ensured_dirs.add(key)
    return just_created


def retry_if_dir_vanished(write: Callable[[], _T]) -> _T:
    """Runs write() -- which must call the path getter itself -- and, if a
    memoised folder was deleted underneath it (FileNotFoundError), forgets
    every memoised folder and runs it once more so the getter recreates it."""
    try:
        return write()
    except FileNotFoundError:
        _ensured_dirs.clear()
        return write()


def _lock_down_acl(path: Path) -> None:
    """Best-effort NTFS ACL lockdown for a freshly-created app data
    directory -- restricts access to the current user + SYSTEM, replacing
    whatever broader access it inherited from its parent (relevant on a
    machine shared between multiple Windows accounts; this directory holds
    config.json, resume data, and the sqlite stores). Never raises: a
    failure here (e.g. running outside Windows, icacls missing) must never
    block the app from starting."""
    username = os.environ.get("USERNAME", "")
    if not username:
        return
    try:
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{username}:(OI)(CI)F",
                "/grant:r",
                "SYSTEM:(OI)(CI)F",
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def get_app_data_dir() -> Path:
    override = os.environ.get("TORRENT2000_DATA_DIR")
    if override:
        app_dir = Path(override)
    else:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        app_dir = Path(base) / "Torrent2000"
    if _ensure_dir(app_dir):
        _lock_down_acl(app_dir)
    return app_dir


def get_resume_dir() -> Path:
    resume_dir = get_app_data_dir() / "resume"
    _ensure_dir(resume_dir)
    return resume_dir


def get_logs_dir() -> Path:
    logs_dir = get_app_data_dir() / "logs"
    _ensure_dir(logs_dir)
    return logs_dir


def get_config_path() -> Path:
    return get_app_data_dir() / "config.json"


def get_config_backups_dir() -> Path:
    backups_dir = get_app_data_dir() / "config_backups"
    _ensure_dir(backups_dir)
    return backups_dir


def get_stats_db_path() -> Path:
    return get_app_data_dir() / "stats.sqlite3"


def get_history_db_path() -> Path:
    return get_app_data_dir() / "history.sqlite3"


def get_session_state_path() -> Path:
    return get_app_data_dir() / "session_state.bin"


def get_rss_seen_db_path() -> Path:
    return get_app_data_dir() / "rss_seen.sqlite3"


def get_share_limits_path() -> Path:
    return get_app_data_dir() / "share_limits.json"


def get_categories_path() -> Path:
    return get_config_path().parent / "categories.json"


def get_tags_path() -> Path:
    return get_config_path().parent / "tags.json"


def get_torrent_search_sources_path() -> Path:
    return get_config_path().parent / "torrent_search_sources.json"


def get_settings_profiles_path() -> Path:
    return get_config_path().parent / "settings_profiles.json"


def get_routing_rules_path() -> Path:
    return get_config_path().parent / "routing_rules.json"


def get_known_disks_path() -> Path:
    return get_config_path().parent / "known_disks.json"


def get_network_profiles_path() -> Path:
    return get_config_path().parent / "network_profiles.json"


def get_peer_reputation_path() -> Path:
    return get_config_path().parent / "peer_reputation.json"


def get_lan_peer_cache_path() -> Path:
    return get_config_path().parent / "lan_peer_cache.json"


def get_decision_journal_path() -> Path:
    return get_config_path().parent / "decision_journal.jsonl"


def get_default_download_dir() -> Path:
    downloads = Path.home() / "Downloads" / "Torrent2000"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads
