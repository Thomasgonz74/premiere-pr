"""Regression guard for reproducible builds.

PySide6 and libtorrent used to be declared with ">=" lower bounds, so
rebuilding an old release later would silently pull whatever is newest at
build time instead of the exact versions the shipped exe was built with.
PyInstaller (a build-only tool, not a runtime dependency) must stay pinned
too, but only inside the optional "build" extra so a plain
"pip install torrent2000" never drags it in.
"""

import tomllib
from pathlib import Path

PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text())


def test_runtime_dependencies_are_exactly_pinned():
    data = _load_pyproject()
    dependencies = data["project"]["dependencies"]
    pinned = {dep.split("==")[0]: dep for dep in dependencies if "==" in dep}
    assert pinned["PySide6"] == "PySide6==6.11.1"
    assert pinned["libtorrent"] == "libtorrent==2.0.13"


def test_pyinstaller_is_pinned_in_build_extra_not_runtime():
    data = _load_pyproject()
    dependencies = data["project"]["dependencies"]
    assert not any("pyinstaller" in dep.lower() for dep in dependencies)
    build_extra = data["project"]["optional-dependencies"]["build"]
    assert build_extra == ["pyinstaller==6.21.0"]
