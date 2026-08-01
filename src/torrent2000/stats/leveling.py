"""Pure, Qt-free leveling math: level n is reached once the user's weighted
cumulative bytes hit threshold(n) = 1 GiB * 1.4^(n-1). This is an absolute
cumulative threshold (not a summed series of chunks), matching the
requirement's own formula directly.

Uploaded bytes count for *more* than downloaded bytes toward the level
(UPLOAD_LEVEL_WEIGHT): 1 GiB uploaded is worth 1.5 GiB downloaded, to reward
seeding. This weighting applies only to the level/threshold math -- the raw
totals shown in the UI (StatsSnapshot.total_downloaded/total_uploaded) stay
the real, unweighted byte counts.
"""

import math

from torrent2000.stats.models import StatsSnapshot

LEVEL_BASE_BYTES = 1024**3  # 1 GiB
LEVEL_GROWTH = 1.4
UPLOAD_LEVEL_WEIGHT = 1.5


def threshold_for_level(level: int) -> int:
    """Cumulative bytes needed to reach `level`. Level 0 (the starting level,
    before the first 1 GiB milestone) has threshold 0."""
    if level <= 0:
        return 0
    return round(LEVEL_BASE_BYTES * (LEVEL_GROWTH ** (level - 1)))


def level_for_total_bytes(total_bytes: int) -> int:
    if total_bytes < LEVEL_BASE_BYTES:
        return 0
    estimate = int(math.log(total_bytes / LEVEL_BASE_BYTES, LEVEL_GROWTH)) + 1
    # math.log on floats can land one step off right at a threshold boundary;
    # nudge the estimate until it matches exactly.
    while threshold_for_level(estimate + 1) <= total_bytes:
        estimate += 1
    while estimate > 0 and threshold_for_level(estimate) > total_bytes:
        estimate -= 1
    return estimate


def progress_within_level(total_bytes: int) -> float:
    level = level_for_total_bytes(total_bytes)
    lower = threshold_for_level(level)
    upper = threshold_for_level(level + 1)
    if upper <= lower:
        return 1.0
    return max(0.0, min(1.0, (total_bytes - lower) / (upper - lower)))


def weighted_total_bytes(total_downloaded: int, total_uploaded: int) -> int:
    return total_downloaded + round(total_uploaded * UPLOAD_LEVEL_WEIGHT)


def snapshot(total_downloaded: int, total_uploaded: int) -> StatsSnapshot:
    weighted_total = weighted_total_bytes(total_downloaded, total_uploaded)
    level = level_for_total_bytes(weighted_total)
    return StatsSnapshot(
        total_downloaded=total_downloaded,
        total_uploaded=total_uploaded,
        level=level,
        progress_to_next=progress_within_level(weighted_total),
        current_threshold=threshold_for_level(level),
        next_threshold=threshold_for_level(level + 1),
    )
