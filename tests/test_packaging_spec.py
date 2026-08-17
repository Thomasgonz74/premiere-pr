"""Guards against the packaging spec regressing to per-extension datas globs.

Torrent2000.spec must embed resources/ and assets/ as whole folders (via
PyInstaller's Tree()) so a file dropped into an existing folder, or a new
top-level file under assets/, is bundled automatically -- no .spec edit
needed. These tests exercise the real Tree() mechanism the .spec uses,
not a mock of it.
"""

import os

import pytest

PyInstaller = pytest.importorskip("PyInstaller")

from PyInstaller.config import CONF  # noqa: E402
from PyInstaller.building.datastruct import Tree  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SPEC_PATH = os.path.join(REPO_ROOT, "packaging", "torrent2000.spec")


@pytest.fixture
def pyinstaller_workpath(tmp_path):
    previous = CONF.get("workpath")
    CONF["workpath"] = str(tmp_path)
    yield tmp_path
    if previous is None:
        CONF.pop("workpath", None)
    else:
        CONF["workpath"] = previous


def test_spec_uses_tree_not_per_extension_globs():
    spec_source = open(SPEC_PATH, encoding="utf-8").read()

    assert "Tree(" in spec_source
    assert 'prefix="resources"' in spec_source
    assert 'prefix="assets"' in spec_source

    for pattern in ("*.qss", "*.json", "*.mp3", "*.png", "*.ico"):
        assert pattern not in spec_source, (
            f"spec re-introduced a per-extension glob ({pattern!r}); "
            "new resource/asset files would silently drop out of the build"
        )


def test_tree_auto_includes_new_file_in_existing_subfolder(tmp_path, pyinstaller_workpath):
    root = tmp_path / "resources"
    (root / "styles").mkdir(parents=True)
    (root / "styles" / "win95.qss").write_text("body {}")

    before = {name for name, _src, _typecode in Tree(str(root), prefix="resources")}
    assert os.path.join("resources", "styles", "win95.qss") in before

    (root / "styles" / "new_theme.wav").write_bytes(b"\x00")

    after = {name for name, _src, _typecode in Tree(str(root), prefix="resources")}
    assert os.path.join("resources", "styles", "new_theme.wav") in after


def test_tree_auto_includes_new_top_level_file_in_assets(tmp_path, pyinstaller_workpath):
    root = tmp_path / "assets"
    root.mkdir()
    (root / "icon.ico").write_bytes(b"\x00")

    (root / "tray_icon.png").write_bytes(b"\x00")

    entries = {name for name, _src, _typecode in Tree(str(root), prefix="assets")}
    assert os.path.join("assets", "icon.ico") in entries
    assert os.path.join("assets", "tray_icon.png") in entries


def test_tree_over_real_repo_folders_includes_known_files(pyinstaller_workpath):
    resources_entries = {
        name for name, _src, _typecode in Tree(os.path.join(REPO_ROOT, "resources"), prefix="resources")
    }
    assets_entries = {
        name for name, _src, _typecode in Tree(os.path.join(REPO_ROOT, "assets"), prefix="assets")
    }

    assert os.path.join("resources", "i18n", "en.json") in resources_entries
    assert os.path.join("resources", "styles", "cccp.qss") in resources_entries
    assert os.path.join("assets", "icon.ico") in assets_entries
    assert os.path.join("assets", "checkmark.png") in assets_entries
    assert os.path.join("assets", "audio", "cccp_anthem.mp3") in assets_entries
