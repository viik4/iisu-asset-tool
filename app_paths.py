"""Utility module for resolving application paths in both script and frozen modes."""
import sys
from pathlib import Path

# Flag to enable diagnostic output (set to True for debugging path issues)
_DEBUG_PATHS = False


def get_app_dir() -> Path:
    """Get the application's base directory.

    For frozen apps (PyInstaller), this is the directory containing the executable.
    For macOS app bundles, resources are in Contents/MacOS alongside the executable.
    For scripts, this is the script's directory.
    Assets should be placed alongside the executable.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        exe_path = Path(sys.executable)

        # Check if we're in a macOS .app bundle (path contains .app/Contents/MacOS)
        if sys.platform == 'darwin' and '.app/Contents/MacOS' in str(exe_path):
            # Resources are bundled in the same MacOS directory by PyInstaller's COLLECT
            app_dir = exe_path.parent
        else:
            # Windows/Linux - assets are next to the exe
            app_dir = exe_path.parent

        if _DEBUG_PATHS:
            print(f"[app_paths] Frozen mode - executable: {exe_path}")
            print(f"[app_paths] App directory: {app_dir}")
        return app_dir
    else:
        # Running as script - use this file's location
        app_dir = Path(__file__).parent
        if _DEBUG_PATHS:
            print(f"[app_paths] Script mode - app directory: {app_dir}")
        return app_dir


def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to a resource, works for dev and PyInstaller."""
    return get_app_dir() / relative_path


# All paths relative to app directory (next to executable)
def get_templates_dir() -> Path:
    return get_app_dir() / "templates"


def get_borders_dir() -> Path:
    return get_app_dir() / "borders"


def get_fonts_dir() -> Path:
    return get_app_dir() / "fonts"


def get_platform_icons_dir() -> Path:
    return get_app_dir() / "platform_icons"


def get_fallback_icons_dir() -> Path:
    return get_app_dir() / "fallback_icons"


def get_src_dir() -> Path:
    return get_app_dir() / "src"


def get_logo_path() -> Path:
    return get_app_dir() / "logo.png"


def get_theme_path() -> Path:
    return get_app_dir() / "iisu_theme.qss"


def get_config_path() -> Path:
    return get_app_dir() / "config.yaml"


def verify_required_assets() -> dict:
    """Verify that all required asset directories and files exist.

    Returns a dict with 'missing' list and 'found' list for diagnostics.
    """
    required = {
        'templates/iisuTemplates.psd': get_templates_dir() / "iisuTemplates.psd",
        'borders/': get_borders_dir(),
        'fonts/': get_fonts_dir(),
        'platform_icons/': get_platform_icons_dir(),
        'config.yaml': get_config_path(),
    }

    result = {'missing': [], 'found': [], 'app_dir': str(get_app_dir())}

    for name, path in required.items():
        if path.exists():
            result['found'].append(name)
        else:
            result['missing'].append(f"{name} (expected at: {path})")

    return result


def print_asset_diagnostics():
    """Print diagnostic information about asset paths."""
    print("\n=== Asset Path Diagnostics ===")
    print(f"Python executable: {sys.executable}")
    print(f"Frozen: {getattr(sys, 'frozen', False)}")
    print(f"App directory: {get_app_dir()}")

    result = verify_required_assets()
    print(f"\nFound assets ({len(result['found'])}):")
    for item in result['found']:
        print(f"  [OK] {item}")

    if result['missing']:
        print(f"\nMissing assets ({len(result['missing'])}):")
        for item in result['missing']:
            print(f"  [MISSING] {item}")
    else:
        print("\nAll required assets found!")
    print("=" * 30 + "\n")
