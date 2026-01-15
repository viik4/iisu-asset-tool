#!/usr/bin/env python3
"""
Launcher for iiSU Icon Generator GUI.
"""
import sys
import os
from pathlib import Path


def get_app_dir() -> Path:
    """Get the application's base directory.

    Works correctly for:
    - Running as script: returns the script's directory
    - Running as PyInstaller bundle: returns the directory containing the executable
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable (PyInstaller)
        return Path(sys.executable).parent
    else:
        # Running as script
        return Path(__file__).parent


def setup_working_directory():
    """Set the working directory to the application's base directory.

    This ensures relative paths in config.yaml resolve correctly
    whether running as script or compiled executable.
    """
    app_dir = get_app_dir()
    os.chdir(app_dir)
    print(f"Working directory set to: {app_dir}")


if __name__ == "__main__":
    # Set working directory before importing other modules
    setup_working_directory()

    # Print asset diagnostics to help debug path issues
    from app_paths import print_asset_diagnostics
    print_asset_diagnostics()

    from ui_app_with_tabs import main
    main()
