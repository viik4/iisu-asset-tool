"""
Device Asset Replacement Dialog for iiSU Asset Tool
Allows browsing and replacing existing assets on connected Android devices via ADB
"""
import os
import re
import sys
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QGroupBox, QDialogButtonBox, QMessageBox, QProgressBar,
    QFileDialog, QSplitter, QWidget, QCheckBox
)

from adb_setup import is_adb_installed


def get_subprocess_kwargs():
    """Get platform-specific subprocess kwargs to hide console windows on Windows."""
    kwargs = {
        'capture_output': True,
        'text': True,
    }
    if sys.platform == 'win32':
        # Prevent console window from flashing on Windows
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return kwargs


def normalize_game_name(name: str) -> str:
    """Normalize a game name for comparison by removing region tags, revision info, etc."""
    # Remove common suffixes like (USA), (Rev 1), (En,Fr), etc.
    normalized = re.sub(r'\s*\([^)]*\)\s*', ' ', name)
    # Remove square bracket content like [!], [b1], etc.
    normalized = re.sub(r'\s*\[[^\]]*\]\s*', ' ', normalized)
    # Replace underscores with spaces
    normalized = normalized.replace('_', ' ')
    # Remove extra whitespace
    normalized = ' '.join(normalized.split())
    # Convert to lowercase for comparison
    return normalized.lower().strip()


def find_matching_local_folder(device_game_name: str, local_folders: List[Path]) -> Optional[Path]:
    """Find a local folder that matches the device game name using fuzzy matching."""
    device_normalized = normalize_game_name(device_game_name)

    best_match = None
    best_score = 0

    for folder in local_folders:
        local_normalized = normalize_game_name(folder.name)

        # Exact match after normalization
        if device_normalized == local_normalized:
            return folder

        # Check if one contains the other
        if device_normalized in local_normalized or local_normalized in device_normalized:
            # Score based on length similarity
            score = min(len(device_normalized), len(local_normalized)) / max(len(device_normalized), len(local_normalized))
            if score > best_score:
                best_score = score
                best_match = folder

        # Check word overlap
        device_words = set(device_normalized.split())
        local_words = set(local_normalized.split())
        if device_words and local_words:
            overlap = len(device_words & local_words)
            total = len(device_words | local_words)
            score = overlap / total if total > 0 else 0
            if score > best_score and score >= 0.5:  # At least 50% word overlap
                best_score = score
                best_match = folder

    return best_match if best_score >= 0.5 else None


def get_adb_path() -> Optional[str]:
    """Find ADB executable path."""
    adb_path = shutil.which("adb")
    if adb_path:
        return adb_path

    is_installed, adb_exe = is_adb_installed()
    if is_installed and adb_exe:
        return str(adb_exe)

    return None


def list_device_directory(adb_path: str, device_path: str) -> List[str]:
    """List contents of a directory on the device."""
    try:
        # Quote the path to handle spaces
        kwargs = get_subprocess_kwargs()
        result = subprocess.run(
            [adb_path, "shell", f'ls -1 "{device_path}"'],
            timeout=30, **kwargs
        )
        print(f"[DEBUG] ls '{device_path}' returncode={result.returncode}")
        if result.stderr:
            print(f"[DEBUG] ls stderr: {result.stderr[:200]}")
        if result.returncode == 0:
            items = result.stdout.strip().split('\n')
            clean_items = [item.strip() for item in items if item.strip()]
            print(f"[DEBUG] Found {len(clean_items)} items in {device_path}")
            return clean_items
        return []
    except Exception as e:
        print(f"[DEBUG] list_device_directory exception: {e}")
        return []


def check_path_is_directory(adb_path: str, device_path: str) -> bool:
    """Check if a path on the device is a directory."""
    try:
        # Use a single shell command string so && is interpreted correctly
        kwargs = get_subprocess_kwargs()
        result = subprocess.run(
            [adb_path, "shell", f'test -d "{device_path}" && echo yes'],
            timeout=10, **kwargs
        )
        is_dir = "yes" in result.stdout
        print(f"[DEBUG] check_path_is_directory '{device_path}' = {is_dir}")
        return is_dir
    except Exception as e:
        print(f"[DEBUG] check_path_is_directory exception: {e}")
        return False


class DeviceScanThread(QThread):
    """Thread for scanning device assets."""
    progress = Signal(str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, adb_path: str, device_base_path: str):
        super().__init__()
        self.adb_path = adb_path
        self.device_base_path = device_base_path

    def run(self):
        """Scan device for existing game assets."""
        try:
            assets = {}

            # List platform folders
            self.progress.emit("Scanning platforms...")
            print(f"[DEBUG] Scanning base path: {self.device_base_path}")
            platforms = list_device_directory(self.adb_path, self.device_base_path)
            print(f"[DEBUG] Found platforms: {platforms}")

            for platform in platforms:
                if not platform:
                    continue

                platform_path = f"{self.device_base_path}/{platform}"

                self.progress.emit(f"Scanning {platform}...")

                # List game folders in platform - use ls -la to identify directories
                try:
                    kwargs = get_subprocess_kwargs()
                    result = subprocess.run(
                        [self.adb_path, "shell", f'ls -la "{platform_path}"'],
                        timeout=60, **kwargs
                    )
                    print(f"[DEBUG] ls -la {platform_path} returncode={result.returncode}")

                    if result.returncode != 0:
                        print(f"[DEBUG] ls -la failed: {result.stderr[:200] if result.stderr else 'no stderr'}")
                        continue

                    # Parse ls -la output to find directories
                    games = []
                    for line in result.stdout.strip().split('\n'):
                        line = line.strip()
                        if not line or line.startswith('total'):
                            continue
                        # Directory lines start with 'd'
                        if line.startswith('d'):
                            # Extract name - it's the last part after the date/time
                            # Format: drwxrwxrwx ... name
                            parts = line.split()
                            if len(parts) >= 8:
                                # Name might have spaces, so join everything after the 7th column
                                name = ' '.join(parts[7:])
                                if name and name not in ('.', '..'):
                                    games.append(name)

                    print(f"[DEBUG] Found {len(games)} game folders in {platform}")

                    if games:
                        assets[platform] = []
                        for game in games:
                            game_path = f"{platform_path}/{game}"
                            # List files in game folder
                            files = list_device_directory(self.adb_path, game_path)
                            assets[platform].append({
                                "name": game,
                                "path": game_path,
                                "files": files
                            })

                except subprocess.TimeoutExpired:
                    print(f"[DEBUG] Timeout scanning {platform}")
                    continue
                except Exception as e:
                    print(f"[DEBUG] Error scanning {platform}: {e}")
                    continue

            self.finished.emit(assets)

        except Exception as e:
            self.error.emit(str(e))


class DevicePushThread(QThread):
    """Thread for pushing assets to device."""
    progress = Signal(int, int, str)
    finished = Signal(int, int, list)  # copied, errors, list of successfully pushed game folders
    error = Signal(str)

    def __init__(self, adb_path: str, items: List[Tuple[str, str]]):
        super().__init__()
        self.adb_path = adb_path
        self.items = items  # List of (local_path, device_path) tuples

    def run(self):
        """Push asset FILES to existing device folders (not creating new folders)."""
        try:
            copied = 0
            errors = 0
            total = len(self.items)
            successful_folders = set()  # Track which LOCAL game folders were fully pushed

            for i, (local_path, device_path) in enumerate(self.items):
                self.progress.emit(i + 1, total, Path(local_path).name)
                print(f"[DEBUG] Pushing FILE: {local_path}")
                print(f"[DEBUG]      -> TO: {device_path}")

                try:
                    # Push file to existing device folder
                    # adb push handles paths with spaces correctly
                    kwargs = get_subprocess_kwargs()
                    result = subprocess.run(
                        [self.adb_path, "push", local_path, device_path],
                        timeout=60, **kwargs
                    )

                    if result.returncode == 0:
                        copied += 1
                        # Track the parent game folder (local) for deletion later
                        game_folder = str(Path(local_path).parent)
                        successful_folders.add(game_folder)
                        print(f"[DEBUG] Push success: {Path(local_path).name}")
                    else:
                        errors += 1
                        print(f"[DEBUG] Push failed: {result.stderr}")

                except Exception as e:
                    errors += 1
                    print(f"[DEBUG] Push exception: {e}")

            self.finished.emit(copied, errors, list(successful_folders))

        except Exception as e:
            self.error.emit(str(e))


class DeviceAssetDialog(QDialog):
    """Dialog for managing assets on connected Android device.

    Scans the iiSU Launcher assets folder directly (same as Android version)
    to find games and their existing artwork files.
    """

    # Default iiSU Launcher assets path
    IISU_DEFAULT_PATH = "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"

    def __init__(self, parent=None, output_dir: str = "", device_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("iiSU Device Assets Manager")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)

        self.output_dir = output_dir or "./output"
        self.device_base_path = device_path or self.IISU_DEFAULT_PATH
        # Ensure path doesn't have trailing slash
        self.device_base_path = self.device_base_path.rstrip("/")
        self.adb_path = get_adb_path()
        self.device_assets = {}

        self._setup_ui()
        self._check_adb()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Device Path Group
        path_group = QGroupBox("iiSU Launcher Assets Path")
        path_layout = QHBoxLayout()

        self.device_path_input = QLineEdit(self.device_base_path)
        self.device_path_input.setPlaceholderText(self.IISU_DEFAULT_PATH)
        path_layout.addWidget(self.device_path_input, 1)

        self.btn_scan = QPushButton("Scan iiSU Assets")
        self.btn_scan.clicked.connect(self._scan_device)
        path_layout.addWidget(self.btn_scan)

        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        # Status
        self.status_label = QLabel("Click 'Scan iiSU Assets' to view game folders on device")
        self.status_label.setObjectName("desc_status")
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Main content - splitter with device assets and local assets
        splitter = QSplitter(Qt.Horizontal)

        # Device assets tree
        device_widget = QWidget()
        device_layout = QVBoxLayout(device_widget)
        device_layout.setContentsMargins(0, 0, 0, 0)

        device_header = QLabel("iiSU Game Folders (Device)")
        device_header.setObjectName("header")
        device_layout.addWidget(device_header)

        self.device_tree = QTreeWidget()
        self.device_tree.setHeaderLabels(["Platform / Game", "Assets"])
        self.device_tree.setColumnWidth(0, 300)
        self.device_tree.itemSelectionChanged.connect(self._on_device_selection_changed)
        device_layout.addWidget(self.device_tree)

        splitter.addWidget(device_widget)

        # Local assets tree
        local_widget = QWidget()
        local_layout = QVBoxLayout(local_widget)
        local_layout.setContentsMargins(0, 0, 0, 0)

        local_header_layout = QHBoxLayout()
        local_header = QLabel("Local Assets (Output)")
        local_header.setObjectName("header")
        local_header_layout.addWidget(local_header)

        btn_browse_local = QPushButton("Browse...")
        btn_browse_local.clicked.connect(self._browse_local_output)
        local_header_layout.addWidget(btn_browse_local)
        local_layout.addLayout(local_header_layout)

        self.local_path_label = QLabel(self.output_dir)
        self.local_path_label.setObjectName("desc_path")
        local_layout.addWidget(self.local_path_label)

        self.local_tree = QTreeWidget()
        self.local_tree.setHeaderLabels(["Platform / Game", "Files"])
        self.local_tree.setColumnWidth(0, 300)
        local_layout.addWidget(self.local_tree)

        splitter.addWidget(local_widget)

        # Set initial splitter sizes (50/50 split)
        splitter.setSizes([400, 400])

        layout.addWidget(splitter, 1)

        # Options row
        options_layout = QHBoxLayout()

        self.delete_after_push = QCheckBox("Delete local assets after pushing to device")
        self.delete_after_push.setToolTip("Remove the local output folder for each game after successfully pushing to device")
        self.delete_after_push.setChecked(True)
        options_layout.addWidget(self.delete_after_push)

        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Action buttons
        action_layout = QHBoxLayout()

        self.btn_replace_selected = QPushButton("Replace Selected on Device")
        self.btn_replace_selected.clicked.connect(self._replace_selected)
        self.btn_replace_selected.setEnabled(False)
        self.btn_replace_selected.setObjectName("btn_start")
        action_layout.addWidget(self.btn_replace_selected)

        self.btn_push_all = QPushButton("Push All Local to Device")
        self.btn_push_all.clicked.connect(self._push_all_local)
        self.btn_push_all.setObjectName("btn_preview")
        action_layout.addWidget(self.btn_push_all)

        action_layout.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        action_layout.addWidget(btn_close)

        layout.addLayout(action_layout)

        # Load local assets
        self._load_local_assets()

    def _check_adb(self):
        """Check if ADB is available."""
        if not self.adb_path:
            self.status_label.setText("ADB not found. Please install Android SDK Platform Tools.")
            self.btn_scan.setEnabled(False)
            self.btn_replace_selected.setEnabled(False)
            self.btn_push_all.setEnabled(False)
        else:
            # Check for connected devices
            try:
                kwargs = get_subprocess_kwargs()
                result = subprocess.run(
                    [self.adb_path, "devices"],
                    timeout=10, **kwargs
                )
                lines = result.stdout.strip().split('\n')[1:]
                devices = [l.split('\t')[0] for l in lines if '\tdevice' in l]

                if devices:
                    self.status_label.setText(f"Found {len(devices)} connected device(s). Click 'Scan Device' to view assets.")
                else:
                    self.status_label.setText("No Android devices connected. Enable USB debugging and connect device.")
                    self.btn_scan.setEnabled(False)
            except Exception as e:
                self.status_label.setText(f"Error checking devices: {e}")
                self.btn_scan.setEnabled(False)

    def _scan_device(self):
        """Scan device for existing assets."""
        self.device_base_path = self.device_path_input.text().strip()

        self.btn_scan.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.status_label.setText("Scanning device...")
        self.device_tree.clear()

        self.scan_thread = DeviceScanThread(self.adb_path, self.device_base_path)
        self.scan_thread.progress.connect(self._on_scan_progress)
        self.scan_thread.finished.connect(self._on_scan_finished)
        self.scan_thread.error.connect(self._on_scan_error)
        self.scan_thread.start()

    def _on_scan_progress(self, message: str):
        """Handle scan progress update."""
        self.status_label.setText(message)

    def _on_scan_finished(self, assets: dict):
        """Handle scan completion."""
        self.device_assets = assets
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)

        # Populate tree
        self.device_tree.clear()
        total_games = 0

        for platform, games in sorted(assets.items()):
            platform_item = QTreeWidgetItem([platform, f"{len(games)} games"])
            platform_item.setData(0, Qt.UserRole, {"type": "platform", "path": f"{self.device_base_path}/{platform}"})

            for game in sorted(games, key=lambda g: g["name"]):
                files_str = ", ".join(game["files"][:3])
                if len(game["files"]) > 3:
                    files_str += f" +{len(game['files']) - 3} more"

                game_item = QTreeWidgetItem([game["name"], files_str])
                game_item.setData(0, Qt.UserRole, {
                    "type": "game",
                    "name": game["name"],
                    "path": game["path"],
                    "files": game["files"],
                    "platform": platform
                })
                game_item.setCheckState(0, Qt.Unchecked)
                platform_item.addChild(game_item)
                total_games += 1

            self.device_tree.addTopLevelItem(platform_item)

        self.device_tree.expandAll()
        self.status_label.setText(f"Found {len(assets)} platforms, {total_games} games on device")

    def _on_scan_error(self, error: str):
        """Handle scan error."""
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Scan error: {error}")
        QMessageBox.critical(self, "Scan Error", f"Failed to scan device: {error}")

    def _load_local_assets(self):
        """Load local output assets."""
        self.local_tree.clear()

        output_path = Path(self.output_dir)
        if not output_path.exists():
            return

        for platform_folder in sorted(output_path.iterdir()):
            if not platform_folder.is_dir():
                continue

            games = list(platform_folder.iterdir())
            game_count = len([g for g in games if g.is_dir()])

            platform_item = QTreeWidgetItem([platform_folder.name, f"{game_count} games"])
            platform_item.setData(0, Qt.UserRole, {"type": "platform", "path": str(platform_folder)})

            for game_folder in sorted(games):
                if not game_folder.is_dir():
                    continue

                files = [f.name for f in game_folder.iterdir() if f.is_file()]
                files_str = ", ".join(files[:3])
                if len(files) > 3:
                    files_str += f" +{len(files) - 3} more"

                game_item = QTreeWidgetItem([game_folder.name, files_str])
                game_item.setData(0, Qt.UserRole, {
                    "type": "game",
                    "name": game_folder.name,
                    "path": str(game_folder),
                    "files": files,
                    "platform": platform_folder.name
                })
                game_item.setCheckState(0, Qt.Unchecked)
                platform_item.addChild(game_item)

            self.local_tree.addTopLevelItem(platform_item)

        self.local_tree.expandAll()

    def _browse_local_output(self):
        """Browse for local output directory."""
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.output_dir,
            QFileDialog.ShowDirsOnly
        )
        if path:
            self.output_dir = path
            self.local_path_label.setText(path)
            self._load_local_assets()

    def _on_device_selection_changed(self):
        """Handle device tree selection change."""
        selected = self.device_tree.selectedItems()
        has_selection = len(selected) > 0
        self.btn_replace_selected.setEnabled(has_selection)

    def _get_checked_local_items(self) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
        """Get list of checked local items with fuzzy matching to device folders.

        Returns:
            Tuple of (items, matched_games, unmatched_games)
            - items: List of (local_path, device_path) tuples
            - matched_games: List of "local_name -> device_name" strings
            - unmatched_games: List of local game names with no device match
        """
        items = []
        matched_games = []
        unmatched_games = []

        for i in range(self.local_tree.topLevelItemCount()):
            platform_item = self.local_tree.topLevelItem(i)
            platform_name = platform_item.text(0)

            # Get device game folders for this platform
            device_game_names = []
            if platform_name in self.device_assets:
                device_game_names = [g["name"] for g in self.device_assets[platform_name]]

            for j in range(platform_item.childCount()):
                game_item = platform_item.child(j)
                if game_item.checkState(0) == Qt.Checked:
                    data = game_item.data(0, Qt.UserRole)
                    local_game_path = Path(data["path"])
                    local_game_name = data['name']
                    device_game_name = local_game_name  # Default to same name

                    # Try to find matching device folder
                    if device_game_names:
                        # First try exact match
                        if local_game_name not in device_game_names:
                            # Try fuzzy matching
                            local_normalized = normalize_game_name(local_game_name)
                            best_match = None
                            best_score = 0

                            for device_name in device_game_names:
                                device_normalized = normalize_game_name(device_name)

                                # Exact match after normalization
                                if local_normalized == device_normalized:
                                    best_match = device_name
                                    best_score = 1.0
                                    break

                                # Check if one contains the other
                                if local_normalized in device_normalized or device_normalized in local_normalized:
                                    score = min(len(local_normalized), len(device_normalized)) / max(len(local_normalized), len(device_normalized))
                                    if score > best_score:
                                        best_score = score
                                        best_match = device_name

                                # Check word overlap
                                local_words = set(local_normalized.split())
                                device_words = set(device_normalized.split())
                                if local_words and device_words:
                                    overlap = len(local_words & device_words)
                                    total = len(local_words | device_words)
                                    score = overlap / total if total > 0 else 0
                                    if score > best_score and score >= 0.5:
                                        best_score = score
                                        best_match = device_name

                            if best_match and best_score >= 0.5:
                                device_game_name = best_match
                                matched_games.append(f"{local_game_name} -> {device_game_name}")
                                print(f"[DEBUG] Checked item match: '{local_game_name}' -> '{device_game_name}'")
                            else:
                                unmatched_games.append(f"{platform_name}/{local_game_name}")
                                continue  # Skip unmatched games
                        else:
                            matched_games.append(f"{local_game_name} (exact)")

                    device_game_path = f"{self.device_base_path}/{platform_name}/{device_game_name}"

                    # Add all files in the game folder
                    for file_path in local_game_path.iterdir():
                        if file_path.is_file():
                            items.append((
                                str(file_path),
                                f"{device_game_path}/{file_path.name}"
                            ))

        return items, matched_games, unmatched_games

    def _get_all_local_items_with_matching(self) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
        """Get list of all local items with fuzzy matching to device folders.

        Returns:
            Tuple of (items, matched_games, unmatched_games)
            - items: List of (local_path, device_path) tuples
            - matched_games: List of "local_name -> device_name" strings
            - unmatched_games: List of local game names with no device match
        """
        items = []
        matched_games = []
        unmatched_games = []

        output_path = Path(self.output_dir)
        if not output_path.exists():
            return items, matched_games, unmatched_games

        for platform_folder in output_path.iterdir():
            if not platform_folder.is_dir():
                continue

            platform_name = platform_folder.name

            # Get device game folders for this platform
            device_game_names = []
            if platform_name in self.device_assets:
                device_game_names = [g["name"] for g in self.device_assets[platform_name]]

            for game_folder in platform_folder.iterdir():
                if not game_folder.is_dir():
                    continue

                local_game_name = game_folder.name
                device_game_name = local_game_name  # Default to same name

                # Try to find matching device folder
                if device_game_names:
                    # First try exact match
                    if local_game_name not in device_game_names:
                        # Try fuzzy matching
                        local_normalized = normalize_game_name(local_game_name)
                        best_match = None
                        best_score = 0

                        for device_name in device_game_names:
                            device_normalized = normalize_game_name(device_name)

                            # Exact match after normalization
                            if local_normalized == device_normalized:
                                best_match = device_name
                                best_score = 1.0
                                break

                            # Check if one contains the other
                            if local_normalized in device_normalized or device_normalized in local_normalized:
                                score = min(len(local_normalized), len(device_normalized)) / max(len(local_normalized), len(device_normalized))
                                if score > best_score:
                                    best_score = score
                                    best_match = device_name

                            # Check word overlap
                            local_words = set(local_normalized.split())
                            device_words = set(device_normalized.split())
                            if local_words and device_words:
                                overlap = len(local_words & device_words)
                                total = len(local_words | device_words)
                                score = overlap / total if total > 0 else 0
                                if score > best_score and score >= 0.5:
                                    best_score = score
                                    best_match = device_name

                        if best_match and best_score >= 0.5:
                            device_game_name = best_match
                            matched_games.append(f"{local_game_name} -> {device_game_name}")
                            print(f"[DEBUG] Push match: '{local_game_name}' -> '{device_game_name}'")
                        else:
                            unmatched_games.append(f"{platform_name}/{local_game_name}")
                            continue  # Skip unmatched games
                    else:
                        matched_games.append(f"{local_game_name} (exact)")

                device_game_path = f"{self.device_base_path}/{platform_name}/{device_game_name}"
                print(f"[DEBUG] Device target folder: {device_game_path}")

                for file_path in game_folder.iterdir():
                    if file_path.is_file():
                        target_path = f"{device_game_path}/{file_path.name}"
                        print(f"[DEBUG]   File: {file_path.name} -> {target_path}")
                        items.append((
                            str(file_path),
                            target_path
                        ))

        return items, matched_games, unmatched_games

    def _replace_selected(self):
        """Replace selected items on device with local versions."""
        # Find selected device items and match with local
        selected_items = []
        matched_games = []
        unmatched_games = []

        for item in self.device_tree.selectedItems():
            data = item.data(0, Qt.UserRole)
            if data and data.get("type") == "game":
                platform = data.get("platform")
                game_name = data.get("name")
                device_game_path = data.get("path")

                # First try exact match
                local_game_path = Path(self.output_dir) / platform / game_name

                if not local_game_path.exists():
                    # Try fuzzy matching with local folders
                    local_platform_path = Path(self.output_dir) / platform
                    if local_platform_path.exists():
                        local_folders = [f for f in local_platform_path.iterdir() if f.is_dir()]
                        matched_folder = find_matching_local_folder(game_name, local_folders)
                        if matched_folder:
                            local_game_path = matched_folder
                            print(f"[DEBUG] Fuzzy matched '{game_name}' -> '{matched_folder.name}'")

                if local_game_path.exists():
                    matched_games.append(f"{game_name} -> {local_game_path.name}")
                    for file_path in local_game_path.iterdir():
                        if file_path.is_file():
                            selected_items.append((
                                str(file_path),
                                f"{device_game_path}/{file_path.name}"
                            ))
                else:
                    unmatched_games.append(game_name)

        if not selected_items:
            msg = "No matching local assets found for selected device games.\n\n"
            if unmatched_games:
                msg += f"Unmatched games ({len(unmatched_games)}):\n"
                msg += "\n".join(f"  - {g}" for g in unmatched_games[:10])
                if len(unmatched_games) > 10:
                    msg += f"\n  ... and {len(unmatched_games) - 10} more"
            msg += "\n\nMake sure you have generated assets for the selected games."
            QMessageBox.information(self, "No Matches", msg)
            return

        # Show confirmation with match details
        msg = f"Replace {len(selected_items)} files on device?\n\n"
        msg += f"Matched {len(matched_games)} games:\n"
        for match in matched_games[:5]:
            msg += f"  - {match}\n"
        if len(matched_games) > 5:
            msg += f"  ... and {len(matched_games) - 5} more\n"
        if unmatched_games:
            msg += f"\n{len(unmatched_games)} games had no local match."

        reply = QMessageBox.question(
            self,
            "Confirm Replace",
            msg,
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._push_items(selected_items)

    def _push_all_local(self):
        """Push all local assets to device."""
        # Check if we have device data for matching
        if not self.device_assets:
            QMessageBox.warning(
                self,
                "Scan Required",
                "Please scan the device first to enable fuzzy matching.\n\n"
                "This ensures local assets are pushed to the correct device folders."
            )
            return

        items, matched_games, unmatched_games = self._get_all_local_items_with_matching()

        if not items:
            msg = "No matching local assets found to push.\n\n"
            if unmatched_games:
                msg += f"Unmatched games ({len(unmatched_games)}):\n"
                msg += "\n".join(f"  - {g}" for g in unmatched_games[:10])
                if len(unmatched_games) > 10:
                    msg += f"\n  ... and {len(unmatched_games) - 10} more"
            msg += "\n\nGenerate assets first using the Icon Generator tab."
            QMessageBox.information(self, "No Assets", msg)
            return

        # Show confirmation with match details
        msg = f"Push {len(items)} files to device?\n\n"
        msg += f"Matched {len(matched_games)} games:\n"
        for match in matched_games[:5]:
            msg += f"  - {match}\n"
        if len(matched_games) > 5:
            msg += f"  ... and {len(matched_games) - 5} more\n"
        if unmatched_games:
            msg += f"\n{len(unmatched_games)} games had no device match and will be skipped."

        reply = QMessageBox.question(
            self,
            "Confirm Push",
            msg,
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._push_items(items)

    def _push_items(self, items: List[Tuple[str, str]]):
        """Push items to device."""
        self.btn_replace_selected.setEnabled(False)
        self.btn_push_all.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(items))
        self.progress_bar.setValue(0)

        self.push_thread = DevicePushThread(self.adb_path, items)
        self.push_thread.progress.connect(self._on_push_progress)
        self.push_thread.finished.connect(self._on_push_finished)
        self.push_thread.error.connect(self._on_push_error)
        self.push_thread.start()

    def _on_push_progress(self, current: int, total: int, filename: str):
        """Handle push progress update."""
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Pushing {current}/{total}: {filename}")

    def _on_push_finished(self, copied: int, errors: int, successful_folders: list):
        """Handle push completion."""
        self.btn_replace_selected.setEnabled(True)
        self.btn_push_all.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)

        deleted_count = 0
        delete_errors = 0

        # Delete local folders if checkbox is checked
        if self.delete_after_push.isChecked() and successful_folders:
            self.status_label.setText(f"Pushed {copied} files. Deleting local folders...")

            for folder_path in successful_folders:
                try:
                    folder = Path(folder_path)
                    if folder.exists() and folder.is_dir():
                        shutil.rmtree(folder)
                        deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {folder_path}: {e}")
                    delete_errors += 1

        # Build status message
        status_parts = [f"Pushed {copied} files to device"]
        if errors > 0:
            status_parts.append(f"{errors} push errors")
        if deleted_count > 0:
            status_parts.append(f"deleted {deleted_count} local folders")
        if delete_errors > 0:
            status_parts.append(f"{delete_errors} delete errors")

        self.status_label.setText(" | ".join(status_parts))

        if errors == 0 and delete_errors == 0:
            msg = f"Successfully pushed {copied} files to device."
            if deleted_count > 0:
                msg += f"\n\nDeleted {deleted_count} local asset folders."
            QMessageBox.information(self, "Success", msg)
        else:
            msg = f"Pushed {copied} files to device."
            if errors > 0:
                msg += f"\n{errors} files failed to push."
            if deleted_count > 0:
                msg += f"\n\nDeleted {deleted_count} local folders."
            if delete_errors > 0:
                msg += f"\n{delete_errors} folders failed to delete."
            QMessageBox.warning(self, "Complete with Errors", msg)

        # Refresh both views
        self._scan_device()
        self._load_local_assets()

    def _on_push_error(self, error: str):
        """Handle push error."""
        self.btn_replace_selected.setEnabled(True)
        self.btn_push_all.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)

        self.status_label.setText(f"Push error: {error}")
        QMessageBox.critical(self, "Push Error", f"Failed to push to device: {error}")
