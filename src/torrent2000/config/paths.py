import os
import subprocess
from pathlib import Path


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
    just_created = not app_dir.exists()
    app_dir.mkdir(parents=True, exist_ok=True)
    if just_created:
        _lock_down_acl(app_dir)
    return app_dir


def get_resume_dir() -> Path:
    resume_dir = get_app_data_dir() / "resume"
    resume_dir.mkdir(parents=True, exist_ok=True)
    return resume_dir


def get_logs_dir() -> Path:
    logs_dir = get_app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_config_path() -> Path:
    return get_app_data_dir() / "config.json"


def get_config_backups_dir() -> Path:
    backups_dir = get_app_data_dir() / "config_backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
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
