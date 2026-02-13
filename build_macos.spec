# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all psd_tools submodules to ensure PSD loading works
psd_tools_imports = collect_submodules('psd_tools')

# Collect psd_tools data files (if any)
psd_tools_datas = collect_data_files('psd_tools')

# Bundle internal resources that are extracted by PyInstaller
# User-modifiable files (config, borders, templates) should be copied alongside the app
a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        entry for entry in [
            # Theme and styling
            ('iisu_theme.qss', '.'),
            ('iisu_theme_light.qss', '.'),
            # Logo
            ('logo.png', '.'),
            # Configuration
            ('config.yaml', '.'),
            # Fonts directory
            ('fonts', 'fonts'),
            # Source assets (icons, grid pattern)
            ('src', 'src'),
            # Platform icons
            ('platform_icons', 'platform_icons'),
            # Fallback icons
            ('fallback_icons', 'fallback_icons'),
            # Border templates
            ('borders', 'borders'),
            # PSD templates
            ('templates', 'templates'),
        ] if os.path.exists(entry[0])
    ] + psd_tools_datas,  # Include psd_tools data files
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
    [],
    exclude_binaries=True,
    name='iiSU_Asset_Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX can corrupt macOS binaries, especially on arm64
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # UPX can corrupt macOS binaries
    upx_exclude=[],
    name='iiSU_Asset_Tool',
)

app = BUNDLE(
    coll,
    name='iiSU Asset Tool.app',
    # Note: macOS requires .icns format for app icons. The icon is set by the CI/CD workflow
    # which creates app_icon.icns from logo.png using iconutil, then injects it into the bundle.
    icon=None,
    bundle_identifier='com.iisu.assettool',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleDocumentTypes': [],
        'CFBundleShortVersionString': '1.3.0',
        'CFBundleVersion': '1.3.0',
        # Icon will be set by the workflow post-build
        'CFBundleIconFile': 'app_icon',
    },
)
