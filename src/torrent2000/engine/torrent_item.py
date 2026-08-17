from dataclasses import dataclass, field
from enum import Enum, auto

from torrent2000.danger_scanner.models import ScanResult


class TorrentState(Enum):
    QUEUED = auto()
    CHECKING_METADATA = auto()
    AWAITING_ANALYSIS = auto()
    DOWNLOADING = auto()
    PAUSED = auto()
    SEEDING = auto()
    FINISHED = auto()
    ERROR = auto()

    @staticmethod
    def from_libtorrent_state(lt_state, paused: bool, has_metadata: bool, awaiting_analysis: bool) -> "TorrentState":
        if awaiting_analysis:
            return TorrentState.AWAITING_ANALYSIS
        if not has_metadata:
            return TorrentState.CHECKING_METADATA
        if paused:
            return TorrentState.PAUSED
        name = str(lt_state)
        if "seeding" in name:
            return TorrentState.SEEDING
        if "finished" in name:
            return TorrentState.FINISHED
        return TorrentState.DOWNLOADING


# "Actively downloading" -- still consuming disk space/bandwidth, as opposed
# to paused/seeding/finished/errored torrents that no longer are. Shared by
# engine/auto_shutdown_service.py's idle check and
# engine/disk_space_monitor.py's active-path scan.
ACTIVE_DOWNLOAD_STATES = {
    TorrentState.DOWNLOADING,
    TorrentState.QUEUED,
    TorrentState.CHECKING_METADATA,
}


@dataclass
class TrackerInfo:
    url: str
    tier: int = 0
    last_error: str = ""


@dataclass
class PeerInfo:
    ip: str  # "address:port"
    client: str = ""
    progress: float = 0.0  # 0.0 - 1.0
    down_speed: int = 0  # bytes/sec
    up_speed: int = 0


@dataclass
class TorrentRecord:
    info_hash: str
    name: str = ""
    save_path: str = ""
    total_size: int = 0
    progress: float = 0.0  # 0.0 - 1.0
    download_rate: int = 0  # bytes/sec
    upload_rate: int = 0
    state: TorrentState = TorrentState.QUEUED
    num_peers: int = 0
    num_seeds: int = 0
    total_downloaded: int = 0
    total_uploaded: int = 0
    all_time_downloaded: int = 0
    all_time_uploaded: int = 0
    error: str = ""
    is_magnet_awaiting_metadata: bool = False
    awaiting_analysis: bool = False
    trackers: list[TrackerInfo] = field(default_factory=list)
    current_tracker: str = ""
    file_list: list | None = None
    danger_report: ScanResult | None = None
    sequential_download: bool = False
    queue_position: int = -1
    is_private: bool = False
    category: str = ""
