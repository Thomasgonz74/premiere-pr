import contextlib
import ctypes
import glob
import os
import re
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDir
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from torrent2000.ui.theme.theme_manager import _APPEARANCE_SUFFIX, _QSS_BASENAMES

QSS_FILES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "resources", "styles", "*.qss")))
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")

CURSOR_RULE_RE = re.compile(r"cursor:\s*url\(theme:([^)]+)\)\s*(\d+)\s+(\d+)\s*;")


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@contextlib.contextmanager
def _captured_stderr():
    """Qt's stylesheet parser warns via qWarning, which writes to the C
    stdio stderr fd directly -- redirecting sys.stderr alone would miss it,
    so the real fd is what gets swapped. Yields a zero-arg callable that
    returns the captured text once the block exits (the underlying temp
    file is closed at that point, so it can't be read lazily)."""
    fd = 2
    saved_fd = os.dup(fd)
    tmp = tempfile.TemporaryFile(mode="w+b")
    os.dup2(tmp.fileno(), fd)
    captured = {}
    try:
        yield lambda: captured["text"]
    finally:
        if os.name == "nt":
            ctypes.windll.msvcrt._flushall()
        os.dup2(saved_fd, fd)
        os.close(saved_fd)
        tmp.seek(0)
        captured["text"] = tmp.read().decode(errors="replace")
        tmp.close()


@pytest.mark.parametrize("path", QSS_FILES, ids=[os.path.basename(p) for p in QSS_FILES])
def test_qss_file_parses_without_warning(qapp, path):
    text = open(path, encoding="utf-8").read()
    with _captured_stderr() as get_output:
        qapp.setStyleSheet(text)
    output = get_output()
    assert "Could not parse stylesheet" not in output, output
    qapp.setStyleSheet("")


def test_all_21_theme_variant_files_exist():
    expected = {f"{basename}{suffix}.qss" for basename in _QSS_BASENAMES.values() for suffix in _APPEARANCE_SUFFIX.values()}
    actual = {os.path.basename(p) for p in QSS_FILES}
    assert expected <= actual


@pytest.mark.parametrize("path", QSS_FILES, ids=[os.path.basename(p) for p in QSS_FILES])
def test_qss_file_has_focus_and_tooltip_rules(path):
    text = open(path, encoding="utf-8").read()
    assert ":focus" in text, f"{path} is missing any :focus rule (audit finding: no theme indicates keyboard focus)"
    assert "QToolTip" in text, f"{path} is missing a QToolTip rule"


@pytest.mark.parametrize("path", QSS_FILES, ids=[os.path.basename(p) for p in QSS_FILES])
def test_qss_file_references_its_theme_cursor(path):
    """Every theme wires up its own hand-drawn assets/cursors/<theme>/arrow.png
    (see CHARTER notes / harmonization report) via `cursor: url(theme:cursors/...)`.
    Cheap substring check -- not about whether the QSS `cursor` property actually
    repaints the pointer at runtime (verified separately: it doesn't, in this
    Qt/PySide6 build -- see test_theme_cursor_assets_exist_and_are_well_formed
    below and the harmonization report) -- just that a future edit can't silently
    drop a theme's cursor declaration without a test noticing."""
    text = open(path, encoding="utf-8").read()
    assert "cursor: url(theme:cursors/" in text, (
        f"{path} has no 'cursor: url(theme:cursors/...)' rule -- this theme lost its custom cursor"
    )


@pytest.mark.parametrize("path", QSS_FILES, ids=[os.path.basename(p) for p in QSS_FILES])
def test_theme_cursor_assets_exist_and_are_well_formed(qapp, path):
    """Every `cursor: url(theme:cursors/<theme>/arrow.png) x y;` rule must
    resolve to a real, non-empty, non-null-pixmap asset with a hotspot that
    actually lands inside the image -- catches a theme referencing a PNG
    that was never committed, or a hotspot typo pointing off-canvas."""
    text = open(path, encoding="utf-8").read()
    matches = CURSOR_RULE_RE.findall(text)
    assert matches, f"{path}: no cursor: url(theme:...) rule found"

    if not QDir.searchPaths("theme"):
        QDir.addSearchPath("theme", ASSETS_DIR)

    for rel_path, hot_x, hot_y in matches:
        asset_path = os.path.join(ASSETS_DIR, *rel_path.split("/"))
        assert os.path.isfile(asset_path), f"{path}: missing cursor asset {asset_path}"
        assert os.path.getsize(asset_path) > 0, f"{path}: cursor asset {asset_path} is empty"

        pixmap = QPixmap(f"theme:{rel_path}")
        assert not pixmap.isNull(), f"{path}: theme:{rel_path} failed to load as a pixmap"

        hot_x, hot_y = int(hot_x), int(hot_y)
        assert 0 <= hot_x < pixmap.width(), f"{path}: hotspot x={hot_x} outside {pixmap.width()}px-wide {rel_path}"
        assert 0 <= hot_y < pixmap.height(), f"{path}: hotspot y={hot_y} outside {pixmap.height()}px-tall {rel_path}"


@pytest.mark.parametrize("path", QSS_FILES, ids=[os.path.basename(p) for p in QSS_FILES])
def test_qcombobox_popup_selection_is_actually_visible(qapp, path):
    """Regression test for a real (not theoretical) bug found by rendering
    each theme's QComboBox popup offscreen: on some themes, if
    `selection-background-color` is declared only on
    `QComboBox QAbstractItemView` and not on `QComboBox` itself, Qt silently
    fails to paint any highlight at all on the row matching the combo's
    current value when the popup first opens -- the win10 and win95
    families had exactly this gap (win7's QSS already documents having
    bisected and fixed the same issue for itself; cccp and win11 render
    fine without the extra declaration, so this isn't required of every
    theme -- only that the highlight actually renders, one way or another).
    This renders the real popup pixmap and asserts the declared highlight
    color is actually present in it, rather than trusting a declaration.
    """
    text = open(path, encoding="utf-8").read()
    stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    sel_match = None
    for rule_selector in (r"QComboBox\s*\{", r"QComboBox\s+QAbstractItemView\s*\{"):
        m = re.search(rule_selector + r"([^{}]*)\}", stripped)
        if m:
            sel_match = re.search(r"selection-background-color\s*:\s*([^;]+);", m.group(1))
            if sel_match:
                break
    assert sel_match, (
        f"{path} declares no selection-background-color on QComboBox or its popup view -- "
        "without it, the popup's currently-selected row can open with no visible highlight"
    )
    target = QColor(sel_match.group(1).strip())
    assert target.isValid()

    qapp.setStyleSheet(text)
    host = QWidget()
    host.resize(300, 100)
    combo = QComboBox(host)
    combo.addItems(["Alpha item", "Beta item", "Gamma item"])
    combo.setCurrentIndex(1)
    combo.resize(220, 30)
    host.show()
    combo.show()
    combo.showPopup()
    popup = combo.view().window()
    qapp.processEvents()
    img = popup.grab().toImage()

    found = any(
        abs(img.pixelColor(x, y).red() - target.red()) <= 3
        and abs(img.pixelColor(x, y).green() - target.green()) <= 3
        and abs(img.pixelColor(x, y).blue() - target.blue()) <= 3
        for y in range(img.height())
        for x in range(0, img.width(), 2)
    )

    combo.hidePopup()
    host.close()
    qapp.setStyleSheet("")

    assert found, (
        f"{path}: declared selection-background-color {sel_match.group(1).strip()} "
        "never appears in the rendered popup -- the current row's highlight is invisible"
    )
