# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all psd_tools submodules to ensure PSD loading works
psd_tools_imports = collect_submodules('psd_tools')

# Collect psd_tools data files (if any)
psd_tools_datas = collect_data_files('psd_tools')

# Minimal build - assets are distributed alongside the executable by GitHub Actions
a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=psd_tools_datas,  # Include psd_tools data files
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'PIL',
        'PIL.ImageQt',
        'yaml',
        'requests',
        'numpy',
        'cv2',
        'imagehash',
        'bs4',
        'tqdm',
        'aggdraw',  # Required by psd_tools for vector shape rendering
    ] + psd_tools_imports,  # Add all psd_tools submodules
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        '_tkinter',
        'PIL._imagingtk',
        'PIL._tkinter_finder',
    ],
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
