# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Minimal build - assets are distributed alongside the executable by GitHub Actions
a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],  # No bundled assets - they go next to the executable
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'PIL',
        'PIL._imagingtk',
        'PIL._tkinter_finder',
        'PIL.ImageQt',
        'psd_tools',
        'psd_tools.psd',
        'psd_tools.psd.layer_and_mask',
        'yaml',
        'requests',
        'numpy',
        'cv2',
        'imagehash',
        'bs4',
        'tqdm',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='iiSU_Asset_Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX for reliability
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.png' if os.path.exists('logo.png') else None,
)
