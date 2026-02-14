"""
ROM Browser Tab for iiSU Asset Tool
Browse ROMs from iiSU directory or manual folder selection and generate icons.
"""
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from PySide6.QtCore import Qt, Signal, QObject, QSize, Slot, QThread
from PySide6.QtGui import QIcon, QPixmap

from iisu_image_utils import load_scaled_pixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QLineEdit, QProgressBar, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QFrame, QGroupBox, QScrollArea, QGridLayout, QSpinBox
)

from rom_parser import (
    ROMScanner, scan_generic_folder, get_available_drives,
    find_iisu_directory, detect_platform_from_folder, IISU_PLATFORM_FOLDERS,
    scan_mtp_device, is_mtp_path,
    check_adb_available, get_adb_path, get_adb_devices, scan_adb_device,
    detect_region, REGION_DISPLAY_NAMES
)
from adb_setup import setup_adb, is_adb_installed, get_setup_instructions
from app_paths import get_config_path, get_borders_dir, get_platform_icons_dir, get_config, invalidate_config_cache
import run_backend
import subprocess


def _get_subprocess_flags():
    """Get platform-specific subprocess flags to hide console on Windows."""
    if sys.platform == 'win32':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}


class GameCardWidget(QFrame):
    """
    Game card widget for grid view display.
    Shows game icon preview, title, and asset status indicators.
    Supports selection and double-click actions.
    """

    clicked = Signal(object)  # Emits self when clicked
    double_clicked = Signal(object)  # Emits self when double-clicked
    selection_changed = Signal(object, bool)  # Emits (self, is_selected)
    context_menu_requested = Signal(object, object)  # Emits (self, QPoint global_pos)

    def __init__(self, title: str, path: str, platform: str, icon_path: Optional[Path] = None,
                 relative_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.title = title
        self.path = path
        self.platform = platform
        self.icon_path = icon_path
        self.relative_path = relative_path  # Path from platform dir to game's parent (for deep search)
        self._selected = False

        # Asset status flags
        self.has_icon = False
        self.has_hero = False
        self.has_logo = False

        self.setFrameShape(QFrame.Box)
        self.setLineWidth(2)
        self.setFixedSize(140, 175)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("game_card")
        self._update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Icon image container
        self.image_label = QLabel()
        self.image_label.setFixedSize(128, 128)
        self.image_label.setScaledContents(True)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setObjectName("game_card_image")

        # Set icon or placeholder
        self._device_icon_path = None  # Track device path for lazy loading
        if icon_path:
            icon_path_str = str(icon_path)
            if icon_path_str.startswith("device:"):
                # Device path - mark as having icon but show placeholder initially
                self._device_icon_path = icon_path_str[7:]  # Remove "device:" prefix
                self.has_icon = True  # Has icon on device
                self._set_placeholder(platform)
            elif Path(icon_path).exists():
                pixmap = load_scaled_pixmap(str(icon_path), 128)
                if not pixmap.isNull():
                    self.image_label.setPixmap(pixmap)
                    self.has_icon = True
                else:
                    self._set_placeholder(platform)
            else:
                self._set_placeholder(platform)
        else:
            self._set_placeholder(platform)

        layout.addWidget(self.image_label, 0, Qt.AlignCenter)

        # Title label (truncated)
        display_title = title[:16] + "..." if len(title) > 16 else title
        self.title_label = QLabel(display_title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setObjectName("game_card_title")
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(24)
        layout.addWidget(self.title_label)

        # Asset status badges row
        badge_row = QHBoxLayout()
        badge_row.setSpacing(2)
        badge_row.setContentsMargins(0, 0, 0, 0)

        self.icon_badge = QLabel("I")
        self.icon_badge.setFixedSize(18, 14)
        self.icon_badge.setAlignment(Qt.AlignCenter)
        self.icon_badge.setObjectName("asset_badge_missing")
        badge_row.addWidget(self.icon_badge)

        self.hero_badge = QLabel("H")
        self.hero_badge.setFixedSize(18, 14)
        self.hero_badge.setAlignment(Qt.AlignCenter)
        self.hero_badge.setObjectName("asset_badge_missing")
        badge_row.addWidget(self.hero_badge)

        self.logo_badge = QLabel("L")
        self.logo_badge.setFixedSize(18, 14)
        self.logo_badge.setAlignment(Qt.AlignCenter)
        self.logo_badge.setObjectName("asset_badge_missing")
        badge_row.addWidget(self.logo_badge)

        badge_row.addStretch()
        layout.addLayout(badge_row)

        # Full tooltip
        self.setToolTip(f"{title}\n[{platform}]\n\nClick to select\nDouble-click to generate")

    def _set_placeholder(self, platform: str):
        """Set placeholder image with platform icon."""
        from PySide6.QtGui import QPainter, QColor, QFont

        # Create placeholder with dark background
        placeholder = QPixmap(128, 128)
        placeholder.fill(QColor(40, 45, 52))

        # Try to load platform icon
        platform_icons_dir = get_platform_icons_dir()
        platform_icon_path = None

        # Check for platform icon files with various name formats
        name_variations = [
            platform,  # Exact match (e.g., GAMECUBE)
            platform.lower(),  # Lowercase
            platform.upper(),  # Uppercase
            platform.replace("_", " ").title().replace(" ", "_"),  # Title_Case
        ]

        for name in name_variations:
            for ext in ['.png', '.svg', '.jpg']:
                potential_path = platform_icons_dir / f"{name}{ext}"
                if potential_path.exists():
                    platform_icon_path = potential_path
                    break
            if platform_icon_path:
                break

        painter = QPainter(placeholder)
        painter.setRenderHint(QPainter.Antialiasing)

        if platform_icon_path:
            # Draw platform icon centered (cached for fast revisits)
            platform_pixmap = load_scaled_pixmap(str(platform_icon_path), 64)
            if not platform_pixmap.isNull():
                scaled = platform_pixmap
                x = (128 - scaled.width()) // 2
                y = (128 - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
        else:
            # Draw placeholder text
            painter.setPen(QColor(100, 100, 100))
            font = QFont()
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(placeholder.rect(), Qt.AlignCenter, "No Icon")

        painter.end()
        self.image_label.setPixmap(placeholder)

    def _update_style(self):
        """Update widget style based on selection state."""
        self.setProperty("selected", "true" if self._selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def update_asset_status(self, has_icon: bool, has_hero: bool, has_logo: bool):
        """Update the asset status badges."""
        self.has_icon = has_icon
        self.has_hero = has_hero
        self.has_logo = has_logo

        self.icon_badge.setObjectName("asset_badge_found" if has_icon else "asset_badge_missing")
        self.hero_badge.setObjectName("asset_badge_found" if has_hero else "asset_badge_missing")
        self.logo_badge.setObjectName("asset_badge_found" if has_logo else "asset_badge_missing")

        # Force style refresh
        for badge in [self.icon_badge, self.hero_badge, self.logo_badge]:
            badge.style().unpolish(badge)
            badge.style().polish(badge)

    def set_icon(self, pixmap: QPixmap):
        """Update the displayed icon."""
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap)
            self.has_icon = True

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Set selection state."""
        if self._selected != selected:
            self._selected = selected
            self._update_style()
            self.selection_changed.emit(self, selected)

    def toggle_selection(self):
        """Toggle selection state."""
        self.set_selected(not self._selected)

    def mousePressEvent(self, event):
        """Handle mouse press - toggle selection."""
        if event.button() == Qt.LeftButton:
            self.toggle_selection()
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click - trigger generation."""
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Handle right-click - show context menu."""
        self.context_menu_requested.emit(self, event.globalPos())
        event.accept()


class BackendCallbacks(QObject):
    """Qt signals for backend callbacks."""
    progress = Signal(int, int)  # done, total
    log = Signal(str)
    finished = Signal(bool, str)
    preview = Signal(str)
    current_item = Signal(str, str)  # title, platform


class ScanWorker(QObject):
    """Worker for non-blocking ROM scanning with progress updates."""
    platform_found = Signal(str, list)  # platform_key, games list
    scan_progress = Signal(str)  # status message
    scan_finished = Signal(dict, str)  # all results, final message
    scan_error = Signal(str)  # error message

    def __init__(self, path_str: str, scanner: ROMScanner, deep_search: bool = False):
        super().__init__()
        self.path_str = path_str
        self.scanner = scanner
        self.deep_search = deep_search
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """Execute the scanning in a thread."""
        try:
            results = {}

            # Check for ADB protocol path (iisu://device_id/path)
            if self.path_str.startswith("iisu://"):
                # Direct ADB path format: iisu://device_id/path
                path_part = self.path_str[7:]  # Remove "iisu://"
                parts = path_part.split("/", 1)
                device_id = parts[0] if parts else ""
                adb_path = "/" + parts[1] if len(parts) > 1 else "/sdcard/roms"

                self.scan_progress.emit(f"Scanning via ADB...")
                results = self._scan_adb_with_progress(device_id, adb_path)

            # Check if this is an MTP device path
            elif is_mtp_path(self.path_str):
                cleaned_path = self.path_str.replace("This PC\\", "").replace("This PC/", "")
                parts = cleaned_path.split("\\") if "\\" in cleaned_path else cleaned_path.split("/")

                if parts:
                    device_name = parts[0]
                    subfolder = "/".join(parts[1:]) if len(parts) > 1 else ""

                    # Try ADB first (faster)
                    adb_available = check_adb_available()
                    adb_devices = get_adb_devices() if adb_available else []

                    if adb_devices:
                        self.scan_progress.emit(f"Scanning via ADB: {device_name}...")
                        adb_path = subfolder.replace("Internal shared storage", "/sdcard").replace("Internal Storage", "/sdcard")
                        if not adb_path.startswith("/"):
                            adb_path = f"/sdcard/{adb_path}" if adb_path else "/sdcard/roms"
                        device_id = adb_devices[0][0] if len(adb_devices) == 1 else ""
                        results = self._scan_adb_with_progress(device_id, adb_path)

                    if not results:
                        # Note: MTP fallback doesn't support deep search yet (ADB is preferred)
                        if self.deep_search:
                            self.scan_progress.emit(f"Scanning MTP device: {device_name} (deep search requires ADB)...")
                        else:
                            self.scan_progress.emit(f"Scanning MTP device: {device_name}...")
                        results = scan_mtp_device(device_name, subfolder)
                        # Convert 2-tuples to 3-tuples for consistency (MTP doesn't support relative_path yet)
                        for platform_key, games in results.items():
                            results[platform_key] = [(title, path, None) for title, path in games]
                            self.platform_found.emit(platform_key, results[platform_key])

                    if not results:
                        self.scan_error.emit("Could not scan device. Try 'Add Games Manually'.")
                        return
            else:
                # Standard filesystem path
                path = Path(self.path_str)
                if not path.exists():
                    self.scan_error.emit(f"Folder not found: {self.path_str}")
                    return

                platform = detect_platform_from_folder(path.name)
                if platform:
                    self.scan_progress.emit(f"Scanning {platform}{'(deep)' if self.deep_search else ''}...")
                    games = scan_generic_folder(path, platform, self.deep_search)
                    results = {platform: games}
                    self.platform_found.emit(platform, games)
                else:
                    # Multi-platform scan with live updates
                    self.scan_progress.emit("Detecting platforms...")
                    self.scanner.set_iisu_path(path)

                    # Scan each platform folder individually for live updates
                    for folder in path.iterdir():
                        if self._cancelled:
                            break
                        if folder.is_dir():
                            platform_key = detect_platform_from_folder(folder.name)
                            if platform_key:
                                self.scan_progress.emit(f"Scanning {platform_key}{'(deep)' if self.deep_search else ''}...")
                                games = scan_generic_folder(folder, platform_key, self.deep_search)
                                if games:
                                    results[platform_key] = games
                                    self.platform_found.emit(platform_key, games)

            if not self._cancelled:
                total_games = sum(len(g) for g in results.values())
                self.scan_finished.emit(results, f"Found {total_games} games in {len(results)} platforms")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.scan_error.emit(f"Scan error: {str(e)}")

    def _scan_adb_with_progress(self, device_id: str, rom_path: str) -> dict:
        """Scan ADB device with progress signals for each platform.
        Supports deep_search to scan subdirectories for games.
        Uses optimized `find` command for deep search (much faster than iterative ls).
        """
        from rom_parser import get_adb_path, detect_platform_from_folder, clean_game_title
        import subprocess

        results = {}
        adb_path = get_adb_path()
        if not adb_path:
            self.scan_error.emit("ADB not found")
            return results

        def run_adb(cmd, timeout=30):
            try:
                kwargs = {'capture_output': True, 'timeout': timeout}
                if sys.platform == 'win32':
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                result = subprocess.run(cmd, **kwargs)
                if result.returncode != 0:
                    return None
                try:
                    return result.stdout.decode('utf-8')
                except UnicodeDecodeError:
                    return result.stdout.decode('latin-1', errors='replace')
            except Exception:
                return None

        def scan_folder_deep_fast(folder_path):
            """
            Fast deep scan using `find` command to get all game folders in one call.
            Finds directories that contain icon/hero/title files (game folders).
            """
            games = []

            # Use find to get all directories containing game assets in one command
            # This finds folders with icon.*, hero.*, title.*, logo.* files
            find_cmd = base_cmd + ["shell", f'''
                find "{folder_path}" -maxdepth 4 -type f \\( -name "icon.*" -o -name "hero*" -o -name "title.*" -o -name "logo.*" \\) 2>/dev/null |
                sed 's|/[^/]*$||' |
                sort -u
            ''']
            output = run_adb(find_cmd, timeout=60)

            game_folders = set()
            if output:
                for line in output.strip().split('\n'):
                    folder = line.strip()
                    if folder and folder != folder_path:
                        game_folders.add(folder)

            # Also find leaf directories (no subdirectories) as potential games
            # This catches game folders that don't have assets yet
            leaf_cmd = base_cmd + ["shell", f'''
                find "{folder_path}" -maxdepth 4 -type d 2>/dev/null | while read dir; do
                    if [ -d "$dir" ] && [ -z "$(find "$dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)" ]; then
                        echo "$dir"
                    fi
                done
            ''']
            leaf_output = run_adb(leaf_cmd, timeout=60)

            if leaf_output:
                for line in leaf_output.strip().split('\n'):
                    folder = line.strip()
                    if folder and folder != folder_path:
                        # Skip media/cache folders
                        folder_name = folder.split('/')[-1].lower()
                        if folder_name not in ('media', 'cache', '.', '..'):
                            game_folders.add(folder)

            # Process found folders
            for game_folder in sorted(game_folders):
                # Calculate relative path from platform folder
                rel_from_platform = game_folder[len(folder_path):].lstrip('/')
                parts = rel_from_platform.split('/')

                if len(parts) >= 1:
                    game_name = parts[-1]  # Last part is game folder name
                    relative_path = '/'.join(parts[:-1]) if len(parts) > 1 else None

                    try:
                        game_title = clean_game_title(game_name)
                    except Exception:
                        continue

                    if game_title:
                        placeholder_path = Path(f"adb://{device_id}/{game_folder}")
                        games.append((game_title, placeholder_path, relative_path))

            return games

        def scan_folder_shallow(folder_path):
            """Shallow scan - only immediate children."""
            games = []
            cmd = base_cmd + ["shell", "ls", "-1", folder_path]
            output = run_adb(cmd, timeout=30)

            if not output:
                return games

            seen_titles = set()
            for line in output.strip().split('\n'):
                item_name = line.strip()
                if not item_name or item_name.startswith('.'):
                    continue

                try:
                    game_title = clean_game_title(item_name.rsplit('.', 1)[0] if '.' in item_name else item_name)
                except Exception:
                    continue

                if game_title and game_title.lower() not in seen_titles:
                    seen_titles.add(game_title.lower())
                    placeholder_path = Path(f"adb://{device_id}/{folder_path}/{item_name}")
                    games.append((game_title, placeholder_path, None))

            return games

        base_cmd = [adb_path]
        if device_id:
            base_cmd.extend(["-s", device_id])

        # List platform folders
        self.scan_progress.emit("Listing platforms...")
        cmd = base_cmd + ["shell", "ls", "-1", rom_path]
        output = run_adb(cmd, timeout=15)

        if output is None:
            # Try alternative path
            if "/sdcard/" in rom_path:
                alt_path = rom_path.replace("/sdcard/", "/storage/emulated/0/")
                cmd = base_cmd + ["shell", "ls", "-1", alt_path]
                output = run_adb(cmd, timeout=15)
                if output:
                    rom_path = alt_path

        if not output:
            return results

        # Parse platform folders
        platform_folders = []
        for line in output.strip().split('\n'):
            folder_name = line.strip()
            if folder_name and not folder_name.startswith('.'):
                platform = detect_platform_from_folder(folder_name)
                if platform:
                    platform_folders.append((folder_name, platform))

        # Scan each platform with progress updates
        for i, (folder_name, platform_key) in enumerate(platform_folders):
            if self._cancelled:
                break

            folder_path = f"{rom_path}/{folder_name}"

            if self.deep_search:
                self.scan_progress.emit(f"Deep scanning {platform_key} ({i+1}/{len(platform_folders)})...")
                games = scan_folder_deep_fast(folder_path)
            else:
                self.scan_progress.emit(f"Scanning {platform_key} ({i+1}/{len(platform_folders)})...")
                games = scan_folder_shallow(folder_path)

            if games:
                results[platform_key] = games
                # Emit signal for live UI update
                self.platform_found.emit(platform_key, games)

        return results


class IconLoaderWorker(QObject):
    """Worker for loading device icons in background without blocking UI.

    Optimized for fast batch loading:
    - Tries multiple file extensions (.png, .jpg, .jpeg)
    - Uses efficient ADB shell commands to find actual files
    - Caches results in temp directory
    """
    icon_loaded = Signal(str, str)  # game_title, local_icon_path
    batch_progress = Signal(int, int)  # current, total
    finished = Signal()

    def __init__(self, device_id: str, icon_requests: list, platform_key: str = ""):
        """
        Args:
            device_id: ADB device identifier
            icon_requests: List of (game_title, device_path) tuples
            platform_key: Platform identifier for temp directory organization
        """
        super().__init__()
        self.device_id = device_id
        self.icon_requests = icon_requests
        self.platform_key = platform_key
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _run_adb(self, cmd, timeout=10):
        """Run ADB command and return output or None on failure."""
        try:
            kwargs = {'capture_output': True, 'timeout': timeout}
            if sys.platform == 'win32':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(cmd, **kwargs)
            if result.returncode == 0:
                try:
                    return result.stdout.decode('utf-8')
                except UnicodeDecodeError:
                    return result.stdout.decode('latin-1', errors='replace')
        except Exception:
            pass
        return None

    def run(self):
        """Pull icons from device to local temp directory."""
        import tempfile

        adb_path = get_adb_path()
        if not adb_path:
            print("[DEBUG] IconLoaderWorker: ADB not found")
            self.finished.emit()
            return

        base_cmd = [adb_path]
        if self.device_id:
            base_cmd.extend(["-s", self.device_id])

        # Create temp directory for this platform
        temp_dir = Path(tempfile.gettempdir()) / "iisu_device_icons" / (self.platform_key or "unknown")
        temp_dir.mkdir(parents=True, exist_ok=True)

        print(f"[DEBUG] IconLoaderWorker: Processing {len(self.icon_requests)} icons for {self.platform_key}")
        print(f"[DEBUG] IconLoaderWorker: Temp dir = {temp_dir}")

        # Asset file names to search for (in priority order)
        asset_priorities = ["icon", "slide", "hero", "title", "logo"]
        extensions = [".png", ".jpg", ".jpeg"]

        total = len(self.icon_requests)
        for idx, (game_title, device_path) in enumerate(self.icon_requests):
            if self._cancelled:
                break

            try:
                # device_path format: /path/to/game_folder/icon.png (suggested filename)
                # We need to find the actual file that exists
                game_folder = '/'.join(device_path.split('/')[:-1])  # Remove filename part

                # Check for cached copy first (any extension)
                cached_path = None
                for ext in extensions:
                    check_path = temp_dir / f"{game_title}{ext}"
                    if check_path.exists():
                        cached_path = check_path
                        break

                if cached_path:
                    self.icon_loaded.emit(game_title, str(cached_path))
                    self.batch_progress.emit(idx + 1, total)
                    continue

                # List files in the game folder to find actual asset files
                list_cmd = base_cmd + ["shell", f'ls -1 "{game_folder}" 2>/dev/null']
                file_list = self._run_adb(list_cmd, timeout=5)

                if not file_list:
                    print(f"[DEBUG] IconLoaderWorker: No files found in {game_folder}")
                    self.batch_progress.emit(idx + 1, total)
                    continue

                files = [f.strip() for f in file_list.split('\n') if f.strip()]

                # Find the best asset file to use (priority order)
                # Asset patterns: icon.ext, title.ext, slide_N.ext, hero_N.ext, logo.ext
                target_file = None
                for asset_name in asset_priorities:
                    for f in files:
                        f_lower = f.lower()
                        # Check for exact match (e.g., icon.png, title.jpg)
                        if f_lower.startswith(asset_name + '.') and any(f_lower.endswith(ext) for ext in extensions):
                            target_file = f
                            break
                        # Check for numbered match (e.g., slide_1.png, hero_2.jpg)
                        if f_lower.startswith(asset_name + '_') and any(f_lower.endswith(ext) for ext in extensions):
                            target_file = f
                            break
                    if target_file:
                        break

                if not target_file:
                    print(f"[DEBUG] IconLoaderWorker: No suitable asset found in {game_folder}, files: {files[:10]}")
                    self.batch_progress.emit(idx + 1, total)
                    continue

                # Get file extension
                file_ext = '.' + target_file.rsplit('.', 1)[-1].lower() if '.' in target_file else '.png'
                local_path = temp_dir / f"{game_title}{file_ext}"

                # Pull the file
                device_file_path = f"{game_folder}/{target_file}"
                pull_cmd = base_cmd + ["pull", device_file_path, str(local_path)]

                kwargs = {'capture_output': True, 'timeout': 15}
                if sys.platform == 'win32':
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

                result = subprocess.run(pull_cmd, **kwargs)
                if result.returncode == 0 and local_path.exists():
                    print(f"[DEBUG] IconLoaderWorker: Pulled {game_title} -> {local_path}")
                    self.icon_loaded.emit(game_title, str(local_path))
                else:
                    print(f"[DEBUG] IconLoaderWorker: Failed to pull {device_file_path}")

            except Exception as e:
                print(f"[DEBUG] IconLoaderWorker: Error for {game_title}: {e}")

            self.batch_progress.emit(idx + 1, total)

        print(f"[DEBUG] IconLoaderWorker: Finished processing")
        self.finished.emit()


class ROMBrowserTab(QWidget):
    """ROM Browser tab for scanning and processing ROMs from directories."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._cancel_token = None
        self._worker_thread = None
        self._scanner = ROMScanner()

        # Settings
        self.config_path = str(get_config_path())
        self.rom_path = ""  # User-selected ROM path
        self.deep_search = False  # Deep search for games in subdirectories
        self.hero_enabled = True
        self.hero_count = 1
        self.fallback_settings = {}  # Fallback icon settings
        self.screenshot_settings = {"enabled": False, "count": 3}  # Screenshot settings
        self.device_settings = {"enabled": False, "path": "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"}  # Device copy settings
        self.logo_settings = {"scrape_logos": True, "fallback_to_boxart": True}  # Logo/title settings
        self.hidden_titles = {}  # Hidden titles by platform: {platform: [title1, title2, ...]}

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ===== SOURCE SELECTION (Simplified) =====
        source_card = QFrame()
        source_card.setObjectName("card")
        source_layout = QVBoxLayout(source_card)
        source_layout.setContentsMargins(12, 10, 12, 10)
        source_layout.setSpacing(8)

        # Combined path row with integrated actions
        path_row = QHBoxLayout()
        path_row.setSpacing(8)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select ROM folder or scan Android device...")
        self.path_input.setMinimumHeight(38)
        self.path_input.returnPressed.connect(self._scan_directory)
        path_row.addWidget(self.path_input, 1)

        # Browse button with dropdown for device options
        self.btn_browse = QPushButton("Browse ▾")
        self.btn_browse.setObjectName("btn_secondary")
        self.btn_browse.setMinimumHeight(38)
        self.btn_browse.setMinimumWidth(90)
        self.btn_browse.setToolTip("Browse folder or select device")

        # Create context menu for browse options
        from PySide6.QtWidgets import QMenu
        self.browse_menu = QMenu(self)
        self.browse_menu.addAction("Browse Local Folder", self._browse_folder)
        self.browse_menu.addAction("USB Drive / External", self._show_drive_selector)
        self.browse_menu.addSeparator()
        self.browse_menu.addAction("Scan Android (ADB)", self._show_adb_scan_dialog)
        self.browse_menu.addSeparator()
        self.browse_menu.addAction("Add Games Manually", self._show_manual_add_dialog)
        self.btn_browse.setMenu(self.browse_menu)
        path_row.addWidget(self.btn_browse)

        # Scan button
        self.btn_refresh = QPushButton("Scan")
        self.btn_refresh.setMinimumHeight(38)
        self.btn_refresh.setMinimumWidth(70)
        self.btn_refresh.setToolTip("Scan selected folder for ROMs")
        self.btn_refresh.clicked.connect(self._scan_directory)
        self.btn_refresh.setObjectName("btn_primary")
        path_row.addWidget(self.btn_refresh)

        source_layout.addLayout(path_row)

        # Keep hidden buttons for compatibility
        self.btn_select_drive = QPushButton()
        self.btn_select_drive.setVisible(False)
        self.btn_adb_scan = QPushButton()
        self.btn_adb_scan.setVisible(False)
        self.btn_manual_add = QPushButton()
        self.btn_manual_add.setVisible(False)

        layout.addWidget(source_card)

        # Main content splitter
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Platform tree
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        platform_label = QLabel("Platforms")
        platform_label.setObjectName("label_card_title")
        left_layout.addWidget(platform_label)

        self.platform_tree = QTreeWidget()
        self.platform_tree.setHeaderHidden(True)
        self.platform_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.platform_tree.itemClicked.connect(self._on_platform_selected)
        self.platform_tree.setMinimumWidth(180)
        self.platform_tree.setObjectName("rom_platform_tree")
        # Enable context menu (right-click) for platforms
        self.platform_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.platform_tree.customContextMenuRequested.connect(self._show_platform_context_menu)
        left_layout.addWidget(self.platform_tree, 1)

        self.platform_stats = QLabel("No ROMs scanned")
        self.platform_stats.setObjectName("label_muted")
        left_layout.addWidget(self.platform_stats)

        splitter.addWidget(left_panel)

        # Right panel: Game grid
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Asset type filter tabs row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        self.filter_all = QPushButton("All")
        self.filter_all.setCheckable(True)
        self.filter_all.setChecked(True)
        self.filter_all.setObjectName("filter_chip")
        self.filter_all.clicked.connect(lambda: self._set_asset_filter("all"))
        filter_row.addWidget(self.filter_all)

        self.filter_icons = QPushButton("Icons")
        self.filter_icons.setCheckable(True)
        self.filter_icons.setObjectName("filter_chip")
        self.filter_icons.clicked.connect(lambda: self._set_asset_filter("icons"))
        filter_row.addWidget(self.filter_icons)

        self.filter_heroes = QPushButton("Heroes")
        self.filter_heroes.setCheckable(True)
        self.filter_heroes.setObjectName("filter_chip")
        self.filter_heroes.clicked.connect(lambda: self._set_asset_filter("heroes"))
        filter_row.addWidget(self.filter_heroes)

        self.filter_logos = QPushButton("Logos")
        self.filter_logos.setCheckable(True)
        self.filter_logos.setObjectName("filter_chip")
        self.filter_logos.clicked.connect(lambda: self._set_asset_filter("logos"))
        filter_row.addWidget(self.filter_logos)

        filter_row.addStretch()

        # Missing assets count label
        self.missing_count_label = QLabel("0 missing assets")
        self.missing_count_label.setObjectName("label_warning")
        filter_row.addWidget(self.missing_count_label)

        right_layout.addLayout(filter_row)

        # Search and selection row
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search games...")
        self.search_input.textChanged.connect(self._filter_games)
        search_row.addWidget(self.search_input, 1)

        self.btn_select_all = QPushButton("All")
        self.btn_select_all.setMinimumWidth(50)
        self.btn_select_all.setObjectName("btn_small")
        self.btn_select_all.clicked.connect(self._select_all_games)
        search_row.addWidget(self.btn_select_all)

        self.btn_select_none = QPushButton("None")
        self.btn_select_none.setMinimumWidth(50)
        self.btn_select_none.setObjectName("btn_small")
        self.btn_select_none.clicked.connect(self._select_no_games)
        search_row.addWidget(self.btn_select_none)

        right_layout.addLayout(search_row)

        # Game cards grid in scroll area
        self.games_scroll_area = QScrollArea()
        self.games_scroll_area.setWidgetResizable(True)
        self.games_scroll_area.setFrameShape(QFrame.NoFrame)
        self.games_scroll_area.setObjectName("games_scroll_area")

        self.games_grid_widget = QWidget()
        self.games_grid_widget.setObjectName("games_grid_container")
        self.games_grid_layout = QGridLayout(self.games_grid_widget)
        self.games_grid_layout.setSpacing(8)
        self.games_grid_layout.setContentsMargins(8, 8, 8, 8)
        self.games_grid_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.games_scroll_area.setWidget(self.games_grid_widget)

        right_layout.addWidget(self.games_scroll_area, 1)

        # Keep the old games_list hidden for compatibility with some methods
        self.games_list = QListWidget()
        self.games_list.setVisible(False)

        # Store game card widgets
        self._game_cards: List[GameCardWidget] = []
        self._current_asset_filter = "all"

        self.games_info = QLabel("Select a platform to view games")
        self.games_info.setObjectName("label_muted")
        right_layout.addWidget(self.games_info)

        splitter.addWidget(right_panel)
        splitter.setSizes([200, 500])

        layout.addWidget(splitter, 1)

        # ===== ACTION BAR (Simplified) =====
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        # Bulk generate all button
        self.btn_bulk_generate = QPushButton("Bulk Generate All")
        self.btn_bulk_generate.setObjectName("btn_action")
        self.btn_bulk_generate.setMinimumHeight(40)
        self.btn_bulk_generate.setMinimumWidth(140)
        self.btn_bulk_generate.setToolTip("Generate all missing assets for selected games")
        self.btn_bulk_generate.clicked.connect(self._bulk_generate_all)
        action_row.addWidget(self.btn_bulk_generate)

        # Primary action button
        self.btn_process = QPushButton("Generate Selected")
        self.btn_process.setObjectName("btn_primary")
        self.btn_process.setMinimumHeight(40)
        self.btn_process.setMinimumWidth(130)
        self.btn_process.clicked.connect(self._start_processing)
        action_row.addWidget(self.btn_process)

        # Cancel button
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("btn_secondary")
        self.btn_cancel.setMinimumHeight(40)
        self.btn_cancel.setMinimumWidth(65)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("Cancel processing")
        self.btn_cancel.clicked.connect(self._cancel_processing)
        action_row.addWidget(self.btn_cancel)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(40)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Ready")
        action_row.addWidget(self.progress, 1)

        # Compact options (moved to right side)
        region_label = QLabel("Region:")
        region_label.setObjectName("label_muted")
        action_row.addWidget(region_label)
        self.region_combo = QComboBox()
        self.region_combo.setToolTip("Prefer artwork from specific region")
        self.region_combo.addItem("Any", "any")
        self.region_combo.addItem("USA", "USA")
        self.region_combo.addItem("EUR", "EUR")
        self.region_combo.addItem("JPN", "JPN")
        self.region_combo.setMinimumWidth(60)
        self.region_combo.setMinimumHeight(28)
        self.region_combo.currentIndexChanged.connect(self._on_region_changed)
        action_row.addWidget(self.region_combo)

        # Hero toggle (compact)
        self.hero_check = QCheckBox("Heroes")
        self.hero_check.setChecked(True)
        self.hero_check.setToolTip("Download hero/banner images")
        action_row.addWidget(self.hero_check)

        # Interactive toggle
        self.interactive_check = QCheckBox("Interactive")
        self.interactive_check.setToolTip("Choose artwork manually")
        action_row.addWidget(self.interactive_check)

        # Output folder button
        self.btn_open_output = QPushButton("Output")
        self.btn_open_output.setObjectName("btn_small")
        self.btn_open_output.setMinimumHeight(40)
        self.btn_open_output.setMinimumWidth(60)
        self.btn_open_output.setToolTip("Open output folder")
        self.btn_open_output.clicked.connect(self._open_output)
        action_row.addWidget(self.btn_open_output)

        # Logs button
        self.btn_show_logs = QPushButton("Logs")
        self.btn_show_logs.setObjectName("btn_small")
        self.btn_show_logs.setMinimumHeight(40)
        self.btn_show_logs.setMinimumWidth(50)
        self.btn_show_logs.setToolTip("View processing logs")
        self.btn_show_logs.clicked.connect(self._show_logs_dialog)
        action_row.addWidget(self.btn_show_logs)

        layout.addLayout(action_row)

        # Status label (compact)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("label_muted")

        layout.addWidget(self.status_label)

        # Preview panel (simplified - collapsible)
        self.preview_group = QFrame()
        self.preview_group.setObjectName("preview_frame")
        preview_layout = QVBoxLayout(self.preview_group)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(6)

        # Preview header with toggle
        preview_header = QHBoxLayout()
        preview_title = QLabel("Generated Icons")
        preview_title.setObjectName("label_header")
        preview_header.addWidget(preview_title)
        preview_header.addStretch()

        self.btn_hide_preview = QPushButton("-")
        self.btn_hide_preview.setFixedSize(24, 24)
        self.btn_hide_preview.setToolTip("Collapse preview")
        self.btn_hide_preview.clicked.connect(self._toggle_preview_visibility)
        self.btn_hide_preview.setObjectName("btn_icon")
        preview_header.addWidget(self.btn_hide_preview)

        # Popout button
        self.btn_popout_preview = QPushButton("^")
        self.btn_popout_preview.setFixedSize(24, 24)
        self.btn_popout_preview.setToolTip("Pop out preview window")
        self.btn_popout_preview.clicked.connect(self._popout_preview)
        self.btn_popout_preview.setObjectName("btn_icon")
        preview_header.addWidget(self.btn_popout_preview)

        preview_layout.addLayout(preview_header)

        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setWidgetResizable(True)
        self.preview_scroll_area.setMinimumHeight(100)
        self.preview_scroll_area.setMaximumHeight(140)
        self.preview_scroll_area.setFrameShape(QFrame.NoFrame)

        self.preview_widget = QWidget()
        self.preview_grid = QGridLayout(self.preview_widget)
        self.preview_grid.setSpacing(4)
        self.preview_grid.setContentsMargins(0, 0, 0, 0)
        self.preview_scroll_area.setWidget(self.preview_widget)

        preview_layout.addWidget(self.preview_scroll_area)
        layout.addWidget(self.preview_group)

        # Track preview visibility and popout window
        self._preview_visible = True
        self._preview_popout_window = None

        self.preview_items = []
        self._log_messages = []

    def _load_settings(self):
        """Load settings from config file."""
        try:
            cfg = get_config()

            rom_cfg = cfg.get("rom_directory", {})
            self.rom_path = rom_cfg.get("rom_path", "")
            self.deep_search = rom_cfg.get("deep_search", False)

            hero_cfg = cfg.get("hero_images", {})
            self.hero_enabled = hero_cfg.get("enabled", True)
            self.hero_count = hero_cfg.get("count", 1)

            # Load hidden titles
            self.hidden_titles = cfg.get("hidden_titles", {})

            # Update UI
            if self.rom_path:
                self.path_input.setText(self.rom_path)
            self.hero_check.setChecked(self.hero_enabled)

            # Set scanner path if we have one saved
            if self.rom_path and Path(self.rom_path).exists():
                self._scanner.set_iisu_path(Path(self.rom_path))

        except Exception as e:
            print(f"Failed to load ROM browser settings: {e}")

    def _save_hidden_titles(self):
        """Save hidden titles to config file."""
        cfg_path = Path(self.config_path)
        try:
            cfg = {}
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}

            cfg["hidden_titles"] = self.hidden_titles

            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            invalidate_config_cache()
        except Exception as e:
            print(f"Failed to save hidden titles: {e}")

    def _save_rom_path(self):
        """Save the current rom_path to config for persistence."""
        cfg_path = Path(self.config_path)
        try:
            cfg = {}
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}

            if "rom_directory" not in cfg:
                cfg["rom_directory"] = {}
            cfg["rom_directory"]["rom_path"] = self.rom_path

            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            invalidate_config_cache()
        except Exception as e:
            print(f"Failed to save ROM path: {e}")

    def _hide_game(self, game_data: Dict):
        """Hide a game from the library view."""
        title = game_data.get("title", "")
        platform = game_data.get("platform", "")

        if not title or not platform:
            return

        # Add to hidden list for this platform
        if platform not in self.hidden_titles:
            self.hidden_titles[platform] = []

        if title not in self.hidden_titles[platform]:
            self.hidden_titles[platform].append(title)
            self._save_hidden_titles()

            # Refresh the current view
            current_item = self.platform_tree.currentItem()
            if current_item:
                self._on_platform_selected(current_item, 0)

    def _unhide_game(self, platform: str, title: str):
        """Unhide a game from the library view."""
        if platform in self.hidden_titles and title in self.hidden_titles[platform]:
            self.hidden_titles[platform].remove(title)
            if not self.hidden_titles[platform]:
                del self.hidden_titles[platform]
            self._save_hidden_titles()

            # Refresh the current view
            current_item = self.platform_tree.currentItem()
            if current_item:
                self._on_platform_selected(current_item, 0)

    def _is_game_hidden(self, platform: str, title: str) -> bool:
        """Check if a game is hidden."""
        return platform in self.hidden_titles and title in self.hidden_titles[platform]

    def _edit_search_query(self, game_data: Dict, card: 'GameCardWidget'):
        """Show a simple dialog to edit the search query for a game."""
        from PySide6.QtWidgets import QInputDialog

        title = game_data.get("title", "Unknown")
        platform = game_data.get("platform", "")

        # Clean the title for initial search query
        clean_title = "".join(c for c in title if c.isalnum() or c in " -_'.!").strip()

        new_query, ok = QInputDialog.getText(
            self,
            "Edit Search Query",
            f"Enter the game title to search for artwork.\n\nOriginal: {title}",
            text=clean_title
        )

        if ok and new_query.strip():
            # Generate with the custom search query
            modified_game_data = game_data.copy()
            modified_game_data["search_term"] = new_query.strip()
            self._generate_single_game(modified_game_data, search_term=new_query.strip())

    def _search_different_game(self, game_data: Dict, card: 'GameCardWidget'):
        """Show full game search dialog with autocomplete from SteamGridDB."""
        from game_search_dialog import GameSearchDialog

        title = game_data.get("title", "Unknown")

        # Clean the title for initial search query
        clean_title = "".join(c for c in title if c.isalnum() or c in " -_'.!").strip()

        # Show the search dialog
        selected_game = GameSearchDialog.search_and_select(
            parent=self,
            initial_query=clean_title,
            title=f"Search Game - {title}"
        )

        if selected_game:
            # User selected a game - generate with the SGDB game ID
            game_id = selected_game.get("id")
            game_name = selected_game.get("name", title)

            if game_id:
                # Generate using the specific SteamGridDB game ID
                modified_game_data = game_data.copy()
                modified_game_data["sgdb_game_id"] = game_id
                modified_game_data["search_term"] = game_name
                self._generate_single_game(modified_game_data, sgdb_game_id=game_id)
            else:
                # Fallback: just use the name
                self._generate_single_game(game_data, search_term=game_name)

    def _browse_folder(self):
        """Browse for a ROM folder using native Windows dialog."""
        # Start from current path if valid, otherwise use "This PC" / Computer
        start_dir = ""
        current = self.path_input.text().strip()
        if current and Path(current).exists():
            start_dir = current

        # Use native dialog - it shows USB drives in the sidebar on Windows
        path = QFileDialog.getExistingDirectory(
            self,
            "Select ROM Folder",
            start_dir,
            QFileDialog.ShowDirsOnly
        )
        if path:
            self.path_input.setText(path)
            self.rom_path = path
            self._save_rom_path()
            self._scan_directory()

    def _show_drive_selector(self):
        """Show a dialog to select from available drives (useful for USB devices)."""
        from PySide6.QtWidgets import QDialog, QListWidget, QListWidgetItem, QDialogButtonBox
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        import subprocess

        drives = get_available_drives()
        if not drives:
            QMessageBox.information(self, "No Drives", "No additional drives detected.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Drive or Device")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select a drive or device:"))

        drive_list = QListWidget()
        for drive_path, drive_label in drives:
            item = QListWidgetItem(drive_label)
            item.setData(Qt.UserRole, drive_path)
            # Mark portable devices
            item.setData(Qt.UserRole + 1, drive_path.startswith("shell:") or "[Portable Device]" in drive_label)
            drive_list.addItem(item)
        layout.addWidget(drive_list)

        # Help text for portable devices
        help_label = QLabel(
            "<span style='color: #888; font-size: 10px;'>"
            "For portable devices (Android, handhelds): Opens in Explorer. "
            "Navigate to your ROM folder, then copy the path from the address bar."
            "</span>"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        # Double-click to select
        drive_list.itemDoubleClicked.connect(dialog.accept)

        if dialog.exec() == QDialog.Accepted:
            selected = drive_list.currentItem()
            if selected:
                drive_path = selected.data(Qt.UserRole)
                is_portable = selected.data(Qt.UserRole + 1)

                if is_portable:
                    # For MTP/portable devices, show a folder browser dialog
                    self._browse_mtp_device(drive_path)
                else:
                    # Standard drive - use file dialog
                    path = QFileDialog.getExistingDirectory(
                        self,
                        "Select ROM Folder",
                        drive_path,
                        QFileDialog.ShowDirsOnly
                    )
                    if path:
                        self.path_input.setText(path)
                        self.rom_path = path
                        self._save_rom_path()
                        self._scan_directory()

    def _browse_mtp_device(self, shell_path: str):
        """Browse an MTP device and let user select a folder."""
        from PySide6.QtWidgets import QDialog, QTreeWidget, QTreeWidgetItem, QDialogButtonBox, QTextEdit
        import subprocess
        import tempfile

        # Extract device name from the shell path
        # Path format: ::{GUID}\\?\usb#...
        # We need to find the device by matching the path
        from rom_parser import get_portable_devices
        device_name = None
        for path, label in get_portable_devices():
            if path == shell_path:
                device_name = label.replace(" [Portable Device]", "")
                break

        if not device_name:
            QMessageBox.warning(self, "Error", "Could not identify the device.")
            return

        # Create a dialog to browse the device
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Browse {device_name}")
        dialog.setMinimumSize(500, 450)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Browsing: {device_name}\nDouble-click a folder to navigate, or type the path manually below."))

        # Manual path entry at the top
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Path:"))
        manual_path_input = QLineEdit()
        manual_path_input.setPlaceholderText("e.g., Internal shared storage/Download/ROMs")
        manual_row.addWidget(manual_path_input, 1)
        btn_use_path = QPushButton("Use This Path")
        manual_row.addWidget(btn_use_path)
        layout.addLayout(manual_row)

        # Help text
        help_text = QLabel(
            "<span style='color: #888; font-size: 10px;'>"
            "Tip: If browsing is slow, type the path directly. Common paths: "
            "Internal shared storage/ROMs, Internal shared storage/Download"
            "</span>"
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        # Tree widget to show folder structure
        tree = QTreeWidget()
        tree.setHeaderLabels(["Name", "Type"])
        tree.setColumnWidth(0, 350)
        layout.addWidget(tree)

        # Path display
        path_label = QLabel("Current path: /")
        path_label.setObjectName("label_muted")
        layout.addWidget(path_label)

        # Store current path
        current_path = [""]

        def load_folder(folder_path: str):
            """Load contents of a folder on the MTP device."""
            tree.clear()
            current_path[0] = folder_path
            path_label.setText(f"Loading: /{folder_path}..." if folder_path else "Loading: /...")

            # Add "go up" item if not at root
            if folder_path:
                up_item = QTreeWidgetItem([".. (Go Up)", ""])
                up_item.setData(0, Qt.UserRole, "GO_UP")
                tree.addTopLevelItem(up_item)

            # Add loading indicator
            loading_item = QTreeWidgetItem(["Loading...", ""])
            tree.addTopLevelItem(loading_item)

            # Force UI update
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            # PowerShell script to list folder contents - optimized to only list folders first
            # and limit to first 100 items to prevent timeouts
            ps_script = f'''
$ErrorActionPreference = "SilentlyContinue"
$s = New-Object -ComObject Shell.Application
$thispc = $s.NameSpace(17)
$device = $thispc.Items() | Where-Object {{ $_.Name -eq "{device_name}" }} | Select-Object -First 1

if ($device) {{
    $folder = $device.GetFolder
    $pathParts = "{folder_path}" -split '[/\\\\]' | Where-Object {{ $_ }}

    foreach ($part in $pathParts) {{
        $found = $false
        foreach ($item in $folder.Items()) {{
            if ($item.Name -eq $part -and $item.IsFolder) {{
                $folder = $item.GetFolder
                $found = $true
                break
            }}
        }}
        if (-not $found) {{
            exit 1
        }}
    }}

    # List folders first (they're what we care about for navigation)
    $count = 0
    foreach ($item in $folder.Items()) {{
        if ($item.IsFolder) {{
            Write-Output "$($item.Name)|Folder"
            $count++
            if ($count -ge 200) {{ break }}
        }}
    }}

    # Then list some files (limited)
    $fileCount = 0
    foreach ($item in $folder.Items()) {{
        if (-not $item.IsFolder) {{
            Write-Output "$($item.Name)|File"
            $fileCount++
            if ($fileCount -ge 50) {{
                Write-Output "... and more files|Info"
                break
            }}
        }}
    }}
}}
'''
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8') as f:
                    f.write(ps_script)
                    script_path = f.name

                # Hide console window on Windows
                run_kwargs = {'capture_output': True, 'text': True, 'timeout': 60}
                if sys.platform == 'win32':
                    run_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                result = subprocess.run(
                    ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', script_path],
                    **run_kwargs
                )

                import os
                os.unlink(script_path)

                # Remove loading indicator
                tree.clear()
                if folder_path:
                    up_item = QTreeWidgetItem([".. (Go Up)", ""])
                    up_item.setData(0, Qt.UserRole, "GO_UP")
                    tree.addTopLevelItem(up_item)

                path_label.setText(f"Current path: /{folder_path}" if folder_path else "Current path: /")

                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().split('\n'):
                        if '|' in line:
                            name, item_type = line.rsplit('|', 1)
                            item = QTreeWidgetItem([name.strip(), item_type.strip()])
                            item.setData(0, Qt.UserRole, name.strip())
                            item.setData(0, Qt.UserRole + 1, item_type.strip() == "Folder")
                            tree.addTopLevelItem(item)
                else:
                    # Show error or empty folder
                    empty_item = QTreeWidgetItem(["(Empty or inaccessible)", ""])
                    tree.addTopLevelItem(empty_item)

            except subprocess.TimeoutExpired:
                tree.clear()
                if folder_path:
                    up_item = QTreeWidgetItem([".. (Go Up)", ""])
                    up_item.setData(0, Qt.UserRole, "GO_UP")
                    tree.addTopLevelItem(up_item)
                path_label.setText(f"Current path: /{folder_path}" if folder_path else "Current path: /")
                error_item = QTreeWidgetItem(["(Folder has too many files - try a subfolder)", ""])
                tree.addTopLevelItem(error_item)
            except Exception as e:
                tree.clear()
                if folder_path:
                    up_item = QTreeWidgetItem([".. (Go Up)", ""])
                    up_item.setData(0, Qt.UserRole, "GO_UP")
                    tree.addTopLevelItem(up_item)
                path_label.setText(f"Error: {str(e)[:50]}")

        def on_item_double_clicked(item, column):
            """Handle double-click to navigate into folder."""
            data = item.data(0, Qt.UserRole)
            is_folder = item.data(0, Qt.UserRole + 1)

            if data == "GO_UP":
                # Go up one level
                parts = current_path[0].rsplit('/', 1)
                new_path = parts[0] if len(parts) > 1 else ""
                load_folder(new_path)
                manual_path_input.setText(new_path)
            elif is_folder:
                # Navigate into folder
                new_path = f"{current_path[0]}/{data}" if current_path[0] else data
                load_folder(new_path)
                manual_path_input.setText(new_path)

        tree.itemDoubleClicked.connect(on_item_double_clicked)

        def on_use_manual_path():
            """Use the manually entered path."""
            manual_path = manual_path_input.text().strip()
            if manual_path:
                current_path[0] = manual_path
                dialog.accept()

        btn_use_path.clicked.connect(on_use_manual_path)

        # Also accept on Enter in the path input
        manual_path_input.returnPressed.connect(on_use_manual_path)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        # Load root folder
        load_folder("")

        if dialog.exec() == QDialog.Accepted:
            # Use manual path if entered, otherwise use browsed path
            final_path = manual_path_input.text().strip() or current_path[0]
            selected_path = f"{device_name}/{final_path}" if final_path else device_name
            self.path_input.setText(selected_path)
            self.rom_path = selected_path
            self._scan_directory()

    def _scan_directory(self):
        """Scan the selected directory for ROMs using background thread."""
        path_str = self.path_input.text().strip()

        if not path_str:
            QMessageBox.warning(
                self,
                "No Folder Selected",
                "Please click Browse to select your ROM folder.\n\n"
                "Your ROM folder can be on a USB drive, external storage,\n"
                "or any connected device."
            )
            return

        self.status_label.setText("Scanning...")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("Scanning...")

        # Clear previous data
        self.platform_tree.clear()
        self._clear_game_grid()
        self._scan_results = {}

        # Create and start scan worker thread (pass deep_search setting)
        self._scan_worker = ScanWorker(path_str, self._scanner, self.deep_search)
        self._scan_thread = threading.Thread(target=self._run_scan_worker, daemon=True)
        self._scan_thread.start()

    def _run_scan_worker(self):
        """Run the scan worker in a thread and emit signals."""
        from PySide6.QtCore import QMetaObject, Qt as QtCore_Qt, Q_ARG

        worker = self._scan_worker

        def emit_platform(platform_key, games):
            QMetaObject.invokeMethod(self, "_on_platform_scanned",
                                    QtCore_Qt.QueuedConnection,
                                    Q_ARG(str, platform_key),
                                    Q_ARG(object, games))

        def emit_progress(msg):
            QMetaObject.invokeMethod(self, "_on_scan_progress",
                                    QtCore_Qt.QueuedConnection,
                                    Q_ARG(str, msg))

        def emit_finished(results, msg):
            QMetaObject.invokeMethod(self, "_on_scan_finished",
                                    QtCore_Qt.QueuedConnection,
                                    Q_ARG(object, results),
                                    Q_ARG(str, msg))

        def emit_error(msg):
            QMetaObject.invokeMethod(self, "_on_scan_error",
                                    QtCore_Qt.QueuedConnection,
                                    Q_ARG(str, msg))

        worker.platform_found.connect(emit_platform)
        worker.scan_progress.connect(emit_progress)
        worker.scan_finished.connect(emit_finished)
        worker.scan_error.connect(emit_error)
        worker.run()

    @Slot(str, object)
    def _on_platform_scanned(self, platform_key: str, games: list):
        """Handle a platform being scanned - add it to the tree immediately."""
        if not games:
            return

        self._scan_results[platform_key] = games

        # Create platform item
        item = QTreeWidgetItem([f"{platform_key} ({len(games)})"])
        item.setData(0, Qt.UserRole, platform_key)
        item.setData(0, Qt.UserRole + 1, games)

        # Try to load platform icon
        platform_icons_dir = get_platform_icons_dir()
        icon_path = platform_icons_dir / f"{platform_key}.png"
        if icon_path.exists():
            item.setIcon(0, QIcon(str(icon_path)))

        self.platform_tree.addTopLevelItem(item)

        # Update stats
        total_games = sum(len(g) for g in self._scan_results.values())
        self.platform_stats.setText(f"{len(self._scan_results)} platforms, {total_games} games")

    @Slot(str)
    def _on_scan_progress(self, message: str):
        """Handle scan progress update."""
        self.status_label.setText(message)

    @Slot(object, str)
    def _on_scan_finished(self, results: dict, message: str):
        """Handle scan completion."""
        self._scan_results = results
        total_games = sum(len(g) for g in results.values())
        self.platform_stats.setText(f"{len(results)} platforms, {total_games} games total")
        self.status_label.setText(message)
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("Scan")

        # Auto-select first platform
        if self.platform_tree.topLevelItemCount() > 0:
            first_item = self.platform_tree.topLevelItem(0)
            self.platform_tree.setCurrentItem(first_item)
            self._on_platform_selected(first_item, 0)

    @Slot(str)
    def _on_scan_error(self, error: str):
        """Handle scan error."""
        self.status_label.setText("Scan failed")
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("Scan")
        QMessageBox.warning(self, "Scan Failed", error)

    def _on_platform_selected(self, item, column):
        """Handle platform selection in tree."""
        if not item:
            return

        platform_key = item.data(0, Qt.UserRole)
        games = item.data(0, Qt.UserRole + 1)

        if not games:
            return

        # Store current platform for later use
        self._current_platform = platform_key
        self._current_games = games

        # Clear existing grid
        self._clear_game_grid()

        # Get selected region filter
        region_filter = self.region_combo.currentData()

        # Pre-load existing icons and asset info from output directory
        existing_icons = self._load_existing_icons(platform_key)
        asset_status = self._load_asset_status(platform_key)

        # Debug: Print first few existing icons to verify matching data
        device_icons = [(p, s) for p, s in existing_icons if str(p).startswith("device:")]
        print(f"[DEBUG] _on_platform_selected: {len(existing_icons)} existing_icons, {len(device_icons)} from device")

        region_counts = {}
        filtered_count = 0
        icons_found = 0
        missing_icons = 0
        missing_heroes = 0
        missing_logos = 0

        # Calculate grid columns based on available width
        cols = self._calculate_grid_columns()
        row = 0
        col = 0

        for game_tuple in games:
            # Handle both (title, path) and (title, path, relative_path) formats
            if len(game_tuple) == 3:
                title, path, relative_path = game_tuple
            else:
                title, path = game_tuple
                relative_path = None

            # Skip hidden titles
            if self._is_game_hidden(platform_key, title):
                continue

            # Detect region from filename
            filename = Path(path).name if path else title
            detected_region = detect_region(filename, Path(path) if path else None, platform_key)
            region_counts[detected_region] = region_counts.get(detected_region, 0) + 1

            # Apply region filter
            if region_filter != "any":
                if detected_region != region_filter and detected_region != "World":
                    continue

            filtered_count += 1

            # Try to find existing icon path
            icon_path = None
            # Clean the title for matching - remove non-alphanumeric chars
            clean_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
            clean_search = clean_title.lower().replace(" ", "").replace("-", "").replace("_", "")
            # Also remove parentheses and their contents for better matching (e.g., "(USA)" region tags)
            import re
            clean_search_no_parens = re.sub(r'\([^)]*\)', '', clean_search).strip()

            # Debug: print first 3 games' matching attempts
            if filtered_count <= 3:
                print(f"[DEBUG] Matching game #{filtered_count}: title='{title}', clean_search='{clean_search}', no_parens='{clean_search_no_parens}'")
                for existing_path, icon_stem in existing_icons[:5]:  # Show first 5 potential matches
                    is_device = str(existing_path).startswith("device:")
                    print(f"[DEBUG]   vs icon_stem='{icon_stem}' {'(device)' if is_device else ''}")

            for existing_path, icon_stem in existing_icons:
                # Check both directions: title in folder name OR folder name in title
                # Also check for exact match
                # Try with and without parenthetical content
                if (clean_search == icon_stem or
                    clean_search_no_parens == icon_stem or
                    clean_search in icon_stem or
                    clean_search_no_parens in icon_stem or
                    icon_stem in clean_search or
                    icon_stem in clean_search_no_parens or
                    # Handle case where folder uses abbreviated name
                    (len(clean_search_no_parens) > 3 and len(icon_stem) > 3 and
                     (clean_search_no_parens[:len(icon_stem)] == icon_stem or
                      icon_stem[:len(clean_search_no_parens)] == clean_search_no_parens))):
                    icon_path = existing_path
                    icons_found += 1
                    is_device = str(existing_path).startswith("device:")
                    if is_device and filtered_count <= 5:
                        print(f"[DEBUG] MATCHED game '{title}' with device icon: {icon_stem}")
                    break

            # Create game card widget (pass relative_path for deep search support)
            card = GameCardWidget(title, str(path), platform_key, icon_path, relative_path)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            card.selection_changed.connect(self._on_card_selection_changed)
            card.context_menu_requested.connect(self._on_card_context_menu)

            # Get asset status for this game
            has_icon = clean_search in [s.lower().replace(" ", "") for s in asset_status.get("icons", [])]
            has_hero = clean_search in [s.lower().replace(" ", "") for s in asset_status.get("heroes", [])]
            has_logo = clean_search in [s.lower().replace(" ", "") for s in asset_status.get("logos", [])]

            # Also check based on icon_path match
            if icon_path:
                has_icon = True

            card.update_asset_status(has_icon, has_hero, has_logo)

            # Track missing assets
            if not has_icon:
                missing_icons += 1
            if not has_hero:
                missing_heroes += 1
            if not has_logo:
                missing_logos += 1

            # Select by default
            card.set_selected(True)

            # Add to grid
            self.games_grid_layout.addWidget(card, row, col)
            self._game_cards.append(card)

            col += 1
            if col >= cols:
                col = 0
                row += 1

        # Update missing count label
        total_missing = missing_icons + missing_heroes + missing_logos
        self.missing_count_label.setText(f"{total_missing} missing assets")

        # Build region stats
        region_stats = ", ".join(f"{k}: {v}" for k, v in sorted(region_counts.items()) if k != "Unknown")
        icon_info = f" | {icons_found} icons found" if icons_found > 0 else ""
        if region_filter != "any":
            self.games_info.setText(f"{filtered_count}/{len(games)} games in {platform_key} (filtered: {region_filter}){icon_info}")
        else:
            self.games_info.setText(f"{len(games)} games in {platform_key}" + (f" ({region_stats})" if region_stats else "") + icon_info)

        # Start background loading of device icons
        self._start_device_icon_loading(platform_key)

    def _start_device_icon_loading(self, platform_key: str):
        """Start background loading of icons from device for cards that need them."""
        path_text = self.path_input.text().strip()
        if not path_text.startswith("iisu://"):
            return

        # Extract device ID
        path_part = path_text[7:]  # Remove "iisu://"
        parts = path_part.split("/", 1)
        device_id = parts[0] if parts else ""

        # Collect icon requests from cards that have device paths
        icon_requests = []
        for card in self._game_cards:
            if hasattr(card, '_device_icon_path') and card._device_icon_path:
                icon_requests.append((card.title, card._device_icon_path))

        if not icon_requests:
            print(f"[DEBUG] _start_device_icon_loading: No icon requests for {platform_key}")
            return

        print(f"[DEBUG] _start_device_icon_loading: {len(icon_requests)} icons to load for {platform_key}")

        # Cancel any existing icon loader
        if hasattr(self, '_icon_loader_thread') and self._icon_loader_thread:
            if self._icon_loader_thread.isRunning():
                self._icon_loader_worker.cancel()
                self._icon_loader_thread.quit()
                self._icon_loader_thread.wait(1000)

        # Create and start icon loader worker with platform key
        self._icon_loader_thread = QThread()
        self._icon_loader_worker = IconLoaderWorker(device_id, icon_requests, platform_key)
        self._icon_loader_worker.moveToThread(self._icon_loader_thread)

        self._icon_loader_thread.started.connect(self._icon_loader_worker.run)
        self._icon_loader_worker.icon_loaded.connect(self._on_device_icon_loaded)
        self._icon_loader_worker.batch_progress.connect(self._on_icon_load_progress)
        self._icon_loader_worker.finished.connect(self._on_icon_loading_finished)
        self._icon_loader_worker.finished.connect(self._icon_loader_thread.quit)

        self._icon_loader_thread.start()

    def _on_icon_load_progress(self, current: int, total: int):
        """Handle icon loading progress updates."""
        self.games_info.setText(f"Loading device icons: {current}/{total}...")

    def _on_icon_loading_finished(self):
        """Handle icon loading completion - restore info text."""
        # Re-trigger the platform selection to refresh the info text
        current_item = self.platform_tree.currentItem()
        if current_item:
            platform_key = current_item.data(0, Qt.UserRole)
            if platform_key:
                games = current_item.data(0, Qt.UserRole + 1)
                if games:
                    icons_found = sum(1 for card in self._game_cards if card.has_icon)
                    self.games_info.setText(f"{len(games)} games in {platform_key} | {icons_found} icons loaded")

    def _on_device_icon_loaded(self, game_title: str, local_path: str):
        """Handle device icon loaded - update the corresponding card."""
        for card in self._game_cards:
            if card.title == game_title:
                # Update card icon
                pixmap = QPixmap(local_path)
                if not pixmap.isNull():
                    card.image_label.setPixmap(pixmap)
                    card.has_icon = True
                    card._device_icon_path = None  # Clear device path marker
                break

    def _clear_game_grid(self):
        """Clear all game cards from the grid."""
        # Stop any running icon loader
        if hasattr(self, '_icon_loader_thread') and self._icon_loader_thread:
            if self._icon_loader_thread.isRunning():
                self._icon_loader_worker.cancel()
                self._icon_loader_thread.quit()
                self._icon_loader_thread.wait(500)

        for card in self._game_cards:
            card.deleteLater()
        self._game_cards.clear()

        # Clear layout
        while self.games_grid_layout.count():
            item = self.games_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _calculate_grid_columns(self) -> int:
        """Calculate number of columns based on available width - no max limit."""
        card_width = 148  # 140 + spacing
        available_width = self.games_scroll_area.viewport().width()
        if available_width < card_width:
            available_width = 500  # Default fallback
        # Remove the max(6) limit to allow more columns on larger screens
        return max(2, available_width // card_width)

    def _reflow_grid(self):
        """Reflow the grid layout when window is resized."""
        if not self._game_cards:
            return

        # Calculate new column count
        cols = self._calculate_grid_columns()

        # Reorganize cards in the grid
        for i, card in enumerate(self._game_cards):
            row = i // cols
            col = i % cols
            self.games_grid_layout.addWidget(card, row, col)

    def resizeEvent(self, event):
        """Handle resize to reflow the grid."""
        super().resizeEvent(event)
        # Use a timer to debounce the reflow
        if not hasattr(self, '_resize_timer'):
            from PySide6.QtCore import QTimer
            self._resize_timer = QTimer()
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._reflow_grid)
        self._resize_timer.start(100)  # 100ms debounce

    def _load_asset_status(self, platform_key: str) -> dict:
        """Load asset status (which games have icons/heroes/logos) from connected device via ADB.

        For Library tab: ONLY searches device folders, not local output.

        Supported asset file names on device:
        - Icons: icon.png/jpg, slide.png/jpg
        - Heroes: hero.png/jpg, hero_1.png/jpg, hero_2.png/jpg, hero_3.png/jpg
        - Logos: logo.png/jpg, title.png/jpg
        """
        status = {"icons": [], "heroes": [], "logos": []}

        # Only check device assets (Library tab is device-focused)
        path_text = self.path_input.text().strip()
        if path_text.startswith("iisu://"):
            device_status = self._load_device_asset_status(platform_key, path_text)
            # Use device status directly
            for key in ["icons", "heroes", "logos"]:
                for name in device_status.get(key, []):
                    if name not in status[key]:
                        status[key].append(name)

        return status

    def _load_device_asset_status(self, platform_key: str, iisu_path: str) -> dict:
        """Load asset status from connected Android device via ADB using a single fast command.

        Supported asset file names:
        - Icons: icon.*, slide.*
        - Heroes: hero.*, hero_1.*, hero_2.*, hero_3.*
        - Logos: logo.*, title.*
        """
        status = {"icons": [], "heroes": [], "logos": []}

        try:
            from rom_parser import get_adb_path, get_iisu_folder_name
            import subprocess
            import re

            adb_path = get_adb_path()
            if not adb_path:
                return status

            # Extract device ID from path
            path_part = iisu_path[7:]  # Remove "iisu://"
            parts = path_part.split("/", 1)
            device_id = parts[0] if parts else ""

            # Check iiSU assets directory on device
            device_assets_path = "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"

            # Try multiple folder name variations (iiSU uses lowercase shorthand like "gc", "n64")
            folder_variations = [
                get_iisu_folder_name(platform_key),  # e.g., gc for GAMECUBE
                platform_key.lower(),  # e.g., gamecube
                platform_key,  # e.g., GAMECUBE
            ]
            folder_variations = list(dict.fromkeys(folder_variations))  # Remove duplicates

            base_cmd = [adb_path]
            if device_id:
                base_cmd.extend(["-s", device_id])

            kwargs = {'capture_output': True, 'timeout': 15}
            if sys.platform == 'win32':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            # Try each folder variation until we find assets
            for folder_name in folder_variations:
                platform_path = f"{device_assets_path}/{folder_name}"

                # Use a single find command to list all asset files at once
                # Search for icon, slide, slide_*, hero, hero_*, logo, title files
                cmd = base_cmd + ["shell", f"find '{platform_path}' -maxdepth 2 -type f \\( -name 'icon.*' -o -name 'slide.*' -o -name 'slide_*.*' -o -name 'hero.*' -o -name 'hero_*.*' -o -name 'logo.*' -o -name 'title.*' \\) 2>/dev/null"]
                result = subprocess.run(cmd, **kwargs)

                if result.returncode != 0:
                    # Fallback: try ls -R if find fails
                    cmd = base_cmd + ["shell", f"ls -R '{platform_path}' 2>/dev/null"]
                    result = subprocess.run(cmd, **kwargs)
                    if result.returncode != 0:
                        continue  # Try next folder variation

                    # Parse ls -R output
                    output = result.stdout.decode('utf-8', errors='replace')
                    current_folder = ""
                    for line in output.split('\n'):
                        line = line.strip()
                        if line.endswith(':'):
                            # This is a directory path
                            current_folder = line[:-1].split('/')[-1]
                        elif line and current_folder:
                            clean_name = current_folder.lower().replace(" ", "").replace("-", "").replace("_", "")
                            clean_name = re.sub(r'\([^)]*\)', '', clean_name).strip()
                            line_lower = line.lower()

                            # icon.* or slide.* counts as icon
                            if line_lower.startswith('icon.') or line_lower == 'slide.png' or line_lower == 'slide.jpg' or line_lower == 'slide.jpeg':
                                if clean_name not in status["icons"]:
                                    status["icons"].append(clean_name)
                            # hero.*, hero_N.* counts as hero
                            if line_lower.startswith('hero.') or line_lower.startswith('hero_'):
                                if clean_name not in status["heroes"]:
                                    status["heroes"].append(clean_name)
                            # logo.* or title.* counts as logo
                            if line_lower.startswith('logo.') or line_lower.startswith('title.'):
                                if clean_name not in status["logos"]:
                                    status["logos"].append(clean_name)
                else:
                    # Parse find output - each line is a full path like:
                    # /sdcard/.../PLATFORM/GameName/icon.png
                    output = result.stdout.decode('utf-8', errors='replace')
                    print(f"[DEBUG] _load_device_asset_status: find output for {folder_name}: {len(output)} chars")
                    for line in output.strip().split('\n'):
                        line = line.strip()
                        if not line:
                            continue

                        # Extract game folder name and asset type from path
                        # Path format: .../PLATFORM/GameFolder/asset.ext
                        parts = line.split('/')
                        if len(parts) >= 2:
                            game_folder = parts[-2]  # Second to last is game folder
                            asset_file = parts[-1].lower()  # Last is asset filename

                            clean_name = game_folder.lower().replace(" ", "").replace("-", "").replace("_", "")
                            clean_name = re.sub(r'\([^)]*\)', '', clean_name).strip()

                            # icon.* or slide.* (not slide_N) counts as icon
                            if asset_file.startswith('icon.') or asset_file == 'slide.png' or asset_file == 'slide.jpg' or asset_file == 'slide.jpeg':
                                if clean_name not in status["icons"]:
                                    status["icons"].append(clean_name)
                            # hero.*, hero_N.* counts as hero
                            if asset_file.startswith('hero.') or asset_file.startswith('hero_'):
                                if clean_name not in status["heroes"]:
                                    status["heroes"].append(clean_name)
                                    print(f"[DEBUG] Found hero for: {clean_name} (file: {asset_file})")
                            # logo.* or title.* counts as logo
                            if asset_file.startswith('logo.') or asset_file.startswith('title.'):
                                if clean_name not in status["logos"]:
                                    status["logos"].append(clean_name)
                                    print(f"[DEBUG] Found logo for: {clean_name} (file: {asset_file})")

                # If we found assets, don't need to try other folder variations
                if status["icons"] or status["heroes"] or status["logos"]:
                    print(f"[DEBUG] _load_device_asset_status: Found assets in {folder_name}: {len(status['icons'])} icons, {len(status['heroes'])} heroes, {len(status['logos'])} logos")
                    break

        except Exception as e:
            print(f"Error loading device asset status: {e}")
            import traceback
            traceback.print_exc()

        return status

    def _on_card_clicked(self, card: GameCardWidget):
        """Handle game card click."""
        self._update_selection_count()

    def _on_card_double_clicked(self, card: GameCardWidget):
        """Handle game card double-click - start generation for this game."""
        # Select only this card and start processing
        for c in self._game_cards:
            c.set_selected(c == card)
        self._start_processing()

    def _on_card_selection_changed(self, card: GameCardWidget, selected: bool):
        """Handle card selection change."""
        self._update_selection_count()

    def _on_card_context_menu(self, card: GameCardWidget, global_pos):
        """Show context menu for game card."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        menu = QMenu(self)
        menu.setObjectName("context_menu")

        game_data = {
            "title": card.title,
            "platform": card.platform,
            "path": card.path,
            "relative_path": card.relative_path  # For deep search support
        }

        # Generate icon for this game
        action_generate = menu.addAction("Generate Icon")
        action_generate.triggered.connect(lambda: self._generate_single_game(game_data))

        # Generate with interactive selection
        action_interactive = menu.addAction("Generate (Choose Artwork)")
        action_interactive.triggered.connect(lambda: self._generate_single_game(game_data, interactive=True))

        menu.addSeparator()

        # Edit search query - simple text edit
        action_edit_query = menu.addAction("Edit Search Query")
        action_edit_query.triggered.connect(lambda: self._edit_search_query(game_data, card))

        # Search different game - full dialog with autocomplete
        action_search_different = menu.addAction("Manual Search")
        action_search_different.triggered.connect(lambda: self._search_different_game(game_data, card))

        menu.addSeparator()

        # Search on SteamGridDB (web browser)
        action_search_sgdb = menu.addAction("Search on SteamGridDB (Web)")
        action_search_sgdb.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"https://www.steamgriddb.com/search/grids?term={card.title}"))
        )

        # Search on IGDB
        action_search_igdb = menu.addAction("Search on IGDB (Web)")
        action_search_igdb.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"https://www.igdb.com/search?utf8=%E2%9C%93&type=1&q={card.title}"))
        )

        menu.addSeparator()

        # Upload local files submenu
        upload_menu = menu.addMenu("Upload Local File")
        action_upload_icon = upload_menu.addAction("Upload Icon...")
        action_upload_icon.triggered.connect(lambda: self._upload_local_file(game_data, "icon"))
        action_upload_hero = upload_menu.addAction("Upload Hero...")
        action_upload_hero.triggered.connect(lambda: self._upload_local_file(game_data, "hero"))
        action_upload_logo = upload_menu.addAction("Upload Logo...")
        action_upload_logo.triggered.connect(lambda: self._upload_local_file(game_data, "logo"))

        menu.addSeparator()

        # Preview existing assets
        action_preview = menu.addAction("Preview Assets")
        action_preview.triggered.connect(lambda: self._preview_game_assets(game_data))

        # Open game folder (if local)
        if card.path and not card.path.startswith("manual://") and not card.path.startswith("iisu://"):
            action_open_folder = menu.addAction("Open Game Folder")
            action_open_folder.triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(card.path).parent)))
            )

        menu.addSeparator()

        # Delete assets option
        action_delete = menu.addAction("Delete Local Assets")
        action_delete.triggered.connect(lambda: self._delete_game_assets(game_data))

        menu.addSeparator()

        # Hide title option
        action_hide = menu.addAction("Hide Title")
        action_hide.triggered.connect(lambda: self._hide_game(game_data))

        # Show the menu at cursor position
        menu.exec(global_pos)

    def _update_selection_count(self):
        """Update the selection count in the UI."""
        selected = sum(1 for c in self._game_cards if c.is_selected)
        total = len(self._game_cards)
        if selected == total:
            self.games_info.setText(f"All {total} games selected")
        elif selected == 0:
            self.games_info.setText(f"No games selected")
        else:
            self.games_info.setText(f"{selected} of {total} games selected")

    def _set_asset_filter(self, filter_type: str):
        """Set the asset type filter and update filter button states."""
        self._current_asset_filter = filter_type

        # Update button states
        self.filter_all.setChecked(filter_type == "all")
        self.filter_icons.setChecked(filter_type == "icons")
        self.filter_heroes.setChecked(filter_type == "heroes")
        self.filter_logos.setChecked(filter_type == "logos")

        # Apply filter to visible cards
        for card in self._game_cards:
            show = True
            if filter_type == "icons":
                show = not card.has_icon
            elif filter_type == "heroes":
                show = not card.has_hero
            elif filter_type == "logos":
                show = not card.has_logo
            card.setVisible(show)

    def _bulk_generate_all(self):
        """Generate all missing assets for all games."""
        # Select all cards that are missing assets based on current filter
        for card in self._game_cards:
            if self._current_asset_filter == "all":
                card.set_selected(not card.has_icon or not card.has_hero or not card.has_logo)
            elif self._current_asset_filter == "icons":
                card.set_selected(not card.has_icon)
            elif self._current_asset_filter == "heroes":
                card.set_selected(not card.has_hero)
            elif self._current_asset_filter == "logos":
                card.set_selected(not card.has_logo)

        self._update_selection_count()
        self._start_processing()

    def _load_existing_icons(self, platform_key: str) -> list:
        """Load existing icon files from connected device via ADB for a platform.
        Returns a list of tuples: (icon_path, clean_stem_for_matching)

        For Library tab: ONLY searches device folders, not local output.
        Assets on device are in: /sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles/PLATFORM/GameName/

        Supported asset file names: icon, slide (with .png, .jpg, .jpeg extensions)
        """
        icons = []

        # Only load icons from connected device (Library tab is device-focused)
        path_text = self.path_input.text().strip()
        if path_text.startswith("iisu://"):
            device_icons = self._load_device_icons(platform_key, path_text)
            icons.extend(device_icons)

        return icons

    def _load_device_icons(self, platform_key: str, iisu_path: str) -> list:
        """Load existing icons from a connected Android device via ADB.
        Returns a list of tuples: (local_temp_path or device_path, clean_stem_for_matching)

        Searches for any available asset file: icon, slide, hero, title, logo
        with extensions .png, .jpg, .jpeg

        NOTE: This method returns paths for matching purposes. Icons are pulled
        lazily only when already cached, to avoid blocking the UI.
        """
        import tempfile

        icons = []

        # Parse the iisu:// path to get device ID and base path
        # Format: iisu://device_id/path/to/assets
        try:
            path_part = iisu_path[7:]  # Remove "iisu://"
            # Find first slash after device ID
            slash_idx = path_part.find('/')
            if slash_idx == -1:
                return icons

            device_id = path_part[:slash_idx]
            assets_path = path_part[slash_idx:]
        except (ValueError, IndexError):
            return icons

        # Asset file names to search for (in priority order)
        asset_names = ["icon", "slide", "hero", "title", "logo"]
        extensions = [".png", ".jpg", ".jpeg"]

        # Use _iisu_game_info if available to check which games have assets
        # This is populated during the initial scan and is fast to access
        if hasattr(self, '_iisu_game_info') and self._iisu_game_info:
            temp_dir = Path(tempfile.gettempdir()) / "iisu_device_icons" / platform_key

            # Build set of valid platform folder names (lowercase for comparison)
            # iiSU uses lowercase shorthand: switch, n64, gb, gc, ps1, etc.
            from rom_parser import get_iisu_folder_name, FOLDER_TO_PLATFORM
            valid_folders = set()
            valid_folders.add(platform_key.lower())  # e.g., "switch"
            valid_folders.add(get_iisu_folder_name(platform_key).lower())  # e.g., "switch" for SWITCH, "gc" for GAMECUBE

            # Also add any folder that maps to this platform_key in FOLDER_TO_PLATFORM
            for folder, pkey in FOLDER_TO_PLATFORM.items():
                if pkey == platform_key:
                    valid_folders.add(folder.lower())

            print(f"[DEBUG] _load_device_icons: platform_key={platform_key}")
            print(f"[DEBUG] _load_device_icons: valid_folders={valid_folders}")
            print(f"[DEBUG] _load_device_icons: _iisu_game_info has {len(self._iisu_game_info)} entries")

            matched_count = 0
            for game_path, info in self._iisu_game_info.items():
                # Check if this game is in the current platform and has any asset
                files = info.get("files", [])
                has_any_asset = info.get("has_icon") or info.get("has_slide") or info.get("has_hero") or info.get("has_logo") or info.get("has_title") or len(files) > 0

                # Extract platform folder from path and check if it matches
                # Path format: /sdcard/.../consoles/PlatformFolder/GameName
                path_parts = game_path.rstrip('/').split('/')
                if len(path_parts) >= 2:
                    platform_folder = path_parts[-2].lower()  # Second to last is platform folder
                    matches_platform = platform_folder in valid_folders
                else:
                    matches_platform = False

                if has_any_asset and matches_platform:
                    matched_count += 1
                    if matched_count <= 3:  # Only print first 3 matches
                        print(f"[DEBUG] _load_device_icons: MATCHED game_path={game_path}, files={files}")
                    # Extract game name from path
                    game_name = game_path.rstrip('/').split('/')[-1]
                    # Clean stem same way as ROM titles: keep only alnum, then remove spaces/dashes/underscores
                    clean_game_name = "".join(c for c in game_name if c.isalnum() or c in " -_").strip()
                    clean_stem = clean_game_name.lower().replace(" ", "").replace("-", "").replace("_", "")

                    # Check if we already have a cached copy (check all extensions)
                    cached_path = None
                    for ext in extensions:
                        local_icon_path = temp_dir / f"{game_name}{ext}"
                        if local_icon_path.exists():
                            cached_path = local_icon_path
                            break

                    if cached_path:
                        icons.append((cached_path, clean_stem))
                    else:
                        # Determine which asset file to use (priority order)
                        asset_file = None
                        for asset_name in asset_names:
                            if asset_name in files:
                                # Use png extension by default, actual file will be found when pulled
                                asset_file = f"{asset_name}.png"
                                break

                        if asset_file:
                            # Mark as having asset (for status display) but use device path marker
                            # The actual icon will be pulled later if needed
                            icons.append((f"device:{game_path}/{asset_file}", clean_stem))

            print(f"[DEBUG] _load_device_icons: Found {matched_count} games with assets, returning {len(icons)} icons")

        return icons

    def _on_region_changed(self, index):
        """Handle region filter change - refresh the current platform's games list."""
        current_item = self.platform_tree.currentItem()
        if current_item:
            self._on_platform_selected(current_item, 0)

    def _show_platform_context_menu(self, position):
        """Show right-click context menu for platform items."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        item = self.platform_tree.itemAt(position)
        if not item:
            return

        platform_key = item.data(0, Qt.UserRole)
        games = item.data(0, Qt.UserRole + 1)

        if not platform_key or not games:
            return

        menu = QMenu(self)
        menu.setObjectName("context_menu")

        # Generate icons for all games in platform
        action_generate_all = menu.addAction(f"Generate All Icons ({len(games)} games)")
        action_generate_all.triggered.connect(lambda: self._generate_platform(platform_key, games))

        # Generate missing icons only
        action_generate_missing = menu.addAction("Generate Missing Icons Only")
        action_generate_missing.triggered.connect(lambda: self._generate_platform_missing(platform_key, games))

        menu.addSeparator()

        # Select all games in this platform
        action_select_all = menu.addAction("Select All Games")
        action_select_all.triggered.connect(self._select_all_games)

        # Deselect all games
        action_select_none = menu.addAction("Deselect All Games")
        action_select_none.triggered.connect(self._select_no_games)

        menu.addSeparator()

        # Open platform output folder
        action_open_output = menu.addAction("Open Output Folder")
        action_open_output.triggered.connect(lambda: self._open_platform_output(platform_key))

        # Delete all assets for platform
        action_delete_all = menu.addAction(f"Delete All {platform_key} Assets")
        action_delete_all.triggered.connect(lambda: self._delete_platform_assets(platform_key))

        menu.exec(self.platform_tree.mapToGlobal(position))

    def _generate_platform(self, platform_key: str, games: List[Tuple[str, str]]):
        """Generate icons for all games in a platform."""
        # Select all games in this platform
        self._select_all_games()
        # Start processing
        self._start_processing()

    def _generate_platform_missing(self, platform_key: str, games: List[Tuple[str, str]]):
        """Generate icons only for games that don't have one yet."""
        # Load config to get output directory
        output_dir = Path("./output")
        try:
            cfg = get_config()
            output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception:
            pass

        platform_dir = output_dir / platform_key
        existing_icons = set()

        if platform_dir.exists():
            for ext in ["*.png", "*.jpg", "*.jpeg"]:
                for file in platform_dir.glob(ext):
                    # Store cleaned filename for comparison
                    existing_icons.add(file.stem.lower().replace(" ", ""))

        # Select only games without existing icons
        missing_count = 0
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            data = item.data(Qt.UserRole)
            title = data.get("title", "")
            clean_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
            clean_search = clean_title.lower().replace(" ", "")

            # Check if this game has an existing icon
            has_icon = any(clean_search in existing for existing in existing_icons)
            item.setSelected(not has_icon)
            if not has_icon:
                missing_count += 1

        if missing_count == 0:
            QMessageBox.information(
                self, "All Icons Present",
                f"All games in {platform_key} already have icons generated."
            )
            return

        QMessageBox.information(
            self, "Missing Icons Selected",
            f"Selected {missing_count} games without icons.\n\nClick 'Generate Icons' to create them."
        )

    def _open_platform_output(self, platform_key: str):
        """Open the output folder for a platform."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        output_dir = Path("./output")
        try:
            cfg = get_config()
            output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception:
            pass

        platform_dir = output_dir / platform_key
        if not platform_dir.exists():
            platform_dir.mkdir(parents=True, exist_ok=True)

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(platform_dir.absolute())))

    def _delete_platform_assets(self, platform_key: str):
        """Delete all generated assets for a platform."""
        reply = QMessageBox.question(
            self,
            "Delete Platform Assets",
            f"Delete ALL generated assets for {platform_key}?\n\n"
            f"This will remove all icons, heroes, and other generated files.\n"
            f"This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        output_dir = Path("./output")
        try:
            cfg = get_config()
            output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception:
            pass

        platform_dir = output_dir / platform_key
        if not platform_dir.exists():
            QMessageBox.information(self, "No Assets", f"No assets folder found for {platform_key}.")
            return

        deleted_count = 0
        for ext in ["*.png", "*.jpg", "*.jpeg"]:
            for file in platform_dir.glob(ext):
                try:
                    file.unlink()
                    deleted_count += 1
                except Exception as e:
                    self._on_log(f"Failed to delete {file.name}: {e}")

        QMessageBox.information(
            self, "Assets Deleted",
            f"Deleted {deleted_count} asset file(s) from {platform_key}."
        )

    def _filter_games(self, text):
        """Filter game cards by search text."""
        search_lower = text.lower()

        for card in self._game_cards:
            title_lower = card.title.lower()
            # Show card if it matches search text
            # Also respect the current asset filter
            matches_search = search_lower in title_lower
            matches_filter = True
            if self._current_asset_filter == "icons":
                matches_filter = not card.has_icon
            elif self._current_asset_filter == "heroes":
                matches_filter = not card.has_hero
            elif self._current_asset_filter == "logos":
                matches_filter = not card.has_logo
            card.setVisible(matches_search and matches_filter)

    def _select_all_games(self):
        """Select all visible game cards."""
        for card in self._game_cards:
            if card.isVisible():
                card.set_selected(True)
        self._update_selection_count()

    def _select_no_games(self):
        """Deselect all game cards."""
        for card in self._game_cards:
            card.set_selected(False)
        self._update_selection_count()

    def _show_game_context_menu(self, position):
        """Show right-click context menu for game items."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        item = self.games_list.itemAt(position)
        if not item:
            return

        data = item.data(Qt.UserRole)
        if not data:
            return

        title = data.get("title", "Unknown")
        platform = data.get("platform", "")
        path = data.get("path", "")

        menu = QMenu(self)
        menu.setObjectName("context_menu")

        # Generate icon for this game
        action_generate = menu.addAction("Generate Icon")
        action_generate.triggered.connect(lambda: self._generate_single_game(data))

        # Generate with interactive selection
        action_interactive = menu.addAction("Generate (Choose Artwork)")
        action_interactive.triggered.connect(lambda: self._generate_single_game(data, interactive=True))

        menu.addSeparator()

        # Search on SteamGridDB
        action_search_sgdb = menu.addAction("Search on SteamGridDB")
        action_search_sgdb.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"https://www.steamgriddb.com/search/grids?term={title}"))
        )

        # Search on IGDB
        action_search_igdb = menu.addAction("Search on IGDB")
        action_search_igdb.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"https://www.igdb.com/search?utf8=%E2%9C%93&type=1&q={title}"))
        )

        menu.addSeparator()

        # Preview existing assets
        action_preview = menu.addAction("Preview Assets")
        action_preview.triggered.connect(lambda: self._preview_game_assets(data))

        # Open game folder (if local)
        if path and not path.startswith("manual://") and not path.startswith("iisu://"):
            action_open_folder = menu.addAction("Open Game Folder")
            action_open_folder.triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
            )

        menu.addSeparator()

        # Delete assets option
        action_delete = menu.addAction("Delete Local Assets")
        action_delete.triggered.connect(lambda: self._delete_game_assets(data))

        menu.addSeparator()

        # Hide title option
        action_hide = menu.addAction("Hide Title")
        action_hide.triggered.connect(lambda: self._hide_game(data))

        # Show the menu at cursor position
        menu.exec(self.games_list.mapToGlobal(position))

    def _generate_single_game(self, game_data: Dict, interactive: bool = False,
                               search_term: str = None, sgdb_game_id: int = None):
        """Generate icon for a single game.

        Args:
            game_data: Dict with title, platform, path
            interactive: If True, show artwork picker dialog
            search_term: Custom search term to use instead of title
            sgdb_game_id: Specific SteamGridDB game ID to use
        """
        title = game_data.get("title", "")
        platform = game_data.get("platform", "")

        if not title or not platform:
            return

        # Set interactive mode temporarily
        original_interactive = self.interactive_check.isChecked()
        self.interactive_check.setChecked(interactive)

        # Store custom search parameters for this generation
        self._single_game_search_term = search_term
        self._single_game_sgdb_id = sgdb_game_id

        # Select only this game in the card view
        for card in self._game_cards:
            if card.title == title:
                card.set_selected(True)
            else:
                card.set_selected(False)

        # Also select in list view if it exists
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            item_data = item.data(Qt.UserRole)
            if item_data and item_data.get("title") == title:
                item.setSelected(True)
            else:
                item.setSelected(False)

        # Start processing
        self._start_processing()

        # Restore interactive setting
        self.interactive_check.setChecked(original_interactive)

        # Clear custom search parameters
        self._single_game_search_term = None
        self._single_game_sgdb_id = None

    def _preview_game_assets(self, game_data: Dict):
        """Preview existing assets for a game from local output or device."""
        from PySide6.QtWidgets import QDialog, QGridLayout, QDialogButtonBox, QTabWidget
        from PySide6.QtGui import QPixmap
        from rom_parser import get_iisu_folder_name
        import tempfile

        title = game_data.get("title", "Unknown")
        platform = game_data.get("platform", "")

        # Clean title for folder/filename matching
        clean_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        clean_title_match = clean_title.lower().replace(" ", "").replace("-", "").replace("_", "")

        # Load config to get output directory
        output_dir = Path("./output")
        try:
            cfg = get_config()
            output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception:
            pass

        # Collect assets from local and device
        local_assets = {"icon": [], "hero": [], "logo": [], "screenshot": []}
        device_assets = {"icon": [], "hero": [], "logo": [], "screenshot": []}

        # Check multiple folder name variations
        folder_variations = [
            platform,
            platform.lower(),
            get_iisu_folder_name(platform),
        ]
        folder_variations = list(dict.fromkeys(folder_variations))

        # Search local output directory
        for folder_name in folder_variations:
            platform_dir = output_dir / folder_name
            if not platform_dir.exists():
                continue

            # Look for game folder matching title
            for game_folder in platform_dir.iterdir():
                if game_folder.is_dir():
                    folder_match = game_folder.name.lower().replace(" ", "").replace("-", "").replace("_", "")
                    if clean_title_match in folder_match or folder_match in clean_title_match:
                        # Found matching game folder - look for assets
                        for ext in [".png", ".jpg", ".jpeg"]:
                            # Icons
                            for name in ["icon", "slide"]:
                                asset_path = game_folder / f"{name}{ext}"
                                if asset_path.exists() and asset_path not in local_assets["icon"]:
                                    local_assets["icon"].append(asset_path)
                            # Heroes
                            for name in ["hero", "hero_1", "hero_2", "hero_3"]:
                                asset_path = game_folder / f"{name}{ext}"
                                if asset_path.exists() and asset_path not in local_assets["hero"]:
                                    local_assets["hero"].append(asset_path)
                            # Logos
                            for name in ["logo", "title"]:
                                asset_path = game_folder / f"{name}{ext}"
                                if asset_path.exists() and asset_path not in local_assets["logo"]:
                                    local_assets["logo"].append(asset_path)
                            # Screenshots
                            for i in range(1, 10):
                                asset_path = game_folder / f"slide_{i}{ext}"
                                if asset_path.exists() and asset_path not in local_assets["screenshot"]:
                                    local_assets["screenshot"].append(asset_path)

            # Also check for flat files (old structure)
            for ext in [".png", ".jpg", ".jpeg"]:
                for file in platform_dir.glob(f"*{ext}"):
                    if file.is_file():
                        file_match = file.stem.lower().replace(" ", "").replace("-", "").replace("_", "")
                        if clean_title_match in file_match or file_match in clean_title_match:
                            if file not in local_assets["icon"]:
                                local_assets["icon"].append(file)

        # Check device assets if using iisu:// path
        path_text = self.path_input.text().strip()
        if path_text.startswith("iisu://"):
            device_assets = self._load_device_assets_for_game(platform, clean_title_match, path_text)

        # Count total assets
        total_local = sum(len(v) for v in local_assets.values())
        total_device = sum(len(v) for v in device_assets.values())

        if total_local == 0 and total_device == 0:
            QMessageBox.information(
                self, "No Assets",
                f"No assets found for '{title}'.\n\n"
                f"Generate icons first or check device connection."
            )
            return

        # Show preview dialog with tabs for local/device
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Assets: {title}")
        dialog.setMinimumSize(600, 500)

        layout = QVBoxLayout(dialog)

        # Create tab widget if we have both local and device assets
        if total_local > 0 and total_device > 0:
            tabs = QTabWidget()
            tabs.addTab(self._create_asset_preview_widget(local_assets, "Local"), f"Local ({total_local})")
            tabs.addTab(self._create_asset_preview_widget(device_assets, "Device"), f"Device ({total_device})")
            layout.addWidget(tabs, 1)
        elif total_local > 0:
            layout.addWidget(QLabel(f"Found {total_local} local asset(s):"))
            layout.addWidget(self._create_asset_preview_widget(local_assets, "Local"), 1)
        else:
            layout.addWidget(QLabel(f"Found {total_device} device asset(s):"))
            layout.addWidget(self._create_asset_preview_widget(device_assets, "Device"), 1)

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec()

    def _create_asset_preview_widget(self, assets: Dict, source: str) -> QWidget:
        """Create a widget showing asset previews organized by type."""
        from PySide6.QtWidgets import QGridLayout, QGroupBox
        from PySide6.QtGui import QPixmap

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(12)

        asset_type_labels = {
            "icon": "Icons",
            "hero": "Heroes",
            "logo": "Logos",
            "screenshot": "Screenshots"
        }

        for asset_type, label in asset_type_labels.items():
            asset_list = assets.get(asset_type, [])
            if not asset_list:
                continue

            group = QGroupBox(f"{label} ({len(asset_list)})")
            grid = QGridLayout(group)
            grid.setSpacing(8)

            for i, asset_item in enumerate(asset_list[:8]):  # Limit to 8 per type
                preview = QLabel()
                # Adjust size based on asset type
                if asset_type == "hero":
                    preview.setFixedSize(200, 65)
                elif asset_type == "screenshot":
                    preview.setFixedSize(160, 90)
                else:
                    preview.setFixedSize(100, 100)
                preview.setScaledContents(True)
                preview.setObjectName("rom_preview_label")

                # Load image - asset_item can be Path (local) or bytes (device)
                if isinstance(asset_item, Path):
                    pixmap = QPixmap(str(asset_item))
                    tooltip = asset_item.name
                elif isinstance(asset_item, tuple):
                    # (filename, bytes_data)
                    filename, img_bytes = asset_item
                    pixmap = QPixmap()
                    pixmap.loadFromData(img_bytes)
                    tooltip = filename
                else:
                    continue

                if not pixmap.isNull():
                    preview.setPixmap(pixmap)
                    preview.setToolTip(tooltip)
                else:
                    preview.setText("Error")

                row = i // 4
                col = i % 4
                grid.addWidget(preview, row, col)

            main_layout.addWidget(group)

        main_layout.addStretch()
        return container

    def _load_device_assets_for_game(self, platform_key: str, clean_title_match: str, iisu_path: str) -> Dict:
        """Load actual asset files from device for a specific game."""
        from rom_parser import get_adb_path, get_iisu_folder_name
        import subprocess

        assets = {"icon": [], "hero": [], "logo": [], "screenshot": []}

        print(f"[DEBUG] _load_device_assets_for_game: platform={platform_key}, title_match={clean_title_match}, path={iisu_path}")

        try:
            adb_path = get_adb_path()
            if not adb_path:
                print(f"[DEBUG] _load_device_assets_for_game: No ADB path found")
                return assets

            # Extract device ID from path
            path_part = iisu_path[7:]  # Remove "iisu://"
            parts = path_part.split("/", 1)
            device_id = parts[0] if parts else ""

            print(f"[DEBUG] _load_device_assets_for_game: device_id={device_id}")

            device_assets_path = "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"

            base_cmd = [adb_path]
            if device_id:
                base_cmd.extend(["-s", device_id])

            kwargs = {'capture_output': True, 'timeout': 15}
            if sys.platform == 'win32':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            # Try multiple platform folder names
            folder_variations = [
                platform_key,
                platform_key.lower(),
                get_iisu_folder_name(platform_key),
            ]
            folder_variations = list(dict.fromkeys(folder_variations))

            for folder_name in folder_variations:
                platform_path = f"{device_assets_path}/{folder_name}"
                print(f"[DEBUG] Trying platform path: {platform_path}")

                # List game folders
                cmd = base_cmd + ["shell", f"ls '{platform_path}' 2>/dev/null"]
                result = subprocess.run(cmd, **kwargs)
                if result.returncode != 0:
                    print(f"[DEBUG] ls failed for {platform_path}")
                    continue

                output = result.stdout.decode('utf-8', errors='replace')
                game_folders = [g.strip() for g in output.strip().split('\n') if g.strip()]
                print(f"[DEBUG] Found {len(game_folders)} game folders in {folder_name}")

                for game_folder in game_folders:
                    folder_match = game_folder.lower().replace(" ", "").replace("-", "").replace("_", "")
                    if clean_title_match not in folder_match and folder_match not in clean_title_match:
                        continue

                    print(f"[DEBUG] Matched game folder: {game_folder}")

                    # Found matching game folder - list its contents
                    game_path = f"{platform_path}/{game_folder}"
                    cmd = base_cmd + ["shell", f"ls '{game_path}' 2>/dev/null"]
                    result = subprocess.run(cmd, **kwargs)
                    if result.returncode != 0:
                        continue

                    files = result.stdout.decode('utf-8', errors='replace').strip().split('\n')
                    print(f"[DEBUG] Files in game folder: {files}")

                    for filename in files:
                        filename = filename.strip()
                        if not filename:
                            continue
                        fname_lower = filename.lower()

                        # Determine asset type
                        asset_type = None
                        if fname_lower.startswith('icon.') or fname_lower == 'slide.png' or fname_lower == 'slide.jpg':
                            asset_type = "icon"
                        elif fname_lower.startswith('hero.') or fname_lower.startswith('hero_'):
                            asset_type = "hero"
                        elif fname_lower.startswith('logo.') or fname_lower.startswith('title.'):
                            asset_type = "logo"
                        elif fname_lower.startswith('slide_'):
                            asset_type = "screenshot"

                        if asset_type:
                            print(f"[DEBUG] Found asset: {filename} -> {asset_type}")
                            # Pull the file from device
                            remote_path = f"{game_path}/{filename}"
                            cmd = base_cmd + ["shell", f"cat '{remote_path}'"]
                            result = subprocess.run(cmd, capture_output=True, timeout=10,
                                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                            if result.returncode == 0 and result.stdout:
                                assets[asset_type].append((filename, result.stdout))
                                print(f"[DEBUG] Pulled {len(result.stdout)} bytes for {filename}")

                # If we found assets, don't check other folder variations
                if any(assets[k] for k in assets):
                    print(f"[DEBUG] Found assets in {folder_name}, stopping search")
                    break

        except Exception as e:
            print(f"Error loading device assets: {e}")
            import traceback
            traceback.print_exc()

        print(f"[DEBUG] _load_device_assets_for_game result: {sum(len(v) for v in assets.values())} total assets")
        return assets

    def _upload_local_file(self, game_data: Dict, asset_type: str):
        """Upload a local image file as an icon, hero, or logo for a game."""
        from PySide6.QtWidgets import QFileDialog
        from rom_parser import get_iisu_folder_name
        import shutil
        from PIL import Image

        title = game_data.get("title", "Unknown")
        platform = game_data.get("platform", "")

        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {asset_type.title()} Image for '{title}'",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;All Files (*)"
        )

        if not file_path:
            return

        # Load config to get output directory
        output_dir = Path("./output")
        try:
            cfg = get_config()
            output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception:
            pass

        # Create platform and game folder structure
        platform_folder_name = get_iisu_folder_name(platform)
        clean_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        game_folder = output_dir / platform_folder_name / clean_title
        game_folder.mkdir(parents=True, exist_ok=True)

        # Determine output filename based on asset type
        output_filename = f"{asset_type}.png"
        output_path = game_folder / output_filename

        try:
            # Load and convert image to PNG
            with Image.open(file_path) as img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Keep alpha channel for images that have it
                    img = img.convert('RGBA')
                else:
                    img = img.convert('RGB')

                img.save(output_path, 'PNG', quality=100)

            self._on_log(f"Uploaded {asset_type} for '{title}': {output_path}")
            QMessageBox.information(
                self,
                "Upload Complete",
                f"{asset_type.title()} uploaded successfully for '{title}'.\n\n"
                f"Saved to: {output_path}"
            )

            # Refresh the card's asset status
            for card in self._game_cards:
                if card.title == title and card.platform == platform:
                    if asset_type == "icon":
                        card.update_asset_status(True, card.has_hero, card.has_logo)
                    elif asset_type == "hero":
                        card.update_asset_status(card.has_icon, True, card.has_logo)
                    elif asset_type == "logo":
                        card.update_asset_status(card.has_icon, card.has_hero, True)
                    break

        except Exception as e:
            self._on_log(f"Failed to upload {asset_type}: {e}")
            QMessageBox.warning(
                self,
                "Upload Failed",
                f"Failed to upload {asset_type} for '{title}':\n{e}"
            )

    def _delete_game_assets(self, game_data: Dict):
        """Delete locally generated assets for a game."""
        title = game_data.get("title", "Unknown")
        platform = game_data.get("platform", "")

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Delete Assets",
            f"Delete all generated assets for '{title}'?\n\n"
            f"This will remove icons, heroes, and other generated files.\n"
            f"This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Load config to get output directory
        output_dir = Path("./output")
        try:
            cfg = get_config()
            output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception:
            pass

        # Find and delete assets
        platform_dir = output_dir / platform
        if not platform_dir.exists():
            QMessageBox.information(self, "No Assets", "No assets found to delete.")
            return

        clean_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        deleted_count = 0

        for ext in ["*.png", "*.jpg", "*.jpeg"]:
            for file in platform_dir.glob(ext):
                if clean_title.lower().replace(" ", "") in file.stem.lower().replace(" ", ""):
                    try:
                        file.unlink()
                        deleted_count += 1
                        self._on_log(f"Deleted: {file.name}")
                    except Exception as e:
                        self._on_log(f"Failed to delete {file.name}: {e}")

        if deleted_count > 0:
            QMessageBox.information(
                self, "Assets Deleted",
                f"Deleted {deleted_count} asset file(s) for '{title}'."
            )
        else:
            QMessageBox.information(self, "No Assets", "No matching assets found to delete.")

    def _get_selected_games(self) -> List[Dict]:
        """Get list of selected games with their data from game cards."""
        selected = []
        for card in self._game_cards:
            if card.is_selected and card.isVisible():
                selected.append({
                    "title": card.title,
                    "path": card.path,
                    "platform": card.platform,
                    "relative_path": card.relative_path  # For deep search support
                })
        return selected

    def _start_processing(self):
        """Start processing selected games."""
        selected = self._get_selected_games()

        if not selected:
            QMessageBox.information(self, "No Selection", "Please select games to process.")
            return

        # Show confirmation dialog for mass generation
        count = len(selected)
        reply = QMessageBox.question(
            self,
            "Confirm Generation",
            f"Are you sure you want to generate assets for {count} game{'s' if count != 1 else ''}?\n\n"
            f"This will scrape artwork and create icons for all selected games.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Group by platform - store full game info for relative_path support
        by_platform: Dict[str, List[Dict]] = {}
        for game in selected:
            plat = game["platform"]
            if plat not in by_platform:
                by_platform[plat] = []
            by_platform[plat].append(game)

        # Load config for processing
        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            QMessageBox.warning(self, "Config Missing", "Configuration file not found.")
            return

        self.progress.setValue(0)
        self.btn_process.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status_label.setText("Processing...")
        self._clear_preview()

        self._cancel_token = run_backend.CancelToken()
        callbacks = BackendCallbacks()
        callbacks.progress.connect(self._on_progress)
        callbacks.log.connect(self._on_log)
        callbacks.finished.connect(self._on_finished)
        callbacks.preview.connect(self._add_preview)
        callbacks.current_item.connect(self._on_current_item)

        # Calculate total games across all platforms
        total_games = sum(len(games) for games in by_platform.values())

        # Process each platform's games
        def _run():
            try:
                done_count = 0
                for platform_key, games in by_platform.items():
                    if self._cancel_token.is_cancelled:
                        break

                    for game_info in games:
                        if self._cancel_token.is_cancelled:
                            break

                        title = game_info.get("title", "")
                        relative_path = game_info.get("relative_path")  # For deep search support

                        # Emit current item being processed
                        callbacks.current_item.emit(title, platform_key)
                        callbacks.progress.emit(done_count, total_games)

                        # Check for custom search parameters (from Edit Search Query / Manual Search)
                        custom_search = getattr(self, '_single_game_search_term', None)
                        custom_sgdb_id = getattr(self, '_single_game_sgdb_id', None)
                        search_for = custom_search if custom_search else title

                        # For Library tab: auto-enable copy to device when using iisu:// path
                        path_text = self.path_input.text().strip()
                        auto_copy_to_device = path_text.startswith("iisu://")

                        # Convert iisu:// path to actual device path for ADB push
                        # Format: iisu://device_id/rest/of/path -> extract device_id, use standard iiSU assets path
                        device_path_for_copy = ""
                        device_id_for_copy = None
                        if auto_copy_to_device:
                            # Extract device ID from iisu:// path
                            path_part = path_text[7:]  # Remove "iisu://"
                            parts = path_part.split("/", 1)
                            device_id_for_copy = parts[0] if parts else None
                            # Standard iiSU assets path on device
                            device_path_for_copy = "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"
                        else:
                            device_path_for_copy = self.device_settings.get("path", "")

                        # Process single game - limit=1 ensures only one icon per ROM
                        ok, msg = run_backend.run_job(
                            config_path=cfg_path,
                            platforms=[platform_key],
                            workers=1,
                            limit=1,  # Only generate one icon per scanned ROM
                            cancel=self._cancel_token,
                            callbacks={
                                "log": lambda m: callbacks.log.emit(str(m)),
                                "preview": lambda p: callbacks.preview.emit(str(p)),
                                "request_selection": self._request_artwork_selection,
                            },
                            search_term=search_for,
                            interactive_mode=self.interactive_check.isChecked(),
                            download_heroes=self.hero_check.isChecked(),
                            hero_count=1,  # Only one hero image per ROM
                            fallback_settings=self.fallback_settings,
                            download_screenshots=self.screenshot_settings.get("enabled", False),
                            screenshot_count=self.screenshot_settings.get("count", 3),
                            copy_to_device=auto_copy_to_device or self.device_settings.get("enabled", False),
                            device_path=device_path_for_copy,
                            scrape_logos=self.logo_settings.get("scrape_logos", True),
                            logo_fallback_to_boxart=self.logo_settings.get("fallback_to_boxart", True),
                            sgdb_game_id=custom_sgdb_id,  # Use specific SGDB game ID if provided
                            device_id=device_id_for_copy,  # Pass device ID for ADB push
                            game_relative_path=relative_path  # For deep search: include subdirectory in output path
                        )

                        done_count += 1
                        callbacks.progress.emit(done_count, total_games)

                callbacks.finished.emit(True, "Processing complete")

            except Exception as e:
                callbacks.finished.emit(False, f"Error: {e}")

        self._worker_thread = threading.Thread(target=_run, daemon=True)
        self._worker_thread.start()

    def _cancel_processing(self):
        """Cancel ongoing processing."""
        if self._cancel_token:
            self._cancel_token.cancel()
            self.status_label.setText("Cancelling...")
        self.btn_cancel.setEnabled(False)

    def _on_progress(self, done: int, total: int):
        """Handle progress update."""
        if total > 0:
            pct = int((done / total) * 100)
            self.progress.setValue(pct)
            self.progress.setFormat(f"{done}/{total} ({pct}%)")

    def _on_current_item(self, title: str, platform: str):
        """Handle current item update - show what's being processed."""
        # Truncate long titles for display
        display_title = title if len(title) <= 40 else title[:37] + "..."
        self.status_label.setText(f"Processing: {display_title} [{platform}]")

    def _on_log(self, msg: str):
        """Handle log message."""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {msg}"
        self._log_messages.append(log_entry)
        # Keep last 1000 messages
        if len(self._log_messages) > 1000:
            self._log_messages = self._log_messages[-1000:]
        # Print to console as well
        print(log_entry)

    # ---------- Interactive mode ----------
    def _request_artwork_selection(self, title: str, platform: str, artwork_options):
        """
        Request user to select artwork from options.
        Called from worker thread, so must use thread-safe Qt mechanisms.
        Returns selected index, None if skipped, -1 if cancelled all.
        """
        from artwork_picker_dialog import ArtworkPickerDialog
        from queue import Queue
        from PySide6.QtCore import QMetaObject, Qt

        self._on_log(f"[INTERACTIVE] Request for {title} with {len(artwork_options)} options")

        # Store data in instance variables so main thread can access them
        self._dialog_title = title
        self._dialog_platform = platform
        self._dialog_options = artwork_options
        self._dialog_result = Queue()

        # Use QMetaObject.invokeMethod to run on main thread
        QMetaObject.invokeMethod(
            self,
            "_show_selection_dialog_on_main_thread",
            Qt.ConnectionType.BlockingQueuedConnection
        )

        # Get result from queue
        result = self._dialog_result.get()
        self._on_log(f"[INTERACTIVE] Got result: {result}")
        return result

    @Slot()
    def _show_selection_dialog_on_main_thread(self):
        """Show dialog on main thread - called via invokeMethod."""
        from artwork_picker_dialog import ArtworkPickerDialog
        try:
            self._on_log(f"[INTERACTIVE] Showing dialog for {self._dialog_title}")

            # Show filter toggle for icon selection
            dialog = ArtworkPickerDialog(
                title=self._dialog_title,
                platform=self._dialog_platform,
                artwork_options=self._dialog_options,
                parent=self,
                asset_type="icon",
                show_filter=True
            )

            # Show dialog modally
            dialog_result = dialog.exec()
            selected = dialog.get_selected_index()

            self._on_log(f"[INTERACTIVE] Dialog result: exec={dialog_result}, selected={selected}")
            self._dialog_result.put(selected)

        except Exception as e:
            import traceback
            self._on_log(f"[ERROR] Dialog exception: {e}")
            self._on_log(f"[ERROR] Traceback: {traceback.format_exc()}")
            self._dialog_result.put(None)

    def _on_finished(self, ok: bool, msg: str):
        """Handle processing completion."""
        self.btn_process.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.status_label.setText(msg if ok else f"Failed: {msg}")

        if ok:
            self.progress.setValue(100)
            self.progress.setFormat("Complete")
            # Auto-refresh the displayed assets to show newly generated ones
            self._refresh_current_platform_assets()

    def _add_preview(self, path: str):
        """Add a generated icon to the preview grid."""
        path_obj = Path(path)
        if not path_obj.exists():
            return

        label = QLabel()
        label.setFixedSize(128, 128)  # Larger preview icons
        label.setScaledContents(True)
        label.setObjectName("rom_preview_label")

        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(pixmap)
            label.setToolTip(path_obj.stem)

            row = len(self.preview_items) // 6  # 6 per row for larger icons
            col = len(self.preview_items) % 6
            self.preview_grid.addWidget(label, row, col)
            self.preview_items.append(label)

            # Also add to popout window if open
            self._add_preview_to_popout(path)

    def _clear_preview(self):
        """Clear preview grid."""
        for item in self.preview_items:
            self.preview_grid.removeWidget(item)
            item.deleteLater()
        self.preview_items.clear()

    def _refresh_current_platform_assets(self):
        """Refresh the current platform's game cards to show newly generated assets.

        Called after processing completes to update the displayed icons/asset badges
        without requiring a full rescan. For Library tab: only searches device folders via ADB.
        """
        current_item = self.platform_tree.currentItem()
        if not current_item:
            return

        platform_key = current_item.data(0, Qt.UserRole)
        if not platform_key:
            return

        # Reload asset status from device (Library tab only uses device folders)
        asset_status = self._load_asset_status(platform_key)

        print(f"[DEBUG] _refresh_current_platform_assets: Refreshing {len(self._game_cards)} cards for {platform_key}")
        print(f"[DEBUG] Asset status from device: {len(asset_status.get('icons', []))} icons, {len(asset_status.get('heroes', []))} heroes, {len(asset_status.get('logos', []))} logos")

        import re
        for card in self._game_cards:
            # Clean the title for matching (same algorithm as in _on_platform_selected)
            clean_title = "".join(c for c in card.title if c.isalnum() or c in " -_").strip()
            clean_search = clean_title.lower().replace(" ", "").replace("-", "").replace("_", "")
            clean_search_no_parens = re.sub(r'\([^)]*\)', '', clean_search).strip()

            # Check asset status from device - use flexible matching
            def matches_any(clean_name, status_list):
                """Check if clean_name matches any item in status_list using flexible matching."""
                for item in status_list:
                    item_clean = item.lower().replace(" ", "").replace("-", "").replace("_", "")
                    if (clean_name == item_clean or
                        clean_search_no_parens == item_clean or
                        clean_name in item_clean or
                        item_clean in clean_name or
                        clean_search_no_parens in item_clean or
                        item_clean in clean_search_no_parens):
                        return True
                return False

            has_icon = matches_any(clean_search, asset_status.get("icons", []))
            has_hero = matches_any(clean_search, asset_status.get("heroes", []))
            has_logo = matches_any(clean_search, asset_status.get("logos", []))

            # Update card status
            card.has_icon = has_icon
            card.has_hero = has_hero
            card.has_logo = has_logo
            card.update_asset_status(has_icon, has_hero, has_logo)

        # Update status info
        missing_icons = sum(1 for card in self._game_cards if not card.has_icon)
        missing_heroes = sum(1 for card in self._game_cards if not card.has_hero)
        missing_logos = sum(1 for card in self._game_cards if not card.has_logo)
        total_missing = missing_icons + missing_heroes + missing_logos
        self.missing_count_label.setText(f"{total_missing} missing assets")

        print(f"[DEBUG] _refresh_current_platform_assets: missing={total_missing} (icons={missing_icons}, heroes={missing_heroes}, logos={missing_logos})")

    def _open_output(self):
        """Open output directory."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        try:
            cfg = get_config()

            output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
            if not output_dir.exists():
                output_dir.mkdir(parents=True, exist_ok=True)

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir.absolute())))

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open output: {e}")

    def set_rom_path(self, path: str):
        """Set the ROM directory path (called from settings)."""
        self.rom_path = path
        if path:
            self.path_input.setText(path)
            if Path(path).exists():
                self._scanner.set_iisu_path(Path(path))

    def set_hero_settings(self, enabled: bool, count: int):
        """Set hero image settings (called from settings)."""
        self.hero_enabled = enabled
        self.hero_count = count  # Stored but ROM browser always uses 1
        self.hero_check.setChecked(enabled)

    def _show_manual_add_dialog(self):
        """Show dialog for manually adding game titles."""
        from PySide6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox, QComboBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Add Games Manually")
        dialog.setMinimumSize(500, 400)

        layout = QVBoxLayout(dialog)

        # Instructions
        instructions = QLabel(
            "Enter game titles below (one per line).\n"
            "This is useful when MTP device scanning is too slow.\n\n"
            "Example:\n"
            "  Super Mario World\n"
            "  The Legend of Zelda\n"
            "  Sonic the Hedgehog"
        )
        instructions.setObjectName("label_muted")
        layout.addWidget(instructions)

        # Platform selector
        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Platform:"))
        platform_combo = QComboBox()

        # Add common platforms
        platforms = [
            ("NES", "NES"),
            ("SNES", "SNES"),
            ("N64", "N64"),
            ("GAMECUBE", "GameCube"),
            ("WII", "Wii"),
            ("GAME_BOY", "Game Boy"),
            ("GAME_BOY_ADVANCE", "GBA"),
            ("NINTENDO_DS", "Nintendo DS"),
            ("PS1", "PlayStation"),
            ("PS2", "PlayStation 2"),
            ("PSP", "PSP"),
            ("GENESIS", "Genesis/Mega Drive"),
            ("SATURN", "Saturn"),
            ("DREAMCAST", "Dreamcast"),
            ("GAME_GEAR", "Game Gear"),
            ("MAME", "Arcade/MAME"),
            ("NEO_GEO", "Neo Geo"),
        ]
        for key, name in platforms:
            platform_combo.addItem(name, key)

        platform_row.addWidget(platform_combo, 1)
        layout.addLayout(platform_row)

        # Text area for game titles
        layout.addWidget(QLabel("Game Titles:"))
        text_edit = QTextEdit()
        text_edit.setPlaceholderText("Enter game titles, one per line...")
        layout.addWidget(text_edit, 1)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            platform_key = platform_combo.currentData()
            text = text_edit.toPlainText().strip()

            if not text:
                return

            # Parse game titles
            titles = [line.strip() for line in text.split('\n') if line.strip()]

            if not titles:
                return

            # Create games list
            games = [(title, Path(f"manual://{platform_key}/{title}")) for title in titles]

            # Clear and populate the tree with the manual platform
            self.platform_tree.clear()
            self.games_list.clear()

            item = QTreeWidgetItem([f"{platform_key} ({len(games)})"])
            item.setData(0, Qt.UserRole, platform_key)
            item.setData(0, Qt.UserRole + 1, games)
            self.platform_tree.addTopLevelItem(item)

            self.platform_stats.setText(f"1 platform, {len(games)} games (manually added)")
            self.status_label.setText(f"Added {len(games)} games manually")

            # Auto-select the platform
            self.platform_tree.setCurrentItem(item)
            self._on_platform_selected(item, 0)

    def _show_adb_scan_dialog(self):
        """Show dialog for ADB scanning of iiSU assets folder on Android devices."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QComboBox, QTextEdit

        # Check if ADB is available
        if not check_adb_available():
            # Offer to install ADB automatically
            reply = QMessageBox.question(
                self,
                "ADB Not Found",
                "ADB (Android Debug Bridge) is not installed.\n\n"
                "ADB is required for fast scanning of Android devices.\n"
                "It will be downloaded from Google's official servers (~10MB).\n\n"
                "Do you want to download and install ADB automatically?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Help
            )

            if reply == QMessageBox.Help:
                # Show manual instructions
                QMessageBox.information(
                    self,
                    "Manual ADB Setup",
                    get_setup_instructions()
                )
                return
            elif reply == QMessageBox.Yes:
                # Install ADB automatically
                self._install_adb()
                # Check again after installation
                if not check_adb_available():
                    return
            else:
                return

        # Get connected devices
        devices = get_adb_devices()

        if not devices:
            QMessageBox.warning(
                self,
                "No ADB Devices",
                "No Android devices detected via ADB.\n\n"
                "Make sure:\n"
                "1. USB Debugging is enabled on your device\n"
                "   (Settings > Developer Options > USB Debugging)\n\n"
                "2. Device is connected via USB cable\n\n"
                "3. You authorized USB debugging when prompted on device\n\n"
                "4. Try running 'adb devices' in terminal to troubleshoot"
            )
            return

        # Show device selector dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Scan iiSU Assets - Android Device")
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)

        # Device selector
        layout.addWidget(QLabel("Select Android Device:"))
        device_combo = QComboBox()
        for device_id, status in devices:
            device_combo.addItem(f"{device_id} ({status})", device_id)
        layout.addWidget(device_combo)

        # iiSU Assets path input - default to the config path
        iisu_default_path = self.device_settings.get("path", "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles")
        layout.addWidget(QLabel("iiSU Assets Path on Device:"))
        path_input = QLineEdit()
        path_input.setText(iisu_default_path)
        path_input.setPlaceholderText("/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles")
        layout.addWidget(path_input)

        # ROM Source path (optional sync)
        rom_source_label = QLabel("ROM Source Path (optional):")
        layout.addWidget(rom_source_label)
        rom_path_input = QLineEdit()
        rom_path_input.setPlaceholderText("e.g. /sdcard/ROMs — leave empty to scan assets only")
        layout.addWidget(rom_path_input)

        # Help info
        help_info = QLabel(
            "<span style='color: #888; font-size: 10px;'>"
            "This scans the iiSU Launcher assets folder for games that need artwork.<br>"
            "If games are missing, enter your ROM directory above to create<br>"
            "matching asset folders automatically before scanning."
            "</span>"
        )
        help_info.setWordWrap(True)
        layout.addWidget(help_info)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Scan Assets")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            device_id = device_combo.currentData()
            assets_path = path_input.text().strip() or iisu_default_path
            rom_source_path = rom_path_input.text().strip()

            # Update UI
            self.btn_adb_scan.setEnabled(False)
            self.btn_refresh.setEnabled(False)

            # Force UI update
            from PySide6.QtWidgets import QApplication

            # If ROM source path provided, sync folders first
            if rom_source_path:
                self.status_label.setText(f"Syncing game folders from ROM directory...")
                QApplication.processEvents()

                try:
                    from device_asset_dialog import RomFolderSyncThread, get_subprocess_kwargs as _get_kwargs, list_device_directory, check_path_is_directory
                    # Run sync synchronously (in the main thread for simplicity in the dialog)
                    sync = RomFolderSyncThread(adb_path, rom_source_path, assets_path)
                    # Run the sync thread and wait for it
                    sync.start()
                    sync.wait(timeout=120000)  # 2 minute timeout
                    self.status_label.setText(f"Folder sync complete. Scanning assets...")
                    QApplication.processEvents()
                except Exception as e:
                    print(f"[ADB SCAN] ROM folder sync error: {e}")
                    self.status_label.setText(f"Folder sync failed ({e}), continuing with scan...")
                    QApplication.processEvents()

            self.status_label.setText(f"Scanning iiSU assets via ADB: {device_id}...")
            QApplication.processEvents()

            # Clear previous data
            self.platform_tree.clear()
            self.games_list.clear()

            # Perform ADB scan of iiSU assets folder
            results = self._scan_iisu_assets_via_adb(device_id, assets_path)

            # Re-enable buttons
            self.btn_adb_scan.setEnabled(True)
            self.btn_refresh.setEnabled(True)

            if not results:
                QMessageBox.warning(
                    self,
                    "No Games Found",
                    f"No game folders found at: {assets_path}\n\n"
                    "Make sure:\n"
                    "- iiSU Launcher is installed on your device\n"
                    "- The assets path is correct\n"
                    "- Platform folders exist (nes, snes, gba, etc.)\n\n"
                    "Try 'Add Games Manually' to enter game titles directly."
                )
                self.status_label.setText("ADB scan: No games found")
                return

            # Populate platform tree
            total_games = 0
            missing_icons = 0
            for platform_key in sorted(results.keys()):
                games = results[platform_key]
                if not games:
                    continue

                total_games += len(games)
                # Count missing icons using the extended info dict
                platform_missing = sum(
                    1 for _, path in games
                    if not self._iisu_game_info.get(path, {}).get("has_icon", False)
                )
                missing_icons += platform_missing

                # Create platform item with missing count
                display_text = f"{platform_key} ({len(games)})"
                if platform_missing > 0:
                    display_text += f" - {platform_missing} missing"

                item = QTreeWidgetItem([display_text])
                item.setData(0, Qt.UserRole, platform_key)
                item.setData(0, Qt.UserRole + 1, games)

                # Try to load platform icon
                platform_icons_dir = get_platform_icons_dir()
                icon_path = platform_icons_dir / f"{platform_key}.png"
                if icon_path.exists():
                    item.setIcon(0, QIcon(str(icon_path)))

                self.platform_tree.addTopLevelItem(item)

            self.platform_stats.setText(f"{len(results)} platforms, {total_games} games ({missing_icons} missing icons)")
            self.status_label.setText(f"iiSU scan complete: {total_games} games, {missing_icons} need artwork")

            # Update path display
            self.path_input.setText(f"iisu://{device_id}{assets_path}")

            # Auto-select first platform
            if self.platform_tree.topLevelItemCount() > 0:
                first_item = self.platform_tree.topLevelItem(0)
                self.platform_tree.setCurrentItem(first_item)
                self._on_platform_selected(first_item, 0)

    def _scan_iisu_assets_via_adb(self, device_id: str, assets_path: str) -> Dict[str, List[Tuple[str, str]]]:
        """Scan iiSU assets folder structure via ADB.

        Returns dict of platform -> list of (game_title, game_path) tuples
        compatible with the existing _on_platform_selected method.

        Also stores extended info in self._iisu_game_info for tracking icon/hero status.
        Uses optimized batch commands to minimize ADB calls and prevent UI freezing.
        """
        import subprocess

        adb_path = get_adb_path()
        if not adb_path:
            return {}

        results = {}
        self._iisu_game_info = {}  # Store extended info: path -> {has_icon, has_hero, files}

        # Ensure path doesn't have trailing slash
        assets_path = assets_path.rstrip("/")

        try:
            # Use a single find command to get ALL directories and files in one call
            # This is MUCH faster than calling ls for each game folder
            result = subprocess.run(
                [adb_path, "-s", device_id, "shell",
                 f'find "{assets_path}" -maxdepth 3 -type d -o -maxdepth 3 -type f \\( -name "icon.*" -o -name "hero.*" -o -name "logo.*" \\) 2>/dev/null'],
                capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace',
                **_get_subprocess_flags()
            )

            if result.returncode != 0 or not result.stdout.strip():
                # Fallback to simple ls approach if find fails
                return self._scan_iisu_assets_via_adb_fallback(device_id, assets_path)

            # Parse find output to build structure
            # Output contains both directories and asset files
            # Example:
            #   /path/consoles/GAMECUBE
            #   /path/consoles/GAMECUBE/GameName
            #   /path/consoles/GAMECUBE/GameName/icon.png

            from rom_parser import FOLDER_TO_PLATFORM

            platforms_found = set()
            games_by_platform = {}  # platform_key -> list of (name, path)
            assets_by_game = {}     # game_path -> set of asset types

            lines = result.stdout.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line or line == assets_path:
                    continue

                # Calculate depth from assets_path
                rel_path = line[len(assets_path):].strip('/')
                parts = rel_path.split('/')

                if len(parts) == 1:
                    # Platform folder (depth 1)
                    platforms_found.add(parts[0])
                elif len(parts) == 2:
                    # Game folder (depth 2)
                    platform_folder = parts[0]
                    game_name = parts[1]

                    platform_key = FOLDER_TO_PLATFORM.get(platform_folder.lower(), platform_folder.upper())

                    if platform_key not in games_by_platform:
                        games_by_platform[platform_key] = []

                    game_path = f"{assets_path}/{platform_folder}/{game_name}"
                    # Only add if not already added
                    if not any(g[1] == game_path for g in games_by_platform[platform_key]):
                        games_by_platform[platform_key].append((game_name, game_path))

                    # Initialize asset tracking
                    if game_path not in assets_by_game:
                        assets_by_game[game_path] = set()

                elif len(parts) == 3:
                    # Asset file (depth 3)
                    platform_folder = parts[0]
                    game_name = parts[1]
                    asset_file = parts[2].lower()

                    game_path = f"{assets_path}/{platform_folder}/{game_name}"

                    if game_path not in assets_by_game:
                        assets_by_game[game_path] = set()

                    # Check for asset files: icon.ext, title.ext, slide_N.ext, hero_N.ext, logo.ext
                    if asset_file.startswith('icon.') or asset_file.startswith('icon_'):
                        assets_by_game[game_path].add('icon')
                    elif asset_file.startswith('slide.') or asset_file.startswith('slide_'):
                        assets_by_game[game_path].add('slide')
                    elif asset_file.startswith('hero.') or asset_file.startswith('hero_'):
                        assets_by_game[game_path].add('hero')
                    elif asset_file.startswith('logo.') or asset_file.startswith('logo_'):
                        assets_by_game[game_path].add('logo')
                    elif asset_file.startswith('title.') or asset_file.startswith('title_'):
                        assets_by_game[game_path].add('title')

            # Build results and _iisu_game_info
            for platform_key, games in games_by_platform.items():
                results[platform_key] = games
                print(f"[DEBUG] {platform_key}: {len(games)} games")

                for game_name, game_path in games:
                    assets = assets_by_game.get(game_path, set())
                    if assets:
                        print(f"[DEBUG] Storing game_path={game_path}, assets={assets}")
                    self._iisu_game_info[game_path] = {
                        "has_icon": 'icon' in assets or 'slide' in assets,  # slide can serve as icon
                        "has_slide": 'slide' in assets,
                        "has_hero": 'hero' in assets or 'slide' in assets,  # slide can serve as hero
                        "has_logo": 'logo' in assets or 'title' in assets,  # title can serve as logo
                        "has_title": 'title' in assets,
                        "files": list(assets)
                    }

        except Exception as e:
            print(f"[DEBUG] ADB scan error: {e}")
            return self._scan_iisu_assets_via_adb_fallback(device_id, assets_path)

        return results

    def _scan_iisu_assets_via_adb_fallback(self, device_id: str, assets_path: str) -> Dict[str, List[Tuple[str, str]]]:
        """Fallback scan method using ls -R when find command fails."""
        import subprocess

        adb_path = get_adb_path()
        if not adb_path:
            return {}

        results = {}
        self._iisu_game_info = {}

        try:
            # List platform folders first
            result = subprocess.run(
                [adb_path, "-s", device_id, "shell", f'ls -1 "{assets_path}"'],
                capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace',
                **_get_subprocess_flags()
            )

            if result.returncode != 0:
                return {}

            platforms = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            from rom_parser import FOLDER_TO_PLATFORM

            for platform_folder in platforms:
                platform_path = f"{assets_path}/{platform_folder}"
                platform_key = FOLDER_TO_PLATFORM.get(platform_folder.lower(), platform_folder.upper())

                # Use ls -R to get recursive listing in one call
                result = subprocess.run(
                    [adb_path, "-s", device_id, "shell", f'ls -R "{platform_path}"'],
                    capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace',
                    **_get_subprocess_flags()
                )

                if result.returncode != 0:
                    continue

                games = []
                current_game_path = None
                current_game_name = None
                current_assets = set()

                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if not line:
                        continue

                    if line.endswith(':'):
                        # Save previous game info
                        if current_game_path and current_game_name:
                            self._iisu_game_info[current_game_path] = {
                                "has_icon": 'icon' in current_assets or 'slide' in current_assets,
                                "has_slide": 'slide' in current_assets,
                                "has_hero": 'hero' in current_assets or 'slide' in current_assets,
                                "has_logo": 'logo' in current_assets or 'title' in current_assets,
                                "has_title": 'title' in current_assets,
                                "files": list(current_assets)
                            }

                        # New directory - check if it's a game folder (depth 1 from platform)
                        dir_path = line[:-1]
                        rel_path = dir_path[len(platform_path):].strip('/')

                        if '/' not in rel_path and rel_path:
                            # This is a game folder
                            current_game_name = rel_path
                            current_game_path = dir_path
                            current_assets = set()
                            games.append((current_game_name, current_game_path))
                        else:
                            current_game_path = None
                            current_game_name = None
                    elif current_game_path:
                        # This is a file in the current game folder
                        # Check for asset files: icon.ext, title.ext, slide_N.ext, hero_N.ext, logo.ext
                        file_lower = line.lower()
                        if file_lower.startswith('icon.') or file_lower.startswith('icon_'):
                            current_assets.add('icon')
                        elif file_lower.startswith('slide.') or file_lower.startswith('slide_'):
                            current_assets.add('slide')
                        elif file_lower.startswith('hero.') or file_lower.startswith('hero_'):
                            current_assets.add('hero')
                        elif file_lower.startswith('logo.') or file_lower.startswith('logo_'):
                            current_assets.add('logo')
                        elif file_lower.startswith('title.') or file_lower.startswith('title_'):
                            current_assets.add('title')

                # Save last game info
                if current_game_path and current_game_name:
                    self._iisu_game_info[current_game_path] = {
                        "has_icon": 'icon' in current_assets or 'slide' in current_assets,
                        "has_slide": 'slide' in current_assets,
                        "has_hero": 'hero' in current_assets or 'slide' in current_assets,
                        "has_logo": 'logo' in current_assets or 'title' in current_assets,
                        "has_title": 'title' in current_assets,
                        "files": list(current_assets)
                    }

                if games:
                    results[platform_key] = games
                    print(f"[DEBUG] {platform_key}: {len(games)} games")

        except Exception as e:
            print(f"[DEBUG] ADB fallback scan error: {e}")

        return results

    def _install_adb(self):
        """Download and install Android SDK Platform Tools."""
        from PySide6.QtWidgets import QDialog, QProgressBar, QDialogButtonBox

        # Create progress dialog
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("Installing ADB")
        progress_dialog.setMinimumWidth(400)
        progress_dialog.setModal(True)

        layout = QVBoxLayout(progress_dialog)

        status_label = QLabel("Downloading Android SDK Platform Tools...")
        layout.addWidget(status_label)

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        layout.addWidget(progress_bar)

        info_label = QLabel(
            "<span style='color: #888; font-size: 10px;'>"
            "Downloading from dl.google.com (~10MB)"
            "</span>"
        )
        layout.addWidget(info_label)

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(progress_dialog.reject)
        layout.addWidget(cancel_btn)

        # Track cancellation
        cancelled = [False]

        def on_cancel():
            cancelled[0] = True

        cancel_btn.clicked.connect(on_cancel)

        # Progress callback
        def progress_callback(downloaded, total):
            if cancelled[0]:
                raise Exception("Download cancelled")
            if total > 0:
                pct = int((downloaded / total) * 100)
                progress_bar.setValue(pct)
                mb_downloaded = downloaded / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                status_label.setText(f"Downloading... {mb_downloaded:.1f} / {mb_total:.1f} MB")
            # Process events to keep UI responsive
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

        # Run installation in a thread-like manner
        progress_dialog.show()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            success, message, adb_path = setup_adb(
                add_path=True,
                progress_callback=progress_callback
            )

            progress_dialog.close()

            if success:
                QMessageBox.information(
                    self,
                    "ADB Installed",
                    f"ADB has been installed successfully!\n\n{message}\n\n"
                    "Next steps:\n"
                    "1. Enable USB Debugging on your Android device\n"
                    "   (Settings > Developer Options > USB Debugging)\n"
                    "2. Connect your device via USB\n"
                    "3. Authorize the USB debugging prompt on your device"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Installation Failed",
                    f"Failed to install ADB:\n\n{message}\n\n"
                    "You can try manual installation instead."
                )

        except Exception as e:
            progress_dialog.close()
            if "cancelled" in str(e).lower():
                self.status_label.setText("ADB installation cancelled")
            else:
                QMessageBox.warning(
                    self,
                    "Installation Error",
                    f"Error during installation:\n\n{str(e)}"
                )

    def _show_logs_dialog(self):
        """Show logs dialog with processing history."""
        from PySide6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox, QApplication

        dialog = QDialog(self)
        dialog.setWindowTitle("Processing Logs")
        dialog.setMinimumSize(700, 500)

        layout = QVBoxLayout(dialog)

        # Info label
        info_label = QLabel(f"{len(self._log_messages)} log entries")
        info_label.setObjectName("label_muted")
        layout.addWidget(info_label)

        # Log text area
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setObjectName("rom_log_text")

        # Populate with log messages
        if self._log_messages:
            log_text.setPlainText("\n".join(self._log_messages))
            # Scroll to bottom
            cursor = log_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            log_text.setTextCursor(cursor)
        else:
            log_text.setPlainText("No log messages yet.\n\nProcess some games to see logs here.")

        layout.addWidget(log_text, 1)

        # Buttons
        button_row = QHBoxLayout()

        btn_clear = QPushButton("Clear Logs")
        btn_clear.clicked.connect(lambda: (self._log_messages.clear(), log_text.clear(), info_label.setText("0 log entries")))
        button_row.addWidget(btn_clear)

        def copy_to_clipboard():
            if self._log_messages:
                clipboard = QApplication.clipboard()
                clipboard.setText("\n".join(self._log_messages))
                btn_copy.setText("Copied!")
                # Reset button text after 2 seconds
                from PySide6.QtCore import QTimer
                QTimer.singleShot(2000, lambda: btn_copy.setText("Copy to Clipboard"))

        btn_copy = QPushButton("Copy to Clipboard")
        btn_copy.clicked.connect(copy_to_clipboard)
        button_row.addWidget(btn_copy)

        button_row.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.accept)
        button_row.addWidget(btn_close)

        layout.addLayout(button_row)

        dialog.exec()

    def _toggle_preview_visibility(self):
        """Toggle preview panel visibility."""
        if self._preview_visible:
            self.preview_scroll_area.hide()
            self.btn_hide_preview.setText("+")
            self.btn_hide_preview.setToolTip("Expand preview")
            self._preview_visible = False
        else:
            self.preview_scroll_area.show()
            self.btn_hide_preview.setText("-")
            self.btn_hide_preview.setToolTip("Collapse preview")
            self._preview_visible = True

    def _popout_preview(self):
        """Pop out preview to a separate window."""
        if self._preview_popout_window is not None:
            # If already popped out, bring window to front
            self._preview_popout_window.raise_()
            self._preview_popout_window.activateWindow()
            return

        # Create a new window for the preview
        from PySide6.QtWidgets import QDialog

        self._preview_popout_window = QDialog(self)
        self._preview_popout_window.setWindowTitle("Preview - iiSU Asset Tool")
        self._preview_popout_window.setMinimumSize(600, 400)
        self._preview_popout_window.setAttribute(Qt.WA_DeleteOnClose)
        self._preview_popout_window.finished.connect(self._on_popout_closed)

        popout_layout = QVBoxLayout(self._preview_popout_window)
        popout_layout.setContentsMargins(10, 10, 10, 10)

        # Create new scroll area for popout
        self._popout_scroll_area = QScrollArea()
        self._popout_scroll_area.setWidgetResizable(True)

        self._popout_preview_widget = QWidget()
        self._popout_preview_grid = QGridLayout(self._popout_preview_widget)
        self._popout_preview_grid.setSpacing(8)
        self._popout_scroll_area.setWidget(self._popout_preview_widget)

        popout_layout.addWidget(self._popout_scroll_area)

        # Copy existing previews to popout window
        self._popout_preview_items = []
        self._sync_previews_to_popout()

        # Button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_dock = QPushButton("Dock")
        btn_dock.clicked.connect(self._dock_preview)
        btn_row.addWidget(btn_dock)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self._preview_popout_window.close)
        btn_row.addWidget(btn_close)

        popout_layout.addLayout(btn_row)

        # Hide the inline preview
        self.preview_group.hide()
        self.btn_popout_preview.setText("Docked")
        self.btn_popout_preview.setEnabled(False)

        self._preview_popout_window.show()

    def _sync_previews_to_popout(self):
        """Sync preview items to the popout window."""
        if not hasattr(self, '_popout_preview_grid'):
            return

        # Copy all preview items to the popout
        for i, preview_label in enumerate(self.preview_items):
            pixmap = preview_label.pixmap()
            if pixmap:
                label = QLabel()
                label.setFixedSize(160, 160)  # Larger in popout
                label.setScaledContents(True)
                label.setObjectName("rom_preview_label")
                label.setPixmap(pixmap)
                label.setToolTip(preview_label.toolTip())

                row = i // 4  # 4 per row in popout
                col = i % 4
                self._popout_preview_grid.addWidget(label, row, col)
                self._popout_preview_items.append(label)

    def _dock_preview(self):
        """Dock the preview back to inline view."""
        if self._preview_popout_window:
            self._preview_popout_window.close()

    def _on_popout_closed(self):
        """Handle popout window being closed."""
        # Clear popout items
        if hasattr(self, '_popout_preview_items'):
            for item in self._popout_preview_items:
                item.deleteLater()
            self._popout_preview_items = []

        self._preview_popout_window = None

        # Show inline preview again
        self.preview_group.show()
        self.btn_popout_preview.setText("Pop Out")
        self.btn_popout_preview.setEnabled(True)

    def _add_preview_to_popout(self, path: str):
        """Add a preview to the popout window if it's open."""
        if not self._preview_popout_window or not hasattr(self, '_popout_preview_grid'):
            return

        path_obj = Path(path)
        if not path_obj.exists():
            return

        label = QLabel()
        label.setFixedSize(160, 160)
        label.setScaledContents(True)
        label.setObjectName("rom_preview_label")

        pixmap = QPixmap(path)
        if not pixmap.isNull():
            label.setPixmap(pixmap)
            label.setToolTip(path_obj.stem)

            row = len(self._popout_preview_items) // 4
            col = len(self._popout_preview_items) % 4
            self._popout_preview_grid.addWidget(label, row, col)
            self._popout_preview_items.append(label)
