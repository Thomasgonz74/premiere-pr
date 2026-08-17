# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))

a = Analysis(
    [os.path.join(REPO_ROOT, "run.py")],
    pathex=[os.path.join(REPO_ROOT, "src")],
    binaries=[],
    datas=[],
    hiddenimports=["libtorrent"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

# Whole-folder Tree() inclusion so new files dropped into resources/ or assets/
# are picked up automatically, without editing this spec.
a.datas += Tree(os.path.join(REPO_ROOT, "resources"), prefix="resources")
a.datas += Tree(os.path.join(REPO_ROOT, "assets"), prefix="assets")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Torrent2000",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO_ROOT, "assets", "icon.ico"),
)
