# -*- mode: python ; coding: utf-8 -*-
# Production build: run_web_spike.py (QWebEngineView/CSS app), --onedir.
# Replaces the old native Qt/QSS app (run.py, retired) as of the web-UI
# cutover. Slimming logic (excludes, locale filter, debug.pak/bin strip)
# carried over unchanged from the retired packaging/torrent2000_spike.spec
# validation build.
import os

block_cipher = None

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))

a = Analysis(
    [os.path.join(REPO_ROOT, "run_web_spike.py")],
    pathex=[os.path.join(REPO_ROOT, "src")],
    binaries=[],
    datas=[],
    hiddenimports=["libtorrent"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuick3D",
        "PySide6.QtQuick3DRuntimeRender",
        "PySide6.QtCharts",
        "PySide6.QtGraphs",
        "PySide6.QtDataVisualization",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DExtras",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtBluetooth",
        # QtMultimedia/QtMultimediaWidgets: NOT excluded -- AnthemPlayer
        # (engine/anthem_player.py) needs QMediaPlayer/QAudioOutput.
        "PySide6.QtSensors",
        "PySide6.QtNfc",
        "PySide6.QtRemoteObjects",
        "PySide6.QtSerialPort",
        "PySide6.QtSerialBus",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtStateMachine",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtTest",
        "PySide6.QtXml",
        "PySide6.QtHelp",
        "PySide6.QtDesigner",
        "PySide6.QtUiTools",
        "PySide6.QtPdfWidgets",
    ],
    noarchive=False,
    cipher=block_cipher,
)

# Whole-folder Tree() inclusion so new files dropped into resources/ or
# assets/ are picked up automatically, without editing this spec.
a.datas += Tree(os.path.join(REPO_ROOT, "resources"), prefix="resources")
a.datas += Tree(os.path.join(REPO_ROOT, "assets"), prefix="assets")

# QtWebEngine ships 53 locale .pak files; keep only the ones matching the
# app's own i18n catalog (src/torrent2000/i18n/translator.py LANGUAGE_LABELS)
# -- 44MB -> ~10MB, pure data files, never linked as DLL dependencies.
_KEEP_LOCALES = {
    "fr", "en-US", "en-GB", "es", "es-419", "de", "pt-BR", "pt-PT",
    "it", "zh-CN", "zh-TW", "ja", "ko", "pl", "ru",
}


def _keep_datum(entry):
    dest = entry[0].replace("\\", "/")
    if dest.endswith(".debug.pak") or dest.endswith(".debug.bin"):
        # Unused *.debug.pak/*.debug.bin duplicates PyInstaller's QtWebEngine
        # hook bundles unconditionally (~78MB measured, never read at runtime).
        return False
    if "qtwebengine_locales" not in dest:
        return True
    name = os.path.splitext(os.path.basename(dest))[0]
    return name in _KEEP_LOCALES


a.datas = [d for d in a.datas if _keep_datum(d)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Torrent2000",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO_ROOT, "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Torrent2000",
)
