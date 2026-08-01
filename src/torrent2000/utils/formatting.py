_UNITS = ("o", "Ko", "Mo", "Go", "To")


def human_size(num_bytes: float) -> str:
    value = float(num_bytes)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            if unit == "o":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} {_UNITS[-1]}"


def human_rate(bytes_per_sec: float) -> str:
    return f"{human_size(bytes_per_sec)}/s"


def human_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "—"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def human_percent(progress: float) -> str:
    return f"{progress * 100:.1f}%"
