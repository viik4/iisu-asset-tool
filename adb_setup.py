"""
ADB Setup Helper for iiSU Asset Tool
Downloads and sets up Android SDK Platform Tools automatically.
"""
import os
import sys
import zipfile
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Callable
import urllib.request
import tempfile

# Platform tools download URLs (official Google sources)
PLATFORM_TOOLS_URLS = {
    "win32": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}

# Default installation directory
def get_default_adb_dir() -> Path:
    """Get the default ADB installation directory."""
    if sys.platform == "win32":
        # Install to user's local app data
        app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(app_data) / "Android" / "platform-tools"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Android" / "platform-tools"
    else:
        return Path.home() / ".android" / "platform-tools"


def get_adb_executable_name() -> str:
    """Get the ADB executable name for the current platform."""
    if sys.platform == "win32":
        return "adb.exe"
    return "adb"


def is_adb_installed(check_path: Optional[Path] = None) -> Tuple[bool, Optional[Path]]:
    """
    Check if ADB is already installed.

    Returns:
        Tuple of (is_installed, adb_path)
    """
    # Check provided path first
    if check_path:
        adb_exe = check_path / get_adb_executable_name()
        if adb_exe.exists():
            return True, adb_exe

    # Check if adb is in PATH
    adb_in_path = shutil.which("adb")
    if adb_in_path:
        return True, Path(adb_in_path)

    # Check common installation locations
    common_paths = []
    if sys.platform == "win32":
        common_paths = [
            Path(r"C:\adb"),
            Path(r"C:\Android\platform-tools"),
            Path(r"C:\Program Files\Android\platform-tools"),
            Path(r"C:\Program Files (x86)\Android\platform-tools"),
            Path(os.path.expanduser(r"~\AppData\Local\Android\Sdk\platform-tools")),
            Path(os.path.expanduser(r"~\AppData\Local\Android\platform-tools")),
        ]
    elif sys.platform == "darwin":
        common_paths = [
            Path.home() / "Library" / "Android" / "sdk" / "platform-tools",
            Path.home() / "Library" / "Android" / "platform-tools",
            Path("/usr/local/bin"),
        ]
    else:
        common_paths = [
            Path.home() / "Android" / "Sdk" / "platform-tools",
            Path.home() / ".android" / "platform-tools",
            Path("/usr/bin"),
            Path("/usr/local/bin"),
        ]

    for path in common_paths:
        adb_exe = path / get_adb_executable_name()
        if adb_exe.exists():
            return True, adb_exe

    # Check default installation directory
    default_dir = get_default_adb_dir()
    adb_exe = default_dir / get_adb_executable_name()
    if adb_exe.exists():
        return True, adb_exe

    return False, None


def download_platform_tools(
    dest_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Tuple[bool, str, Optional[Path]]:
    """
    Download and extract Android SDK Platform Tools.

    Args:
        dest_dir: Destination directory (default: platform-specific location)
        progress_callback: Optional callback(bytes_downloaded, total_bytes)

    Returns:
        Tuple of (success, message, adb_path)
    """
    if dest_dir is None:
        dest_dir = get_default_adb_dir()

    # Get download URL for current platform
    platform_key = sys.platform
    if platform_key not in PLATFORM_TOOLS_URLS:
        if platform_key.startswith("linux"):
            platform_key = "linux"
        else:
            return False, f"Unsupported platform: {platform_key}", None

    url = PLATFORM_TOOLS_URLS[platform_key]

    try:
        # Create temp file for download
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

        print(f"Downloading Android SDK Platform Tools...")
        print(f"URL: {url}")
        print(f"Destination: {dest_dir}")

        # Download with progress
        def reporthook(block_num, block_size, total_size):
            if progress_callback and total_size > 0:
                downloaded = block_num * block_size
                progress_callback(downloaded, total_size)

        urllib.request.urlretrieve(url, tmp_path, reporthook=reporthook)

        print(f"Download complete. Extracting...")

        # Create destination directory
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        # Extract zip file
        with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
            # The zip contains a "platform-tools" folder
            # Extract to parent directory so we get dest_dir/adb.exe
            extract_to = dest_dir.parent
            zip_ref.extractall(extract_to)

        # Clean up temp file
        tmp_path.unlink()

        # Verify installation
        adb_exe = dest_dir / get_adb_executable_name()
        if not adb_exe.exists():
            # Check if it extracted to a different name
            extracted_dir = dest_dir.parent / "platform-tools"
            if extracted_dir.exists() and extracted_dir != dest_dir:
                # Rename to expected location
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                extracted_dir.rename(dest_dir)
                adb_exe = dest_dir / get_adb_executable_name()

        if not adb_exe.exists():
            return False, f"Installation failed: ADB executable not found at {adb_exe}", None

        # Make executable on Unix systems
        if sys.platform != "win32":
            adb_exe.chmod(0o755)

        # Test ADB
        try:
            run_kwargs = {'capture_output': True, 'text': True, 'timeout': 10}
            if sys.platform == 'win32':
                run_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [str(adb_exe), "version"],
                **run_kwargs
            )
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0] if result.stdout else "Unknown version"
                return True, f"Successfully installed: {version_line}", adb_exe
            else:
                return False, f"ADB installed but failed to run: {result.stderr}", adb_exe
        except Exception as e:
            return False, f"ADB installed but failed to verify: {e}", adb_exe

    except urllib.error.URLError as e:
        return False, f"Download failed: {e}", None
    except zipfile.BadZipFile as e:
        return False, f"Invalid zip file: {e}", None
    except PermissionError as e:
        return False, f"Permission denied: {e}. Try running as administrator.", None
    except Exception as e:
        return False, f"Installation failed: {e}", None


def add_to_path(adb_dir: Path) -> Tuple[bool, str]:
    """
    Add ADB directory to the system PATH (Windows only, for current user).

    Returns:
        Tuple of (success, message)
    """
    if sys.platform != "win32":
        return False, "PATH modification only supported on Windows. Add manually to your shell profile."

    try:
        import winreg

        # Open the user's environment variables
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_ALL_ACCESS
        )

        try:
            # Get current PATH
            current_path, _ = winreg.QueryValueEx(key, "Path")
        except WindowsError:
            current_path = ""

        # Check if already in PATH
        adb_dir_str = str(adb_dir)
        if adb_dir_str.lower() in current_path.lower():
            winreg.CloseKey(key)
            return True, "ADB directory already in PATH"

        # Add to PATH
        if current_path:
            new_path = f"{current_path};{adb_dir_str}"
        else:
            new_path = adb_dir_str

        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
        winreg.CloseKey(key)

        # Broadcast environment change
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x1A
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 0, 1000, None
            )
        except Exception:
            pass

        # Also add to current process PATH
        os.environ["PATH"] = new_path

        return True, f"Added {adb_dir_str} to user PATH. Restart terminal for full effect."

    except Exception as e:
        return False, f"Failed to modify PATH: {e}"


def setup_adb(
    install_dir: Optional[Path] = None,
    add_path: bool = True,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Tuple[bool, str, Optional[Path]]:
    """
    Full ADB setup: check if installed, download if needed, add to PATH.

    Args:
        install_dir: Optional custom installation directory
        add_path: Whether to add to system PATH (Windows only)
        progress_callback: Optional progress callback for download

    Returns:
        Tuple of (success, message, adb_path)
    """
    # Check if already installed
    is_installed, existing_path = is_adb_installed(install_dir)
    if is_installed:
        return True, f"ADB already installed at: {existing_path}", existing_path

    # Download and install
    success, message, adb_path = download_platform_tools(install_dir, progress_callback)

    if not success:
        return False, message, None

    # Add to PATH on Windows
    if add_path and sys.platform == "win32" and adb_path:
        path_success, path_message = add_to_path(adb_path.parent)
        if path_success:
            message += f"\n{path_message}"
        else:
            message += f"\nNote: {path_message}"

    return True, message, adb_path


def get_setup_instructions() -> str:
    """Get manual setup instructions for the current platform."""
    if sys.platform == "win32":
        return """
Manual ADB Setup Instructions (Windows):

1. Download Android SDK Platform Tools:
   https://developer.android.com/tools/releases/platform-tools

2. Extract the ZIP file to a folder (e.g., C:\\adb)

3. Add to PATH (optional but recommended):
   - Press Win+X and select "System"
   - Click "Advanced system settings"
   - Click "Environment Variables"
   - Under "User variables", select "Path" and click "Edit"
   - Click "New" and add the folder path (e.g., C:\\adb)
   - Click OK on all dialogs

4. Enable USB Debugging on your Android device:
   - Go to Settings > About Phone
   - Tap "Build Number" 7 times to enable Developer Options
   - Go to Settings > Developer Options
   - Enable "USB Debugging"

5. Connect your device and authorize the USB debugging prompt
"""
    elif sys.platform == "darwin":
        return """
Manual ADB Setup Instructions (macOS):

1. Using Homebrew (recommended):
   brew install android-platform-tools

   OR

2. Manual download:
   - Download from: https://developer.android.com/tools/releases/platform-tools
   - Extract to ~/Library/Android/platform-tools
   - Add to PATH in ~/.zshrc or ~/.bash_profile:
     export PATH="$PATH:$HOME/Library/Android/platform-tools"

3. Enable USB Debugging on your Android device:
   - Go to Settings > About Phone
   - Tap "Build Number" 7 times to enable Developer Options
   - Go to Settings > Developer Options
   - Enable "USB Debugging"
"""
    else:
        return """
Manual ADB Setup Instructions (Linux):

1. Using package manager (recommended):
   Ubuntu/Debian: sudo apt install android-tools-adb
   Fedora: sudo dnf install android-tools
   Arch: sudo pacman -S android-tools

   OR

2. Manual download:
   - Download from: https://developer.android.com/tools/releases/platform-tools
   - Extract to ~/.android/platform-tools
   - Add to PATH in ~/.bashrc:
     export PATH="$PATH:$HOME/.android/platform-tools"

3. Set up udev rules for your device (check manufacturer docs)

4. Enable USB Debugging on your Android device:
   - Go to Settings > About Phone
   - Tap "Build Number" 7 times to enable Developer Options
   - Go to Settings > Developer Options
   - Enable "USB Debugging"
"""


if __name__ == "__main__":
    # Test/CLI usage
    import argparse

    parser = argparse.ArgumentParser(description="Setup Android SDK Platform Tools")
    parser.add_argument("--check", action="store_true", help="Check if ADB is installed")
    parser.add_argument("--install", action="store_true", help="Download and install ADB")
    parser.add_argument("--dir", type=str, help="Custom installation directory")
    parser.add_argument("--no-path", action="store_true", help="Don't add to PATH")

    args = parser.parse_args()

    if args.check:
        is_installed, path = is_adb_installed()
        if is_installed:
            print(f"ADB is installed at: {path}")
        else:
            print("ADB is not installed")
            print(get_setup_instructions())

    elif args.install:
        install_dir = Path(args.dir) if args.dir else None

        def progress(downloaded, total):
            pct = (downloaded / total) * 100 if total > 0 else 0
            print(f"\rDownloading: {pct:.1f}%", end="", flush=True)

        success, message, adb_path = setup_adb(
            install_dir=install_dir,
            add_path=not args.no_path,
            progress_callback=progress
        )

        print()  # Newline after progress
        print(message)

        if success:
            print(f"\nADB is ready to use: {adb_path}")
        else:
            print("\nSetup failed. Manual instructions:")
            print(get_setup_instructions())

    else:
        parser.print_help()
