"""
Existing Assets Tab for iiSU Asset Tool
Browse and manage previously generated icons organized by platform.
Supports re-scraping individual or batch icons with interactive mode.
"""

import threading
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml
from PySide6.QtCore import Qt, Signal, QObject, QSize, Slot
from PySide6.QtGui import QIcon, QPixmap

from iisu_image_utils import load_scaled_pixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QLineEdit, QProgressBar, QComboBox, QCheckBox,
    QMessageBox, QTreeWidget, QTreeWidgetItem, QFrame, QGroupBox,
    QScrollArea, QGridLayout, QDialog
)

from app_paths import get_config_path, get_borders_dir, get_platform_icons_dir
from rom_parser import FOLDER_TO_PLATFORM, IISU_PLATFORM_FOLDERS
import run_backend


class ClickableIconPreview(QFrame):
    """
    Clickable icon preview widget with checkbox selection and double-click support.
    Shows game title on hover and supports batch selection.
    """

    clicked = Signal(object)  # Emits self when clicked
    double_clicked = Signal(object)  # Emits self when double-clicked
    selection_changed = Signal(object, bool)  # Emits (self, is_selected)

    def __init__(self, icon_path: Path, title: str, platform: str, parent=None):
        super().__init__(parent)
        self.icon_path = icon_path
        self.title = title
        self.platform = platform
        self._selected = False

        self.setFrameShape(QFrame.Box)
        self.setLineWidth(2)
        self.setFixedSize(140, 160)
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Icon image
        self.image_label = QLabel()
        self.image_label.setFixedSize(128, 128)
        self.image_label.setScaledContents(True)
        self.image_label.setAlignment(Qt.AlignCenter)

        pixmap = load_scaled_pixmap(str(icon_path), 128)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap)

        layout.addWidget(self.image_label, 0, Qt.AlignCenter)

        # Title label (truncated)
        display_title = title[:18] + "..." if len(title) > 18 else title
        self.title_label = QLabel(display_title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setObjectName("label_muted")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        # Full tooltip
        self.setToolTip(f"{title}\n[{platform}]\n\nDouble-click to re-scrape\nClick to select/deselect")

    def _update_style(self):
        """Update widget style based on selection state."""
        # Use Qt property for theme-aware styling (see iisu_theme.qss)
        self.setProperty("selected", "true" if self._selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

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
        """Handle double-click - trigger re-scrape."""
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self)
        super().mouseDoubleClickEvent(event)


class BackendCallbacks(QObject):
    """Qt signals for backend callbacks."""
    progress = Signal(int, int)  # done, total
    log = Signal(str)
    finished = Signal(bool, str)
    preview = Signal(str)
    current_item = Signal(str, str)  # title, platform


class ExistingAssetsTab(QWidget):
    """Tab for browsing and managing existing generated icons."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._cancel_token = None
        self._worker_thread = None

        # Settings
        self.config_path = str(get_config_path())
        self.output_dir = Path("./output")
        self.android_apps_path = "/storage/emulated/0/Android/media/com.iisulauncher/iiSULauncher/assets/media/android/apps"

        # Special platform key for Android apps
        self.ANDROID_APPS_KEY = "__ANDROID_APPS__"

        # State
        self._all_icons: Dict[str, List[Tuple[Path, str]]] = {}  # platform -> [(icon_path, title)]
        self._icon_widgets: List[ClickableIconPreview] = []
        self._log_messages = []

        self._setup_ui()
        self._load_config()
        self._scan_output_directory()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ===== HEADER CARD =====
        header_card = QFrame()
        header_card.setObjectName("header_card")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(12)

        header = QLabel("My Assets")
        header.setObjectName("label_card_title")
        header_layout.addWidget(header)

        # Total count badge
        self.total_badge = QLabel("0 icons")
        self.total_badge.setObjectName("badge")
        header_layout.addWidget(self.total_badge)

        header_layout.addStretch()

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setMinimumHeight(32)
        self.btn_refresh.setToolTip("Rescan output directory for icons")
        self.btn_refresh.clicked.connect(self._scan_output_directory)
        self.btn_refresh.setObjectName("btn_secondary")
        header_layout.addWidget(self.btn_refresh)

        layout.addWidget(header_card)

        # ===== MAIN CONTENT SPLITTER =====
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Platform tree
        left_card = QFrame()
        left_card.setObjectName("platform_panel")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)

        platform_label = QLabel("Platforms")
        platform_label.setObjectName("label_card_title")
        left_layout.addWidget(platform_label)

        self.platform_tree = QTreeWidget()
        self.platform_tree.setHeaderHidden(True)
        self.platform_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.platform_tree.itemClicked.connect(self._on_platform_selected)
        self.platform_tree.setMinimumWidth(180)
        self.platform_tree.setObjectName("rom_platform_tree")
        left_layout.addWidget(self.platform_tree, 1)

        self.platform_stats = QLabel("No icons found")
        self.platform_stats.setObjectName("label_muted")
        left_layout.addWidget(self.platform_stats)

        splitter.addWidget(left_card)

        # Right panel: Icon grid
        right_card = QFrame()
        right_card.setObjectName("icons_panel")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search games...")
        self.search_input.setMinimumHeight(32)
        self.search_input.textChanged.connect(self._filter_icons)
        filter_row.addWidget(self.search_input, 1)

        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setMinimumHeight(32)
        self.btn_select_all.setMinimumWidth(80)
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_select_all.setObjectName("btn_select")
        filter_row.addWidget(self.btn_select_all)

        self.btn_select_none = QPushButton("Clear")
        self.btn_select_none.setMinimumHeight(32)
        self.btn_select_none.setMinimumWidth(60)
        self.btn_select_none.clicked.connect(self._select_none)
        self.btn_select_none.setObjectName("btn_secondary")
        filter_row.addWidget(self.btn_select_none)

        right_layout.addLayout(filter_row)

        # Icon grid in scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.scroll_area.setWidget(self.grid_widget)

        right_layout.addWidget(self.scroll_area, 1)

        # Selection info badge
        self.selection_info = QLabel("Click to select, double-click to re-scrape")
        self.selection_info.setObjectName("label_muted")
        right_layout.addWidget(self.selection_info)

        splitter.addWidget(right_card)
        splitter.setSizes([200, 600])

        layout.addWidget(splitter, 1)

        # ===== ACTION BAR =====
        action_card = QFrame()
        action_card.setObjectName("action_card")
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(12, 8, 12, 8)
        action_layout.setSpacing(10)

        # Primary action
        self.btn_rescrape_selected = QPushButton("Re-scrape Selected")
        self.btn_rescrape_selected.setMinimumHeight(38)
        self.btn_rescrape_selected.setMinimumWidth(150)
        self.btn_rescrape_selected.setToolTip("Re-scrape all selected icons with interactive mode")
        self.btn_rescrape_selected.setEnabled(False)
        self.btn_rescrape_selected.clicked.connect(self._rescrape_selected)
        self.btn_rescrape_selected.setObjectName("btn_action")
        action_layout.addWidget(self.btn_rescrape_selected)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumHeight(38)
        self.btn_cancel.setMinimumWidth(80)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_processing)
        self.btn_cancel.setObjectName("btn_secondary")
        action_layout.addWidget(self.btn_cancel)

        # Progress bar (uses default QSS styling)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(38)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Ready")
        action_layout.addWidget(self.progress, 1)

        # Delete button
        self.btn_delete_selected = QPushButton("Delete Selected")
        self.btn_delete_selected.setMinimumHeight(38)
        self.btn_delete_selected.setMinimumWidth(120)
        self.btn_delete_selected.setToolTip("Delete selected icons and their asset folders")
        self.btn_delete_selected.setEnabled(False)
        self.btn_delete_selected.clicked.connect(self._delete_selected)
        self.btn_delete_selected.setObjectName("btn_danger")
        action_layout.addWidget(self.btn_delete_selected)

        # Push to device button
        self.btn_push_to_device = QPushButton("Push to Device")
        self.btn_push_to_device.setMinimumHeight(38)
        self.btn_push_to_device.setMinimumWidth(130)
        self.btn_push_to_device.setToolTip("Push selected assets to connected Android device via ADB")
        self.btn_push_to_device.setEnabled(False)
        self.btn_push_to_device.clicked.connect(self._push_to_device)
        self.btn_push_to_device.setObjectName("btn_success")
        action_layout.addWidget(self.btn_push_to_device)

        action_layout.addStretch()

        self.btn_open_output = QPushButton("Output Folder")
        self.btn_open_output.setMinimumHeight(38)
        self.btn_open_output.clicked.connect(self._open_output)
        self.btn_open_output.setObjectName("btn_secondary")
        action_layout.addWidget(self.btn_open_output)

        layout.addWidget(action_card)

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("label_muted")

    def _load_config(self):
        """Load output directory and android apps path from config."""
        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            self.output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
            # Load Android apps path
            rom_settings = cfg.get("rom_directory", {})
            self.android_apps_path = rom_settings.get(
                "android_apps_path",
                "/storage/emulated/0/Android/media/com.iisulauncher/iiSULauncher/assets/media/android/apps"
            )
        except Exception as e:
            print(f"Failed to load config: {e}")

    def _scan_output_directory(self):
        """Scan output directory for existing icons organized by platform."""
        self._all_icons.clear()
        self.platform_tree.clear()
        self._clear_grid()

        if not self.output_dir.exists():
            self.platform_stats.setText("Output directory not found")
            self.status_label.setText("No output directory")
            return

        self.status_label.setText("Scanning output directory...")

        total_icons = 0

        # Scan platform folders
        for platform_folder in sorted(self.output_dir.iterdir()):
            if not platform_folder.is_dir():
                continue

            platform_key = platform_folder.name
            icons = []

            # Scan game folders within platform
            for game_folder in platform_folder.iterdir():
                if not game_folder.is_dir():
                    continue

                # Look for icon.png or icon.jpg
                icon_path = None
                for ext in ['.png', '.jpg', '.jpeg']:
                    candidate = game_folder / f"icon{ext}"
                    if candidate.exists():
                        icon_path = candidate
                        break

                if icon_path:
                    game_title = game_folder.name
                    icons.append((icon_path, game_title))

            if icons:
                self._all_icons[platform_key] = icons
                total_icons += len(icons)

                # Add to platform tree
                item = QTreeWidgetItem([f"{platform_key} ({len(icons)})"])
                item.setData(0, Qt.UserRole, platform_key)

                # Try to load platform icon
                platform_icons_dir = get_platform_icons_dir()
                icon_file = platform_icons_dir / f"{platform_key}.png"
                if icon_file.exists():
                    item.setIcon(0, QIcon(str(icon_file)))

                self.platform_tree.addTopLevelItem(item)

        # Also scan Android apps if path is configured
        android_icons = self._scan_android_apps()
        if android_icons:
            self._all_icons[self.ANDROID_APPS_KEY] = android_icons
            total_icons += len(android_icons)

            # Add Android Apps to platform tree
            item = QTreeWidgetItem([f"Android Apps ({len(android_icons)})"])
            item.setData(0, Qt.UserRole, self.ANDROID_APPS_KEY)
            self.platform_tree.addTopLevelItem(item)

        self.platform_stats.setText(f"{len(self._all_icons)} platforms")
        self.total_badge.setText(f"{total_icons} icons")
        self.status_label.setText(f"Found {total_icons} icons in {len(self._all_icons)} platforms")

        # Auto-select first platform
        if self.platform_tree.topLevelItemCount() > 0:
            first_item = self.platform_tree.topLevelItem(0)
            self.platform_tree.setCurrentItem(first_item)
            self._on_platform_selected(first_item, 0)

    def _on_platform_selected(self, item, column):
        """Handle platform selection - show icons for that platform."""
        if not item:
            return

        platform_key = item.data(0, Qt.UserRole)
        icons = self._all_icons.get(platform_key, [])

        self._clear_grid()
        self._display_icons(icons, platform_key)

    def _scan_android_apps(self) -> List[Tuple[Path, str]]:
        """
        Scan Android apps folder for existing icons via ADB.
        Returns list of (icon_path, app_display_name) tuples.
        """
        import subprocess
        import tempfile
        import shutil

        icons = []

        try:
            # Check if ADB is available
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return icons

            # Check for connected device
            lines = result.stdout.strip().split('\n')
            if len(lines) < 2 or not any('device' in line and 'devices' not in line for line in lines[1:]):
                return icons

            # List app folders in the android apps directory
            list_result = subprocess.run(
                ["adb", "shell", f"ls -1 '{self.android_apps_path}' 2>/dev/null"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if list_result.returncode != 0:
                return icons

            app_folders = [f.strip() for f in list_result.stdout.strip().split('\n') if f.strip()]

            # Create temp directory for pulling icons
            temp_dir = Path(tempfile.mkdtemp(prefix="android_apps_"))

            for app_folder in app_folders:
                if not app_folder or app_folder.startswith('.'):
                    continue

                # Check for icon file
                for ext in ['png', 'jpg', 'jpeg']:
                    icon_remote_path = f"{self.android_apps_path}/{app_folder}/icon.{ext}"
                    check_result = subprocess.run(
                        ["adb", "shell", f"test -f '{icon_remote_path}' && echo exists"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if 'exists' in check_result.stdout:
                        # Pull icon to temp directory
                        local_icon_path = temp_dir / f"{app_folder}_icon.{ext}"
                        pull_result = subprocess.run(
                            ["adb", "pull", icon_remote_path, str(local_icon_path)],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if pull_result.returncode == 0 and local_icon_path.exists():
                            # Convert package name to display name
                            display_name = self._package_to_display_name(app_folder)
                            icons.append((local_icon_path, display_name))
                        break

        except subprocess.TimeoutExpired:
            print("ADB command timed out while scanning Android apps")
        except FileNotFoundError:
            print("ADB not found - Android apps scanning unavailable")
        except Exception as e:
            print(f"Error scanning Android apps: {e}")

        return icons

    def _package_to_display_name(self, package_name: str) -> str:
        """Convert Android package name to display name."""
        # Get last part of package and convert to title case
        app_name = package_name.split('.')[-1]
        # Insert space before capitals (CamelCase to separate words)
        import re
        result = re.sub(r'([a-z])([A-Z])', r'\1 \2', app_name)
        # Replace underscores with spaces and title case
        result = result.replace('_', ' ')
        return ' '.join(word.capitalize() for word in result.split())

    def _display_icons(self, icons: List[Tuple[Path, str]], platform: str):
        """Display icons in the grid."""
        self._icon_widgets.clear()

        # Sort by title
        icons_sorted = sorted(icons, key=lambda x: x[1].lower())

        # Calculate columns based on scroll area width
        num_columns = max(1, (self.scroll_area.width() - 40) // 150)

        for i, (icon_path, title) in enumerate(icons_sorted):
            widget = ClickableIconPreview(icon_path, title, platform)
            widget.double_clicked.connect(self._on_icon_double_clicked)
            widget.selection_changed.connect(self._on_selection_changed)

            row = i // num_columns
            col = i % num_columns
            self.grid_layout.addWidget(widget, row, col)
            self._icon_widgets.append(widget)

        self._update_selection_count()

    def _clear_grid(self):
        """Clear all icons from the grid."""
        for widget in self._icon_widgets:
            self.grid_layout.removeWidget(widget)
            widget.deleteLater()
        self._icon_widgets.clear()

    def _filter_icons(self, text: str):
        """Filter icons by search text."""
        search_lower = text.lower()

        for widget in self._icon_widgets:
            matches = search_lower in widget.title.lower()
            widget.setVisible(matches)

    def _select_all(self):
        """Select all visible icons."""
        for widget in self._icon_widgets:
            if widget.isVisible():
                widget.set_selected(True)
        self._update_selection_count()

    def _select_none(self):
        """Deselect all icons."""
        for widget in self._icon_widgets:
            widget.set_selected(False)
        self._update_selection_count()

    def _get_selected_icons(self) -> List[ClickableIconPreview]:
        """Get list of selected icon widgets."""
        return [w for w in self._icon_widgets if w.is_selected]

    def _update_selection_count(self):
        """Update selection info label."""
        selected = self._get_selected_icons()
        if selected:
            self.selection_info.setText(f"{len(selected)} selected")
            self.btn_rescrape_selected.setEnabled(True)
            self.btn_delete_selected.setEnabled(True)
            self.btn_push_to_device.setEnabled(True)
        else:
            self.selection_info.setText("Click icons to select, double-click to re-scrape")
            self.btn_rescrape_selected.setEnabled(False)
            self.btn_delete_selected.setEnabled(False)
            self.btn_push_to_device.setEnabled(False)

    def _on_selection_changed(self, widget: ClickableIconPreview, is_selected: bool):
        """Handle selection change on a widget."""
        self._update_selection_count()

    def _on_icon_double_clicked(self, widget: ClickableIconPreview):
        """Handle double-click on icon - trigger re-scrape."""
        self._rescrape_icons([widget])

    def _rescrape_selected(self):
        """Re-scrape all selected icons."""
        selected = self._get_selected_icons()
        if not selected:
            return

        reply = QMessageBox.question(
            self,
            "Re-scrape Icons",
            f"Re-scrape {len(selected)} selected icon(s)?\n\n"
            "This will open interactive artwork selection for each game.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._rescrape_icons(selected)

    def _delete_selected(self):
        """Delete selected icons and their asset folders."""
        import shutil

        selected = self._get_selected_icons()
        if not selected:
            return

        # Build list of game folders that will be deleted
        folders_to_delete = []
        for icon_widget in selected:
            game_folder = icon_widget.icon_path.parent
            if game_folder.exists():
                folders_to_delete.append((icon_widget, game_folder))

        if not folders_to_delete:
            QMessageBox.information(self, "Nothing to Delete", "No asset folders found for selected items.")
            return

        # Show confirmation dialog with details
        reply = QMessageBox.warning(
            self,
            "Delete Assets",
            f"This will permanently delete {len(folders_to_delete)} game folder(s) and all their assets.\n\n"
            "This action cannot be undone.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Delete the folders
        deleted_count = 0
        error_count = 0

        for icon_widget, game_folder in folders_to_delete:
            try:
                shutil.rmtree(game_folder)
                deleted_count += 1
            except Exception as e:
                print(f"Failed to delete {game_folder}: {e}")
                error_count += 1

        # Show result
        if error_count > 0:
            QMessageBox.warning(
                self,
                "Delete Complete",
                f"Deleted {deleted_count} folder(s).\n{error_count} folder(s) could not be deleted."
            )
        else:
            self.status_label.setText(f"Deleted {deleted_count} folder(s)")

        # Refresh the view
        self._scan_output_directory()

    def _push_to_device(self):
        """Push selected assets to connected Android device via ADB."""
        import subprocess
        import sys
        import shutil

        selected = self._get_selected_icons()
        if not selected:
            return

        # Check for ADB
        from adb_setup import is_adb_installed

        def get_adb_path():
            adb_path = shutil.which("adb")
            if adb_path:
                return adb_path
            is_installed, adb_exe = is_adb_installed()
            if is_installed and adb_exe:
                return str(adb_exe)
            return None

        adb_path = get_adb_path()
        if not adb_path:
            QMessageBox.warning(
                self,
                "ADB Not Found",
                "ADB (Android Debug Bridge) is not installed or not in PATH.\n\n"
                "Please install Android SDK Platform Tools to use this feature."
            )
            return

        # Check for connected device
        try:
            kwargs = {'capture_output': True, 'text': True}
            if sys.platform == 'win32':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run([adb_path, "devices"], timeout=10, **kwargs)
            lines = result.stdout.strip().split('\n')[1:]
            devices = [l.split('\t')[0] for l in lines if '\tdevice' in l]

            if not devices:
                QMessageBox.warning(
                    self,
                    "No Device Connected",
                    "No Android device is connected.\n\n"
                    "Please connect your device with USB debugging enabled."
                )
                return
        except Exception as e:
            QMessageBox.warning(self, "ADB Error", f"Failed to check devices: {e}")
            return

        # Load device path from config
        device_base_path = "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"
        cfg_path = Path(self.config_path)
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                device_base_path = cfg.get("device", {}).get(
                    "path",
                    "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"
                )
            except Exception:
                pass

        # Group files by platform/game
        files_to_push = []
        for icon_widget in selected:
            game_folder = icon_widget.icon_path.parent
            platform = icon_widget.platform
            game_name = icon_widget.title

            # Device path for this game
            device_game_path = f"{device_base_path}/{platform}/{game_name}"

            # Add all files in the game folder
            if game_folder.exists():
                for file_path in game_folder.iterdir():
                    if file_path.is_file():
                        files_to_push.append((
                            str(file_path),
                            f"{device_game_path}/{file_path.name}"
                        ))

        if not files_to_push:
            QMessageBox.information(self, "Nothing to Push", "No files found to push.")
            return

        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Push to Device",
            f"Push {len(files_to_push)} files from {len(selected)} game(s) to device?\n\n"
            f"Target: {device_base_path}\n\n"
            "Note: This will overwrite existing files on the device.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Push files
        self.progress.setVisible(True)
        self.progress.setRange(0, len(files_to_push))
        self.progress.setValue(0)
        self.btn_push_to_device.setEnabled(False)
        self.status_label.setText("Pushing to device...")

        pushed = 0
        errors = 0

        for i, (local_path, device_path) in enumerate(files_to_push):
            self.progress.setValue(i + 1)
            self.progress.setFormat(f"{i + 1}/{len(files_to_push)}")

            try:
                kwargs = {'capture_output': True, 'text': True}
                if sys.platform == 'win32':
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

                result = subprocess.run(
                    [adb_path, "push", local_path, device_path],
                    timeout=60,
                    **kwargs
                )

                if result.returncode == 0:
                    pushed += 1
                else:
                    errors += 1
                    print(f"Push failed: {result.stderr}")
            except Exception as e:
                errors += 1
                print(f"Push error: {e}")

        # Done
        self.progress.setVisible(False)
        self.progress.setFormat("Ready")
        self.btn_push_to_device.setEnabled(True)

        if errors > 0:
            QMessageBox.warning(
                self,
                "Push Complete",
                f"Pushed {pushed} files to device.\n{errors} files failed to push."
            )
        else:
            QMessageBox.information(
                self,
                "Push Complete",
                f"Successfully pushed {pushed} files to device."
            )
            self.status_label.setText(f"Pushed {pushed} files to device")

        # Deselect after successful push
        if errors == 0:
            self._select_none()

    def _rescrape_icons(self, icons: List[ClickableIconPreview]):
        """Re-scrape the given icons with interactive mode."""
        if not icons:
            return

        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            QMessageBox.warning(self, "Config Missing", "Configuration file not found.")
            return

        # Group by platform
        by_platform: Dict[str, List[ClickableIconPreview]] = {}
        for icon in icons:
            if icon.platform not in by_platform:
                by_platform[icon.platform] = []
            by_platform[icon.platform].append(icon)

        total = len(icons)

        # Setup UI for processing
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_rescrape_selected.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status_label.setText("Re-scraping...")

        self._cancel_token = run_backend.CancelToken()
        callbacks = BackendCallbacks()
        callbacks.progress.connect(self._on_progress)
        callbacks.log.connect(self._on_log)
        callbacks.finished.connect(self._on_finished)
        callbacks.preview.connect(self._on_preview)

        def _run():
            try:
                done_count = 0
                for platform_key, platform_icons in by_platform.items():
                    if self._cancel_token.is_cancelled:
                        break

                    # Get border path for this platform
                    borders_dir = get_borders_dir()
                    border_path = borders_dir / f"{platform_key}.png"
                    if not border_path.exists():
                        # Try lowercase folder name mapping
                        for folder_name, p_key in FOLDER_TO_PLATFORM.items():
                            if p_key == platform_key:
                                border_path = borders_dir / f"{p_key}.png"
                                break

                    for icon_widget in platform_icons:
                        if self._cancel_token.is_cancelled:
                            break

                        title = icon_widget.title
                        callbacks.current_item.emit(title, platform_key)
                        callbacks.progress.emit(done_count, total)

                        # Determine output path (same as existing)
                        output_path = icon_widget.icon_path.parent

                        # Run with force_rescrape to bypass existing check
                        ok, msg = run_backend.run_job(
                            config_path=cfg_path,
                            platforms=[platform_key],
                            workers=1,
                            limit=1,
                            cancel=self._cancel_token,
                            callbacks={
                                "log": lambda m: callbacks.log.emit(str(m)),
                                "preview": lambda p: callbacks.preview.emit(str(p)),
                                "request_selection": self._request_artwork_selection,
                            },
                            search_term=title,
                            interactive_mode=True,
                            download_heroes=False,
                            force_rescrape=True,  # Bypass existing check
                            output_path_override=str(output_path),
                            border_path_override=str(border_path) if border_path.exists() else None,
                        )

                        done_count += 1
                        callbacks.progress.emit(done_count, total)

                callbacks.finished.emit(True, f"Re-scraped {done_count} icons")

            except Exception as e:
                import traceback
                callbacks.log.emit(f"Error: {e}\n{traceback.format_exc()}")
                callbacks.finished.emit(False, f"Error: {e}")

        self._worker_thread = threading.Thread(target=_run, daemon=True)
        self._worker_thread.start()

    def _request_artwork_selection(self, title: str, platform: str, artwork_options):
        """Request artwork selection from user (called from worker thread)."""
        from artwork_picker_dialog import ArtworkPickerDialog
        from queue import Queue
        from PySide6.QtCore import QMetaObject, Qt

        self._dialog_title = title
        self._dialog_platform = platform
        self._dialog_options = artwork_options
        self._dialog_result = Queue()

        QMetaObject.invokeMethod(
            self,
            "_show_selection_dialog",
            Qt.ConnectionType.BlockingQueuedConnection
        )

        return self._dialog_result.get()

    @Slot()
    def _show_selection_dialog(self):
        """Show artwork selection dialog on main thread."""
        from artwork_picker_dialog import ArtworkPickerDialog
        try:
            # Show filter toggle for icon selection
            dialog = ArtworkPickerDialog(
                title=self._dialog_title,
                platform=self._dialog_platform,
                artwork_options=self._dialog_options,
                parent=self,
                asset_type="icon",
                show_filter=True
            )
            dialog.exec()
            self._dialog_result.put(dialog.get_selected_index())
        except Exception as e:
            print(f"Dialog error: {e}")
            self._dialog_result.put(None)

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
            self.progress.setFormat(f"{done}/{total}")

    def _on_log(self, msg: str):
        """Handle log message."""
        self._log_messages.append(msg)
        if len(self._log_messages) > 500:
            self._log_messages = self._log_messages[-500:]

    def _on_preview(self, path: str):
        """Handle preview - update icon if it matches a displayed one."""
        path_obj = Path(path)

        # Find matching widget and update its image
        for widget in self._icon_widgets:
            if widget.icon_path.parent == path_obj.parent:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    widget.image_label.setPixmap(pixmap)
                    widget.icon_path = path_obj
                break

    def _on_finished(self, ok: bool, msg: str):
        """Handle processing completion."""
        self.btn_rescrape_selected.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.status_label.setText(msg if ok else f"Failed: {msg}")

        if ok:
            # Deselect all after successful re-scrape
            self._select_none()

    def _open_output(self):
        """Open output directory."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        if self.output_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_dir.absolute())))
        else:
            QMessageBox.warning(self, "Error", "Output directory not found.")
