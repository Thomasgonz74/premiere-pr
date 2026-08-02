"""Pure, Qt-free leveling math: level n is reached once the user's weighted
cumulative bytes hit threshold(n) = 1 GiB * 1.4^(n-1). This is an absolute
cumulative threshold (not a summed series of chunks), matching the
requirement's own formula directly.

Uploaded bytes count for *more* than downloaded bytes toward the level
(UPLOAD_LEVEL_WEIGHT): 1 GiB uploaded is worth 1.5 GiB downloaded, to reward
seeding. This weighting applies only to the level/threshold math -- the raw
totals shown in the UI (StatsSnapshot.total_downloaded/total_uploaded) stay
the real, unweighted byte counts.

Some graphical themes (see theme_ids.py) are also silly gameplay skins: the
macOS theme halves both scores, and the CCCP theme triples the upload one
(and blocks downloading outright -- enforced in engine/session_manager.py,
not here). These per-theme factors REPLACE the baseline (1.0, 1.5) pair --
they are absolute multipliers on raw bytes, not stacked on top of
UPLOAD_LEVEL_WEIGHT -- and apply live to the whole current total rather than
being baked permanently into history, the same way UPLOAD_LEVEL_WEIGHT
itself already works: switching themes immediately (and reversibly)
rescales the displayed level, it doesn't rewrite what was already earned.
"""

import math
from typing import Optional

from torrent2000.stats.models import StatsSnapshot
from torrent2000.theme_ids import CCCP_THEME_ID, MACOS_THEME_ID

LEVEL_BASE_BYTES = 1024**3  # 1 GiB
LEVEL_GROWTH = 1.4
UPLOAD_LEVEL_WEIGHT = 1.5

# (download_factor, upload_factor) -- absolute multipliers on raw bytes,
# keyed by theme id. Themes not listed here use the baseline pair below.
_THEME_SCORE_FACTORS = {
    MACOS_THEME_ID: (0.5, UPLOAD_LEVEL_WEIGHT * 0.5),
    # Download factor is moot -- CCCP torrents can't be downloading in the
    # first place -- but kept at the baseline rather than 0 so a torrent
    # that finished downloading under a different theme still shows its
    # earned download score honestly instead of being zeroed retroactively.
    CCCP_THEME_ID: (1.0, 3.0),
}


def score_factors_for(theme_id: Optional[str]) -> tuple[float, float]:
    return _THEME_SCORE_FACTORS.get(theme_id, (1.0, UPLOAD_LEVEL_WEIGHT))


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


def weighted_total_bytes(
    total_downloaded: int,
    total_uploaded: int,
    download_factor: float = 1.0,
    upload_factor: float = UPLOAD_LEVEL_WEIGHT,
) -> int:
    return round(total_downloaded * download_factor) + round(total_uploaded * upload_factor)


def snapshot(
    total_downloaded: int,
    total_uploaded: int,
    download_factor: float = 1.0,
    upload_factor: float = UPLOAD_LEVEL_WEIGHT,
) -> StatsSnapshot:
    weighted_total = weighted_total_bytes(total_downloaded, total_uploaded, download_factor, upload_factor)
    level = level_for_total_bytes(weighted_total)
    return StatsSnapshot(
        total_downloaded=total_downloaded,
        total_uploaded=total_uploaded,
        level=level,
        progress_to_next=progress_within_level(weighted_total),
        current_threshold=threshold_for_level(level),
        next_threshold=threshold_for_level(level + 1),
    )
