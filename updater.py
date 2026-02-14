"""
In-App Updater for iiSU Asset Tool (Desktop)
Checks GitHub Releases for new versions and handles download + apply.
"""
import sys
import os
import json
import zipfile
import tarfile
import shutil
import subprocess
import tempfile
import stat
import urllib.request
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Callable
from datetime import datetime, timezone


GITHUB_OWNER = "viik4"
GITHUB_REPO = "iisu-asset-tool"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# Map sys.platform to expected release asset names
PLATFORM_ASSETS = {
    "win32": "iiSU_Asset_Tool_Windows.zip",
    "linux": "iiSU_Asset_Tool_Linux.tar.gz",
    "darwin": "iiSU_Asset_Tool_macOS.dmg",
}

CHECK_INTERVAL_SECONDS = 3600  # 1 hour


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    is_update_available: bool
    changelog: str
    download_url: str
    download_size: int
    asset_name: str
    release_url: str


def version_compare(v1: str, v2: str) -> int:
    """Compare two version strings. Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2."""
    try:
        parts1 = [int(x) for x in v1.strip().lstrip("v").split(".")]
        parts2 = [int(x) for x in v2.strip().lstrip("v").split(".")]
    except ValueError:
        return 0
    for a, b in zip(parts1, parts2):
        if a < b:
            return -1
        if a > b:
            return 1
    if len(parts1) < len(parts2):
        return -1
    if len(parts1) > len(parts2):
        return 1
    return 0


def check_for_updates(current_version: str) -> Optional[UpdateInfo]:
    """
    Check GitHub Releases for a newer version.
    Returns UpdateInfo if an update is available, None if up-to-date or on error.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"iiSU-Asset-Tool/{current_version}",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "")
        latest_version = tag.lstrip("v")
        changelog = data.get("body", "") or ""
        release_url = data.get("html_url", "")

        is_update = version_compare(current_version, latest_version) < 0

        # Find the right asset for this platform
        platform_asset_name = PLATFORM_ASSETS.get(sys.platform)
        download_url = ""
        download_size = 0
        asset_name = platform_asset_name or ""

        if platform_asset_name:
            for asset in data.get("assets", []):
                if asset.get("name") == platform_asset_name:
                    download_url = asset.get("browser_download_url", "")
                    download_size = asset.get("size", 0)
                    break

        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_version,
            is_update_available=is_update,
            changelog=changelog,
            download_url=download_url,
            download_size=download_size,
            asset_name=asset_name,
            release_url=release_url,
        )
    except Exception as e:
        print(f"[Updater] Check failed: {e}")
        return None


def download_update(
    update_info: UpdateInfo,
    dest_dir: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Optional[Path]:
    """
    Download the update artifact to dest_dir.
    progress_callback receives (bytes_downloaded, total_bytes).
    Returns path to downloaded file, or None on error.
    """
    if not update_info.download_url:
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / update_info.asset_name

    def reporthook(block_num, block_size, total_size):
        if progress_callback:
            downloaded = block_num * block_size
            total = total_size if total_size > 0 else update_info.download_size
            progress_callback(min(downloaded, total), total)

    try:
        req = urllib.request.Request(
            update_info.download_url,
            headers={"User-Agent": f"iiSU-Asset-Tool/{update_info.current_version}"},
        )
        urllib.request.urlretrieve(update_info.download_url, str(dest_file), reporthook=reporthook)
        return dest_file
    except Exception as e:
        print(f"[Updater] Download failed: {e}")
        # Clean up partial download
        if dest_file.exists():
            try:
                dest_file.unlink()
            except OSError:
                pass
        return None


def apply_update(archive_path: Path, app_dir: Path) -> bool:
    """
    Extract the update archive and prepare a swap script.
    On macOS, opens the DMG in Finder instead.
    Returns True if ready for restart.
    """
    staging_dir = app_dir / "_update_staging"

    # Clean any previous staging
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        # macOS: just open the DMG, user handles it
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(archive_path)])
            return True

        # Extract archive
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(staging_dir)
        elif archive_path.name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(staging_dir)
        else:
            print(f"[Updater] Unknown archive format: {archive_path.name}")
            return False

        # Find the extracted content directory
        # Archives typically contain a top-level folder like "iiSU_Asset_Tool/"
        extracted_items = list(staging_dir.iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            content_dir = extracted_items[0]
        else:
            content_dir = staging_dir

        # Generate swap script
        if sys.platform == "win32":
            return _generate_windows_script(content_dir, app_dir, staging_dir)
        else:
            return _generate_linux_script(content_dir, app_dir, staging_dir)

    except Exception as e:
        print(f"[Updater] Apply failed: {e}")
        return False


def _generate_windows_script(content_dir: Path, app_dir: Path, staging_dir: Path) -> bool:
    """Generate a .bat script to swap files on Windows."""
    exe_name = Path(sys.executable).name
    script_path = staging_dir / "_apply_update.bat"

    script = f"""@echo off
echo Applying update...
timeout /t 3 /nobreak >nul

rem Copy new files over the app directory
xcopy /s /e /y "{content_dir}\\*" "{app_dir}\\" >nul 2>&1

rem Restart the app
start "" "{app_dir / exe_name}"

rem Clean up staging
timeout /t 2 /nobreak >nul
rmdir /s /q "{staging_dir}"
"""
    script_path.write_text(script, encoding="utf-8")
    return True


def _generate_linux_script(content_dir: Path, app_dir: Path, staging_dir: Path) -> bool:
    """Generate a .sh script to swap files on Linux."""
    exe_name = Path(sys.executable).name
    script_path = staging_dir / "_apply_update.sh"

    script = f"""#!/bin/bash
echo "Applying update..."
sleep 3

# Copy new files over the app directory
cp -rf "{content_dir}/"* "{app_dir}/"

# Make executable
chmod +x "{app_dir / exe_name}"

# Restart the app
nohup "{app_dir / exe_name}" &>/dev/null &

# Clean up staging
sleep 2
rm -rf "{staging_dir}"
"""
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
    return True


def launch_swap_and_exit(app_dir: Path):
    """Launch the swap script and exit the application."""
    staging_dir = app_dir / "_update_staging"

    if sys.platform == "win32":
        script_path = staging_dir / "_apply_update.bat"
        if script_path.exists():
            subprocess.Popen(
                ["cmd", "/c", str(script_path)],
                cwd=str(staging_dir),
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
    else:
        script_path = staging_dir / "_apply_update.sh"
        if script_path.exists():
            subprocess.Popen(
                ["bash", str(script_path)],
                cwd=str(staging_dir),
                start_new_session=True,
            )

    sys.exit(0)


def should_check_for_updates(config: dict) -> bool:
    """Check if enough time has elapsed since the last update check."""
    updater_cfg = config.get("updater", {})
    if not updater_cfg.get("check_on_startup", True):
        return False

    last_check = updater_cfg.get("last_update_check")
    if not last_check:
        return True

    try:
        last_dt = datetime.fromisoformat(str(last_check))
        now = datetime.now(timezone.utc)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed = (now - last_dt).total_seconds()
        return elapsed >= CHECK_INTERVAL_SECONDS
    except (ValueError, TypeError):
        return True


def save_last_check_time(config_path: Path):
    """Update the last_update_check timestamp in config.yaml."""
    try:
        import yaml
        from app_paths import invalidate_config_cache

        cfg = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

        if "updater" not in cfg:
            cfg["updater"] = {}

        cfg["updater"]["last_update_check"] = datetime.now(timezone.utc).isoformat()

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

        invalidate_config_cache()
    except Exception as e:
        print(f"[Updater] Failed to save check time: {e}")


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
