from dataclasses import dataclass


@dataclass
class StatsSnapshot:
    total_downloaded: int
    total_uploaded: int
    level: int
    progress_to_next: float  # 0.0 - 1.0
    current_threshold: int
    next_threshold: int
