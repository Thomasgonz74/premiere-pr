import os
from pathlib import Path


def get_app_data_dir() -> Path:
    override = os.environ.get("TORRENT2000_DATA_DIR")
    if override:
        app_dir = Path(override)
    else:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        app_dir = Path(base) / "Torrent2000"
    app_dir.mkdir(parents=True, exist_ok=True)
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


def get_settings_profiles_path() -> Path:
    return get_config_path().parent / "settings_profiles.json"


def get_routing_rules_path() -> Path:
    return get_config_path().parent / "routing_rules.json"


def get_default_download_dir() -> Path:
    downloads = Path.home() / "Downloads" / "Torrent2000"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads
