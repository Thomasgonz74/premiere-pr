import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Resolve a bundled resource path, working both from source and from a
    PyInstaller-frozen executable (sys._MEIPASS extraction dir)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parents[3]
    return base / relative
