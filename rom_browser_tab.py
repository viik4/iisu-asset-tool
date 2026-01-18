"""
ROM Browser Tab for iiSU Asset Tool
Browse ROMs from iiSU directory or manual folder selection and generate icons.
"""
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from PySide6.QtCore import Qt, Signal, QObject, QSize, Slot
from PySide6.QtGui import QIcon, QPixmap
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
from app_paths import get_config_path, get_borders_dir, get_platform_icons_dir
from icon_generator_tab import ClickableIconPreview
import run_backend
import subprocess


def _get_subprocess_flags():
    """Get platform-specific subprocess flags to hide console on Windows."""
    if sys.platform == 'win32':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}


class BackendCallbacks(QObject):
    """Qt signals for backend callbacks."""
    progress = Signal(int, int)  # done, total
    log = Signal(str)
    finished = Signal(bool, str)
    preview = Signal(str, str, str)  # path, title, platform
    current_item = Signal(str, str)  # title, platform


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
        self.hero_enabled = True
        self.hero_count = 1
        self.fallback_settings = {}  # Fallback icon settings
        self.screenshot_settings = {"enabled": False, "count": 3}  # Screenshot settings
        self.device_settings = {"enabled": False, "path": "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"}  # Device copy settings
        self.logo_settings = {"scrape_logos": True, "fallback_to_boxart": True}  # Logo/title settings

        # Track selected ROMs across platform changes (key: "platform|path")
        self._selected_roms = set()

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Source Selection Group
        source_group = QGroupBox("ROM Source")
        source_layout = QVBoxLayout(source_group)
        source_layout.setSpacing(6)

        # Path row
        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select a ROM folder or connect a device...")
        self.path_input.setReadOnly(False)
        path_row.addWidget(self.path_input, 1)

        self.btn_browse = QPushButton("Browse")
        self.btn_browse.setMinimumWidth(70)
        self.btn_browse.clicked.connect(self._browse_folder)
        path_row.addWidget(self.btn_browse)

        self.btn_refresh = QPushButton("Scan")
        self.btn_refresh.setMinimumWidth(60)
        self.btn_refresh.clicked.connect(self._scan_directory)
        path_row.addWidget(self.btn_refresh)

        source_layout.addLayout(path_row)

        # Device buttons row
        device_row = QHBoxLayout()
        device_row.setSpacing(8)

        self.btn_select_drive = QPushButton("USB Drive")
        self.btn_select_drive.setToolTip("Select from USB drives and external devices")
        self.btn_select_drive.clicked.connect(self._show_drive_selector)
        device_row.addWidget(self.btn_select_drive)

        self.btn_adb_scan = QPushButton("Android (ADB)")
        self.btn_adb_scan.setToolTip("Fast scan Android devices via ADB")
        self.btn_adb_scan.clicked.connect(self._show_adb_scan_dialog)
        device_row.addWidget(self.btn_adb_scan)

        self.btn_manual_add = QPushButton("Manual Entry")
        self.btn_manual_add.setToolTip("Manually enter game titles")
        self.btn_manual_add.clicked.connect(self._show_manual_add_dialog)
        device_row.addWidget(self.btn_manual_add)

        device_row.addStretch()
        source_layout.addLayout(device_row)

        layout.addWidget(source_group)

        # Main content splitter
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Platform tree
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        platform_label = QLabel("Platforms")
        platform_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        left_layout.addWidget(platform_label)

        self.platform_tree = QTreeWidget()
        self.platform_tree.setHeaderHidden(True)
        self.platform_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.platform_tree.itemSelectionChanged.connect(self._on_platform_selected)
        self.platform_tree.setMinimumWidth(180)
        self.platform_tree.setObjectName("rom_platform_tree")
        left_layout.addWidget(self.platform_tree, 1)

        # Platform selection buttons
        platform_btn_row = QHBoxLayout()
        platform_btn_row.setSpacing(4)
        platform_btn_row.setContentsMargins(0, 4, 0, 0)

        self.select_all_platforms_btn = QPushButton("All")
        self.select_all_platforms_btn.setFixedHeight(24)
        self.select_all_platforms_btn.clicked.connect(self._select_all_platforms)
        platform_btn_row.addWidget(self.select_all_platforms_btn, 1)

        self.deselect_all_platforms_btn = QPushButton("None")
        self.deselect_all_platforms_btn.setFixedHeight(24)
        self.deselect_all_platforms_btn.clicked.connect(self._deselect_all_platforms)
        platform_btn_row.addWidget(self.deselect_all_platforms_btn, 1)

        left_layout.addLayout(platform_btn_row)

        self.platform_stats = QLabel("No ROMs scanned")
        self.platform_stats.setStyleSheet("font-size: 10px; opacity: 0.6;")
        left_layout.addWidget(self.platform_stats)

        splitter.addWidget(left_panel)

        # Right panel: Game list
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # Search and selection row
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search games...")
        self.search_input.textChanged.connect(self._filter_games)
        search_row.addWidget(self.search_input, 1)

        self.btn_select_all = QPushButton("All")
        self.btn_select_all.setToolTip("Select all visible games")
        self.btn_select_all.setMinimumWidth(50)
        self.btn_select_all.clicked.connect(self._select_all_games)
        search_row.addWidget(self.btn_select_all)

        self.btn_select_none = QPushButton("None")
        self.btn_select_none.setToolTip("Deselect all visible games")
        self.btn_select_none.setMinimumWidth(50)
        self.btn_select_none.clicked.connect(self._select_no_games)
        search_row.addWidget(self.btn_select_none)

        self.btn_clear_all = QPushButton("Clear All")
        self.btn_clear_all.setToolTip("Clear all selections across all platforms")
        self.btn_clear_all.setMinimumWidth(70)
        self.btn_clear_all.clicked.connect(self._clear_all_selections)
        search_row.addWidget(self.btn_clear_all)

        right_layout.addLayout(search_row)

        # Games list
        self.games_list = QListWidget()
        self.games_list.setSelectionMode(QListWidget.MultiSelection)
        self.games_list.setAlternatingRowColors(False)  # Disable for cleaner look
        self.games_list.setObjectName("rom_games_list")
        right_layout.addWidget(self.games_list, 1)

        self.games_info = QLabel("Select a platform to view games")
        self.games_info.setStyleSheet("font-size: 10px; opacity: 0.6;")
        right_layout.addWidget(self.games_info)

        splitter.addWidget(right_panel)
        splitter.setSizes([200, 500])

        layout.addWidget(splitter, 1)

        # Options and Actions row (combined)
        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)

        # Region preference dropdown
        controls_row.addWidget(QLabel("Region:"))
        self.region_combo = QComboBox()
        self.region_combo.setToolTip("Filter games by region or prefer specific region artwork")
        self.region_combo.addItem("Any Region", "any")
        self.region_combo.addItem("USA (NTSC-U)", "USA")
        self.region_combo.addItem("Europe (PAL)", "EUR")
        self.region_combo.addItem("Japan (NTSC-J)", "JPN")
        self.region_combo.addItem("World", "World")
        self.region_combo.setMinimumWidth(130)
        self.region_combo.currentIndexChanged.connect(self._on_region_changed)
        controls_row.addWidget(self.region_combo)

        controls_row.addSpacing(8)

        # Options
        self.hero_check = QCheckBox("Hero Images")
        self.hero_check.setChecked(True)
        self.hero_check.setToolTip("Download hero/banner images")
        controls_row.addWidget(self.hero_check)

        self.interactive_check = QCheckBox("Interactive")
        self.interactive_check.setToolTip("Manually select artwork for each game")
        controls_row.addWidget(self.interactive_check)

        controls_row.addStretch()

        # Action buttons
        self.btn_process = QPushButton("Generate Icons")
        self.btn_process.setObjectName("btn_start")
        self.btn_process.setMinimumWidth(120)
        self.btn_process.clicked.connect(self._start_processing)
        controls_row.addWidget(self.btn_process)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_processing)
        controls_row.addWidget(self.btn_cancel)

        self.btn_open_output = QPushButton("Output")
        self.btn_open_output.setToolTip("Open output folder")
        self.btn_open_output.clicked.connect(self._open_output)
        controls_row.addWidget(self.btn_open_output)

        self.btn_show_logs = QPushButton("Logs")
        self.btn_show_logs.setToolTip("View processing logs")
        self.btn_show_logs.clicked.connect(self._show_logs_dialog)
        controls_row.addWidget(self.btn_show_logs)

        layout.addLayout(controls_row)

        # Progress section
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setMinimumHeight(20)
        progress_row.addWidget(self.progress, 1)

        layout.addLayout(progress_row)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 11px; opacity: 0.6;")
        layout.addWidget(self.status_label)

        # Preview panel (collapsible/smaller)
        self.preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(self.preview_group)
        preview_layout.setContentsMargins(6, 6, 6, 6)

        # Preview controls row
        preview_controls = QHBoxLayout()
        preview_controls.setSpacing(6)

        self.btn_popout_preview = QPushButton("Pop Out")
        self.btn_popout_preview.setToolTip("Open preview in separate window")
        self.btn_popout_preview.setMinimumWidth(90)
        self.btn_popout_preview.clicked.connect(self._popout_preview)
        preview_controls.addWidget(self.btn_popout_preview)

        self.btn_hide_preview = QPushButton("Hide")
        self.btn_hide_preview.setToolTip("Hide preview panel")
        self.btn_hide_preview.setMinimumWidth(70)
        self.btn_hide_preview.clicked.connect(self._toggle_preview_visibility)
        preview_controls.addWidget(self.btn_hide_preview)

        preview_controls.addStretch()

        # Selection controls
        self.btn_select_all_preview = QPushButton("All")
        self.btn_select_all_preview.setToolTip("Select all icons")
        self.btn_select_all_preview.clicked.connect(self._select_all_previews)
        preview_controls.addWidget(self.btn_select_all_preview)

        self.btn_select_none_preview = QPushButton("None")
        self.btn_select_none_preview.setToolTip("Deselect all icons")
        self.btn_select_none_preview.clicked.connect(self._select_none_previews)
        preview_controls.addWidget(self.btn_select_none_preview)

        self.btn_rescrape_selected = QPushButton("Re-scrape Selected")
        self.btn_rescrape_selected.setToolTip("Re-scrape selected icons with artwork selection")
        self.btn_rescrape_selected.clicked.connect(self._rescrape_selected)
        preview_controls.addWidget(self.btn_rescrape_selected)

        preview_layout.addLayout(preview_controls)

        # Selection count label
        self.preview_selection_label = QLabel("0 selected")
        self.preview_selection_label.setStyleSheet("font-size: 10px; color: #888;")
        preview_layout.addWidget(self.preview_selection_label)

        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setWidgetResizable(True)
        self.preview_scroll_area.setMinimumHeight(150)
        self.preview_scroll_area.setMaximumHeight(220)

        self.preview_widget = QWidget()
        self.preview_grid = QGridLayout(self.preview_widget)
        self.preview_grid.setSpacing(6)
        self.preview_scroll_area.setWidget(self.preview_widget)

        preview_layout.addWidget(self.preview_scroll_area)
        layout.addWidget(self.preview_group)

        # Track preview visibility and popout window
        self._preview_visible = True
        self._preview_popout_window = None
        self._rescrape_in_progress = False

        self.preview_items = []
        self._log_messages = []

    def _load_settings(self):
        """Load settings from config file."""
        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            rom_cfg = cfg.get("rom_directory", {})
            self.rom_path = rom_cfg.get("rom_path", "")

            hero_cfg = cfg.get("hero_images", {})
            self.hero_enabled = hero_cfg.get("enabled", True)
            self.hero_count = hero_cfg.get("count", 1)

            # Update UI
            if self.rom_path:
                self.path_input.setText(self.rom_path)
            self.hero_check.setChecked(self.hero_enabled)

            # Set scanner path if we have one saved
            if self.rom_path and Path(self.rom_path).exists():
                self._scanner.set_iisu_path(Path(self.rom_path))

        except Exception as e:
            print(f"Failed to load ROM browser settings: {e}")

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
        path_label.setStyleSheet("color: #888; font-size: 11px;")
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
        """Scan the selected directory for ROMs."""
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

        # Clear previous data
        self.platform_tree.clear()
        self.games_list.clear()

        results = {}

        # Check if this is an MTP device path (Android/portable device)
        if is_mtp_path(path_str):
            # Parse MTP path - could be "This PC\Device Name\subfolder" or similar
            # Try to extract device name and subfolder
            cleaned_path = path_str.replace("This PC\\", "").replace("This PC/", "")

            # Split by either forward or back slash
            if "\\" in cleaned_path:
                parts = cleaned_path.split("\\")
            else:
                parts = cleaned_path.split("/")

            if parts:
                device_name = parts[0]
                subfolder = "/".join(parts[1:]) if len(parts) > 1 else ""

                # TRY ADB FIRST - it's up to 28x faster than MTP
                adb_available = check_adb_available()
                adb_devices = get_adb_devices() if adb_available else []

                if adb_devices:
                    # ADB is available and device(s) connected - use ADB!
                    self.status_label.setText(f"Scanning via ADB (fast mode): {device_name}...")

                    # Force UI update
                    from PySide6.QtWidgets import QApplication
                    QApplication.processEvents()

                    # Convert MTP path to Android path
                    # Common mapping: "Internal shared storage/Download/roms" -> "/sdcard/Download/roms"
                    adb_path = subfolder.replace("Internal shared storage", "/sdcard").replace("Internal Storage", "/sdcard")
                    if not adb_path.startswith("/"):
                        adb_path = f"/sdcard/{adb_path}" if adb_path else "/sdcard/roms"

                    # Use first device if only one, or let scan_adb_device auto-detect
                    device_id = adb_devices[0][0] if len(adb_devices) == 1 else ""

                    print(f"ADB scan: Using device {device_id or '(auto)'}, path: {adb_path}")
                    results = scan_adb_device(device_id, adb_path)

                    if results:
                        # ADB scan successful!
                        print(f"ADB scan successful: {len(results)} platforms found")
                    else:
                        # ADB scan failed - try MTP as fallback
                        print("ADB scan returned no results, falling back to MTP...")
                        self.status_label.setText(f"Scanning MTP device (fallback): {device_name}...")
                        QApplication.processEvents()
                        results = scan_mtp_device(device_name, subfolder)
                else:
                    # ADB not available - use MTP (slower)
                    if adb_available:
                        self.status_label.setText(f"Scanning MTP device: {device_name}... (ADB available but no device connected)")
                    else:
                        self.status_label.setText(f"Scanning MTP device: {device_name}... (install ADB for faster scans)")

                    # Force UI update before long operation
                    from PySide6.QtWidgets import QApplication
                    QApplication.processEvents()

                    results = scan_mtp_device(device_name, subfolder)

                if not results:
                    # Build helpful error message
                    adb_tip = ""
                    if not adb_available:
                        adb_tip = (
                            "\n\nTIP: Install ADB for much faster scanning:\n"
                            "1. Download Android SDK Platform Tools\n"
                            "2. Extract to C:\\adb\\ or add to PATH\n"
                            "3. Enable USB Debugging on your device"
                        )
                    elif not adb_devices:
                        adb_tip = (
                            "\n\nTIP: ADB is installed but no device detected:\n"
                            "1. Enable USB Debugging on your device\n"
                            "2. Connect via USB (not just MTP)\n"
                            "3. Authorize the USB debugging prompt"
                        )

                    QMessageBox.warning(
                        self,
                        "Scan Failed",
                        f"Could not scan the portable device.\n\n"
                        f"Device: {device_name}\n"
                        f"Path: {subfolder}\n\n"
                        "Possible causes:\n"
                        "- Device is not connected or is locked\n"
                        "- Path doesn't contain recognized platform folders\n"
                        "- Scan timed out (device has too many files)\n\n"
                        "Try 'Add Games Manually' button to enter titles directly."
                        f"{adb_tip}"
                    )
                    self.btn_refresh.setEnabled(True)
                    self.status_label.setText("Scan failed")
                    return
        else:
            # Standard filesystem path
            path = Path(path_str)
            if not path.exists():
                QMessageBox.warning(
                    self,
                    "Folder Not Found",
                    f"The selected folder does not exist or is not accessible:\n\n{path_str}\n\n"
                    "If using external storage, make sure the device is connected."
                )
                self.btn_refresh.setEnabled(True)
                self.status_label.setText("Ready")
                return

            # Try to detect platform from folder name, or scan as multi-platform structure
            platform = detect_platform_from_folder(path.name)
            if platform:
                # Single platform folder
                games = scan_generic_folder(path, platform)
                results = {platform: games}
            else:
                # Multi-platform structure (like iiSU)
                self._scanner.set_iisu_path(path)
                results = self._scanner.scan(force_refresh=True)

        # Populate platform tree
        total_games = 0
        for platform_key in sorted(results.keys()):
            games = results[platform_key]
            if not games:
                continue

            total_games += len(games)

            # Create platform item
            item = QTreeWidgetItem([f"{platform_key} ({len(games)})"])
            item.setData(0, Qt.UserRole, platform_key)
            item.setData(0, Qt.UserRole + 1, games)

            # Try to load platform icon (from platform_icons dir, not borders)
            platform_icons_dir = get_platform_icons_dir()
            icon_path = platform_icons_dir / f"{platform_key}.png"
            if icon_path.exists():
                item.setIcon(0, QIcon(str(icon_path)))

            self.platform_tree.addTopLevelItem(item)

        self.platform_stats.setText(f"{len(results)} platforms, {total_games} games total")
        self.status_label.setText(f"Scanned {total_games} games across {len(results)} platforms")
        self.btn_refresh.setEnabled(True)

        # Auto-select first platform if available
        if self.platform_tree.topLevelItemCount() > 0:
            first_item = self.platform_tree.topLevelItem(0)
            first_item.setSelected(True)
            self._on_platform_selected()

    def _select_all_platforms(self):
        """Select all platforms in the tree."""
        self.platform_tree.blockSignals(True)
        for i in range(self.platform_tree.topLevelItemCount()):
            self.platform_tree.topLevelItem(i).setSelected(True)
        self.platform_tree.blockSignals(False)
        self._on_platform_selected()

    def _deselect_all_platforms(self):
        """Deselect all platforms in the tree."""
        self.platform_tree.clearSelection()
        self.games_list.clear()
        self.games_info.setText("No platform selected")

    def _on_platform_selected(self):
        """Handle platform selection in tree - supports multiple platforms."""
        selected_items = self.platform_tree.selectedItems()

        if not selected_items:
            self.games_list.clear()
            self.games_info.setText("No platform selected")
            return

        # Save current selections before clearing the list
        self._save_current_selections()

        self.games_list.clear()

        # Get selected region filter
        region_filter = self.region_combo.currentData()

        total_games = 0
        filtered_count = 0
        platform_names = []

        for item in selected_items:
            platform_key = item.data(0, Qt.UserRole)
            games = item.data(0, Qt.UserRole + 1)

            if not games:
                continue

            platform_names.append(platform_key)
            total_games += len(games)

            for title, path in games:
                # Detect region from filename
                filename = Path(path).name if path else title
                detected_region = detect_region(filename, Path(path) if path else None, platform_key)

                # Apply region filter
                if region_filter != "any":
                    if detected_region != region_filter and detected_region != "World":
                        # Skip games not matching filter (World matches any region)
                        continue

                filtered_count += 1

                # Display title with region and platform
                display_text = f"{title}"
                if detected_region and detected_region != "Unknown":
                    display_text = f"{title} [{detected_region}]"

                # Add platform tag if multiple platforms selected
                if len(selected_items) > 1:
                    display_text = f"[{platform_key}] {display_text}"

                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.UserRole, {
                    "title": title,
                    "path": str(path),
                    "platform": platform_key,
                    "region": detected_region
                })

                # Check if this ROM was previously selected
                rom_key = f"{platform_key}|{path}"
                if rom_key in self._selected_roms:
                    list_item.setSelected(True)
                else:
                    list_item.setSelected(False)

                self.games_list.addItem(list_item)

        # Build info text
        if len(selected_items) == 1:
            platform_text = platform_names[0] if platform_names else "Unknown"
        else:
            platform_text = f"{len(selected_items)} platforms"

        # Show selection count
        selected_count = len(self._selected_roms)
        if region_filter != "any":
            self.games_info.setText(f"{filtered_count}/{total_games} games in {platform_text} (filtered: {region_filter}) | {selected_count} selected across all platforms")
        else:
            self.games_info.setText(f"{total_games} games in {platform_text} | {selected_count} selected across all platforms")

    def _save_current_selections(self):
        """Save currently selected ROMs to the persistent selection set."""
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            data = item.data(Qt.UserRole)
            if data:
                rom_key = f"{data.get('platform', '')}|{data.get('path', '')}"
                if item.isSelected():
                    self._selected_roms.add(rom_key)
                else:
                    self._selected_roms.discard(rom_key)

    def _on_region_changed(self, index):
        """Handle region filter change - refresh the current platform's games list."""
        selected_items = self.platform_tree.selectedItems()
        if selected_items:
            self._on_platform_selected()

    def _filter_games(self, text):
        """Filter games list by search text."""
        search_lower = text.lower()

        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            data = item.data(Qt.UserRole)
            title = data.get("title", "").lower()
            item.setHidden(search_lower not in title)

    def _select_all_games(self):
        """Select all visible games."""
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            if not item.isHidden():
                item.setSelected(True)
                # Also add to persistent selection
                data = item.data(Qt.UserRole)
                if data:
                    rom_key = f"{data.get('platform', '')}|{data.get('path', '')}"
                    self._selected_roms.add(rom_key)
        self._update_selection_info()

    def _select_no_games(self):
        """Deselect all visible games."""
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            if not item.isHidden():
                item.setSelected(False)
                # Also remove from persistent selection
                data = item.data(Qt.UserRole)
                if data:
                    rom_key = f"{data.get('platform', '')}|{data.get('path', '')}"
                    self._selected_roms.discard(rom_key)
        self._update_selection_info()

    def _clear_all_selections(self):
        """Clear all selections across all platforms."""
        self._selected_roms.clear()
        for i in range(self.games_list.count()):
            self.games_list.item(i).setSelected(False)
        self._update_selection_info()

    def _update_selection_info(self):
        """Update the selection count in the info label."""
        selected_items = self.platform_tree.selectedItems()
        if not selected_items:
            return

        total_games = self.games_list.count()
        selected_count = len(self._selected_roms)

        if len(selected_items) == 1:
            platform_key = selected_items[0].data(0, Qt.UserRole)
            platform_text = platform_key if platform_key else "Unknown"
        else:
            platform_text = f"{len(selected_items)} platforms"

        self.games_info.setText(f"{total_games} games in {platform_text} | {selected_count} selected across all platforms")

    def _get_selected_games(self) -> List[Dict]:
        """Get list of selected games with their data from all platforms."""
        # First, save current visible selections
        self._save_current_selections()

        # Now get all selected games from all platforms
        selected = []

        # Iterate through all platforms in the tree
        for i in range(self.platform_tree.topLevelItemCount()):
            platform_item = self.platform_tree.topLevelItem(i)
            platform_key = platform_item.data(0, Qt.UserRole)
            games = platform_item.data(0, Qt.UserRole + 1)

            if not games:
                continue

            for title, path in games:
                rom_key = f"{platform_key}|{path}"
                if rom_key in self._selected_roms:
                    # Detect region for this game
                    filename = Path(path).name if path else title
                    detected_region = detect_region(filename, Path(path) if path else None, platform_key)

                    selected.append({
                        "title": title,
                        "path": str(path),
                        "platform": platform_key,
                        "region": detected_region
                    })

        return selected

    def _start_processing(self):
        """Start processing selected games."""
        selected = self._get_selected_games()

        if not selected:
            QMessageBox.information(self, "No Selection", "Please select games to process.")
            return

        # Group by platform
        by_platform: Dict[str, List[str]] = {}
        for game in selected:
            plat = game["platform"]
            if plat not in by_platform:
                by_platform[plat] = []
            by_platform[plat].append(game["title"])

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
        total_games = sum(len(titles) for titles in by_platform.values())

        # Load config once to get output directory and format (avoid loading per-ROM)
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            output_dir = cfg_path.parent / cfg.get("paths", {}).get("output_dir", "./output")
            export_format = str(cfg.get("export_format", "JPEG")).upper()
            file_ext = "jpg" if export_format == "JPEG" else "png"
        except Exception:
            output_dir = cfg_path.parent / "output"
            file_ext = "png"

        # Process each platform's games
        def _run():
            try:
                done_count = 0
                skipped_count = 0
                for platform_key, titles in by_platform.items():
                    if self._cancel_token.is_cancelled:
                        break

                    # Get platform output folder name from config
                    platforms_cfg = cfg.get("platforms", {}) or {}
                    pconf = platforms_cfg.get(platform_key, {})
                    folder_name = pconf.get("folder_name", platform_key.lower())
                    out_plat = output_dir / folder_name

                    for title in titles:
                        if self._cancel_token.is_cancelled:
                            break

                        # Check if output already exists BEFORE calling run_job
                        # This avoids expensive config parsing for already-scraped ROMs
                        slug = run_backend.safe_slug(title)
                        out_path = out_plat / slug / f"icon.{file_ext}"

                        if out_path.exists():
                            # Already scraped - skip without calling run_job
                            callbacks.log.emit(f"[SKIP] {platform_key}: {title} - Already exists")
                            done_count += 1
                            skipped_count += 1
                            callbacks.progress.emit(done_count, total_games)
                            continue

                        # Emit current item being processed
                        callbacks.current_item.emit(title, platform_key)
                        callbacks.progress.emit(done_count, total_games)

                        # Process single game - limit=1 ensures only one icon per ROM
                        ok, msg = run_backend.run_job(
                            config_path=cfg_path,
                            platforms=[platform_key],
                            workers=1,
                            limit=1,  # Only generate one icon per scanned ROM
                            cancel=self._cancel_token,
                            callbacks={
                                "log": lambda m: callbacks.log.emit(str(m)),
                                "preview": lambda p, t="", pl="": callbacks.preview.emit(str(p), t, pl),
                                "request_selection": self._request_artwork_selection,
                            },
                            search_term=title,
                            interactive_mode=self.interactive_check.isChecked(),
                            download_heroes=self.hero_check.isChecked(),
                            hero_count=1,  # Only one hero image per ROM
                            fallback_settings=self.fallback_settings,
                            download_screenshots=self.screenshot_settings.get("enabled", False),
                            screenshot_count=self.screenshot_settings.get("count", 3),
                            copy_to_device=self.device_settings.get("enabled", False),
                            device_path=self.device_settings.get("path", ""),
                            scrape_logos=self.logo_settings.get("scrape_logos", True),
                            logo_fallback_to_boxart=self.logo_settings.get("fallback_to_boxart", True)
                        )

                        done_count += 1
                        callbacks.progress.emit(done_count, total_games)

                if skipped_count > 0:
                    callbacks.finished.emit(True, f"Processing complete ({skipped_count} already existed, skipped)")
                else:
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

            dialog = ArtworkPickerDialog(
                title=self._dialog_title,
                platform=self._dialog_platform,
                artwork_options=self._dialog_options,
                parent=self
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

    def _add_preview(self, path: str, title: str = "", platform: str = ""):
        """Add a generated icon to the preview grid."""
        path_obj = Path(path)
        if not path_obj.exists():
            return

        # Use filename as title fallback
        if not title:
            title = path_obj.stem

        # Create clickable preview widget
        preview_item = ClickableIconPreview(path, title, platform)
        preview_item.clicked.connect(self._on_preview_clicked)
        preview_item.selection_changed.connect(self._on_preview_selection_changed)

        row = len(self.preview_items) // 5  # 5 per row to accommodate wider widgets
        col = len(self.preview_items) % 5
        self.preview_grid.addWidget(preview_item, row, col)
        self.preview_items.append(preview_item)

        # Also add to popout window if open
        self._add_preview_to_popout(path, title, platform)

    def _clear_preview(self):
        """Clear preview grid."""
        for item in self.preview_items:
            self.preview_grid.removeWidget(item)
            item.deleteLater()
        self.preview_items.clear()
        self._update_selection_count()

    def _on_preview_selection_changed(self, preview_widget: ClickableIconPreview, is_selected: bool):
        """Handle selection change on a preview widget."""
        self._update_selection_count()

    def _update_selection_count(self):
        """Update the selection count label."""
        count = sum(1 for item in self.preview_items if isinstance(item, ClickableIconPreview) and item.is_selected())
        total = len(self.preview_items)
        self.preview_selection_label.setText(f"{count}/{total} selected")

    def _select_all_previews(self):
        """Select all preview icons."""
        for item in self.preview_items:
            if isinstance(item, ClickableIconPreview):
                item.set_selected(True)
        # Also select in popout if open
        if hasattr(self, '_popout_preview_items'):
            for item in self._popout_preview_items:
                if isinstance(item, ClickableIconPreview):
                    item.set_selected(True)

    def _select_none_previews(self):
        """Deselect all preview icons."""
        for item in self.preview_items:
            if isinstance(item, ClickableIconPreview):
                item.set_selected(False)
        # Also deselect in popout if open
        if hasattr(self, '_popout_preview_items'):
            for item in self._popout_preview_items:
                if isinstance(item, ClickableIconPreview):
                    item.set_selected(False)

    def _rescrape_selected(self):
        """Re-scrape all selected preview icons."""
        if self._rescrape_in_progress:
            QMessageBox.warning(self, "Re-scrape in Progress", "A re-scrape is already in progress. Please wait.")
            return

        # Collect selected items
        selected_items = [item for item in self.preview_items
                         if isinstance(item, ClickableIconPreview) and item.is_selected() and item.platform]

        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select at least one icon to re-scrape.")
            return

        reply = QMessageBox.question(
            self,
            "Re-scrape Selected",
            f"Re-scrape {len(selected_items)} selected icon(s)?\n\n"
            "You will be prompted to select artwork for each one.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        self._rescrape_in_progress = True
        self._rescrape_cancelled = False
        self.btn_rescrape_selected.setEnabled(False)
        self.btn_rescrape_selected.setText("Re-scraping...")
        self._on_log(f"[RE-SCRAPE] Starting batch re-scrape for {len(selected_items)} icons")

        def do_batch_rescrape():
            try:
                cfg_path = Path(self.config_path)
                if not cfg_path.exists():
                    self._on_log("[RE-SCRAPE] Config file not found")
                    return

                for i, preview_widget in enumerate(selected_items):
                    if self._rescrape_cancelled:
                        self._on_log(f"[RE-SCRAPE] Batch cancelled by user")
                        break

                    game_title = preview_widget.game_title
                    platform = preview_widget.platform

                    self._on_log(f"[RE-SCRAPE] ({i+1}/{len(selected_items)}) Processing: {game_title}")

                    cancel_token = run_backend.CancelToken()

                    # Use the same run_job function with interactive_mode=True
                    ok, msg = run_backend.run_job(
                        config_path=cfg_path,
                        platforms=[platform],
                        workers=1,
                        limit=1,
                        cancel=cancel_token,
                        callbacks={
                            "log": lambda m: self._on_log(str(m)),
                            "preview": lambda p, t="", pl="", pw=preview_widget: self._on_rescrape_preview_update(pw, p),
                            "request_selection": self._request_artwork_selection_batch,
                        },
                        search_term=game_title,
                        interactive_mode=True,  # Force interactive mode
                        download_heroes=False,
                        hero_count=0,
                        fallback_settings={"enabled": False},
                        download_screenshots=False,
                        screenshot_count=0,
                        copy_to_device=False,
                        device_path="",
                        scrape_logos=False,
                        logo_fallback_to_boxart=False,
                        force_rescrape=True,  # Override existing icons
                        output_path_override=preview_widget.icon_path
                    )

                    if ok:
                        self._on_log(f"[RE-SCRAPE] Completed: {game_title}")
                        # Deselect after successful processing - store widget reference for main thread
                        self._widget_to_deselect = preview_widget
                        from PySide6.QtCore import QMetaObject, Qt
                        QMetaObject.invokeMethod(
                            self,
                            "_deselect_preview_widget",
                            Qt.ConnectionType.QueuedConnection
                        )
                    else:
                        self._on_log(f"[RE-SCRAPE] Skipped or failed: {game_title}")

                self._on_log(f"[RE-SCRAPE] Batch complete")

            except Exception as e:
                import traceback
                self._on_log(f"[RE-SCRAPE] Error: {e}")
                self._on_log(f"[RE-SCRAPE] {traceback.format_exc()}")
            finally:
                # Reset UI on main thread
                from PySide6.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(
                    self,
                    "_on_batch_rescrape_finished",
                    Qt.ConnectionType.QueuedConnection
                )

        thread = threading.Thread(target=do_batch_rescrape, daemon=True)
        thread.start()

    def _request_artwork_selection_batch(self, title: str, platform: str, artwork_options):
        """
        Request user to select artwork during batch re-scrape.
        Returns selected index, None if skipped, -1 if cancelled all.
        """
        result = self._request_artwork_selection(title, platform, artwork_options)
        if result == -1:
            # User cancelled all - stop batch
            self._rescrape_cancelled = True
        return result

    @Slot()
    def _on_batch_rescrape_finished(self):
        """Called when batch re-scrape is finished."""
        self._rescrape_in_progress = False
        self.btn_rescrape_selected.setEnabled(True)
        self.btn_rescrape_selected.setText("Re-scrape Selected")
        self._update_selection_count()

    @Slot()
    def _deselect_preview_widget(self):
        """Deselect the preview widget stored in _widget_to_deselect (called from main thread)."""
        if hasattr(self, '_widget_to_deselect') and self._widget_to_deselect:
            self._widget_to_deselect.set_selected(False)
            # Also sync with popout if open
            if hasattr(self, '_popout_preview_items'):
                for popout_item in self._popout_preview_items:
                    if isinstance(popout_item, ClickableIconPreview) and popout_item.icon_path == self._widget_to_deselect.icon_path:
                        popout_item.set_selected(False)
                        break
            self._widget_to_deselect = None
            self._update_selection_count()
            if hasattr(self, '_popout_selection_label'):
                self._update_popout_selection_count()

    def _on_preview_clicked(self, preview_widget: ClickableIconPreview):
        """Handle click on a preview icon to re-scrape with artwork selection."""
        game_title = preview_widget.game_title
        platform = preview_widget.platform
        icon_path = preview_widget.icon_path

        if not platform:
            QMessageBox.warning(
                self,
                "Cannot Re-scrape",
                "Platform information is not available for this icon.\n"
                "This may happen with icons generated in a previous session."
            )
            return

        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Re-scrape Artwork",
            f"Do you want to re-scrape artwork for:\n\n"
            f"Game: {game_title}\n"
            f"Platform: {platform}\n\n"
            "This will fetch all available artwork and let you choose.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        # Run re-scrape using the same pipeline as normal scraping
        self._on_log(f"[RE-SCRAPE] Starting re-scrape for {game_title} ({platform})")

        def do_rescrape():
            try:
                cfg_path = Path(self.config_path)
                if not cfg_path.exists():
                    self._on_log("[RE-SCRAPE] Config file not found")
                    return

                cancel_token = run_backend.CancelToken()

                # Use the same run_job function with interactive_mode=True
                # This will use the exact same artwork fetching logic as normal scraping
                ok, msg = run_backend.run_job(
                    config_path=cfg_path,
                    platforms=[platform],
                    workers=1,
                    limit=1,
                    cancel=cancel_token,
                    callbacks={
                        "log": lambda m: self._on_log(str(m)),
                        "preview": lambda p, t="", pl="": self._on_rescrape_preview_update(preview_widget, p),
                        "request_selection": self._request_artwork_selection,
                    },
                    search_term=game_title,
                    interactive_mode=True,  # Force interactive mode for re-scrape
                    download_heroes=False,  # Don't re-download heroes
                    hero_count=0,
                    fallback_settings={"enabled": False},  # No fallback for re-scrape
                    download_screenshots=False,
                    screenshot_count=0,
                    copy_to_device=False,
                    device_path="",
                    scrape_logos=False,
                    logo_fallback_to_boxart=False,
                    force_rescrape=True,  # Override existing icons
                    output_path_override=preview_widget.icon_path
                )

                if ok:
                    self._on_log(f"[RE-SCRAPE] Completed for {game_title}")
                else:
                    self._on_log(f"[RE-SCRAPE] Failed for {game_title}: {msg}")

            except Exception as e:
                import traceback
                self._on_log(f"[RE-SCRAPE] Error: {e}")
                self._on_log(f"[RE-SCRAPE] {traceback.format_exc()}")

        # Start in background thread
        thread = threading.Thread(target=do_rescrape, daemon=True)
        thread.start()

    def _on_rescrape_preview_update(self, preview_widget: ClickableIconPreview, new_path: str):
        """Update preview widget after re-scrape generates new icon."""
        # Store reference for main thread update
        self._widget_to_refresh = preview_widget
        self._refresh_path = new_path
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self,
            "_refresh_preview_widget",
            Qt.ConnectionType.QueuedConnection
        )

    @Slot()
    def _refresh_preview_widget(self):
        """Refresh preview widget and sync with popout (called from main thread)."""
        if hasattr(self, '_widget_to_refresh') and self._widget_to_refresh:
            preview_widget = self._widget_to_refresh
            # Refresh the main preview widget
            preview_widget.refresh_icon()

            # Also refresh corresponding popout widget if open
            if hasattr(self, '_popout_preview_items') and self._popout_preview_items:
                for popout_item in self._popout_preview_items:
                    if isinstance(popout_item, ClickableIconPreview) and popout_item.icon_path == preview_widget.icon_path:
                        popout_item.refresh_icon()
                        break

            # Also refresh main preview if update came from popout
            for main_item in self.preview_items:
                if isinstance(main_item, ClickableIconPreview) and main_item.icon_path == preview_widget.icon_path and main_item != preview_widget:
                    main_item.refresh_icon()
                    break

            self._widget_to_refresh = None

    @Slot()
    def _show_rescrape_no_results(self):
        """Show message when no artwork found for re-scrape."""
        QMessageBox.information(
            self,
            "No Artwork Found",
            "No artwork was found for this game from any source.\n"
            "Try checking your API keys in Settings."
        )

    def _open_output(self):
        """Open output directory."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

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
        instructions.setStyleSheet("color: #888; font-size: 11px;")
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

        # Help info
        help_info = QLabel(
            "<span style='color: #888; font-size: 10px;'>"
            "This scans the iiSU Launcher assets folder for games that need artwork.<br>"
            "Each game folder should contain icon.png, hero.png, etc."
            "</span>"
        )
        help_info.setWordWrap(True)
        layout.addWidget(help_info)

        # Speed info
        speed_info = QLabel(
            "<span style='color: #00D4FF; font-size: 11px;'>"
            "Scans game folders directly from iiSU Launcher assets - same as Android app!"
            "</span>"
        )
        layout.addWidget(speed_info)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Scan Assets")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            device_id = device_combo.currentData()
            assets_path = path_input.text().strip() or iisu_default_path

            # Update UI
            self.status_label.setText(f"Scanning iiSU assets via ADB: {device_id}...")
            self.btn_adb_scan.setEnabled(False)
            self.btn_refresh.setEnabled(False)

            # Force UI update
            from PySide6.QtWidgets import QApplication
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
            # List platform folders
            result = subprocess.run(
                [adb_path, "-s", device_id, "shell", f'ls -1 "{assets_path}"'],
                capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace',
                **_get_subprocess_flags()
            )

            if result.returncode != 0:
                print(f"[DEBUG] Failed to list assets path: {result.stderr}")
                return {}

            platforms = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            print(f"[DEBUG] Found platforms: {platforms}")

            # Map lowercase folder names to standard platform keys
            from rom_parser import FOLDER_TO_PLATFORM

            for platform_folder in platforms:
                platform_path = f"{assets_path}/{platform_folder}"

                # Try to detect platform from folder name
                platform_key = FOLDER_TO_PLATFORM.get(platform_folder.lower())
                if not platform_key:
                    # Use folder name as-is if not in mapping
                    platform_key = platform_folder.upper()

                # List game folders in platform using ls -la to identify directories
                try:
                    result = subprocess.run(
                        [adb_path, "-s", device_id, "shell", f'ls -la "{platform_path}"'],
                        capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace',
                        **_get_subprocess_flags()
                    )

                    if result.returncode != 0:
                        continue

                    games = []
                    for line in result.stdout.strip().split('\n'):
                        if not line:
                            continue
                        line = line.strip()
                        if not line or line.startswith('total'):
                            continue
                        # Directory lines start with 'd'
                        if line.startswith('d'):
                            parts = line.split()
                            if len(parts) >= 8:
                                # Name is everything after the 7th column (handles spaces)
                                name = ' '.join(parts[7:])
                                if name and name not in ('.', '..'):
                                    game_path = f"{platform_path}/{name}"

                                    # Check what files exist in the game folder
                                    files_result = subprocess.run(
                                        [adb_path, "-s", device_id, "shell", f'ls -1 "{game_path}"'],
                                        capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace',
                                        **_get_subprocess_flags()
                                    )

                                    files = []
                                    if files_result.returncode == 0 and files_result.stdout:
                                        files = [f.strip() for f in files_result.stdout.strip().split('\n') if f and f.strip()]

                                    # Store as tuple for compatibility with existing code
                                    games.append((name, game_path))

                                    # Store extended info separately
                                    self._iisu_game_info[game_path] = {
                                        "has_icon": "icon.png" in files,
                                        "has_hero": "hero.png" in files,
                                        "files": files
                                    }

                    if games:
                        results[platform_key] = games
                        print(f"[DEBUG] {platform_key}: {len(games)} games")

                except subprocess.TimeoutExpired:
                    print(f"[DEBUG] Timeout scanning {platform_folder}")
                    continue
                except Exception as e:
                    print(f"[DEBUG] Error scanning {platform_folder}: {e}")
                    continue

        except Exception as e:
            print(f"[DEBUG] ADB scan error: {e}")

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
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info_label)

        # Log text area
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1d21;
                color: #E9E9E9;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
                border: 1px solid #3a3d42;
                border-radius: 4px;
            }
        """)

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
            self.btn_hide_preview.setText("Show")
            self._preview_visible = False
        else:
            self.preview_scroll_area.show()
            self.btn_hide_preview.setText("Hide")
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
        self._preview_popout_window.setMinimumSize(700, 500)
        self._preview_popout_window.setAttribute(Qt.WA_DeleteOnClose)
        self._preview_popout_window.finished.connect(self._on_popout_closed)

        popout_layout = QVBoxLayout(self._preview_popout_window)
        popout_layout.setContentsMargins(10, 10, 10, 10)

        # Selection controls row
        controls_row = QHBoxLayout()
        controls_row.setSpacing(6)

        popout_select_all = QPushButton("All")
        popout_select_all.setToolTip("Select all icons")
        popout_select_all.clicked.connect(self._select_all_previews)
        controls_row.addWidget(popout_select_all)

        popout_select_none = QPushButton("None")
        popout_select_none.setToolTip("Deselect all icons")
        popout_select_none.clicked.connect(self._select_none_previews)
        controls_row.addWidget(popout_select_none)

        popout_rescrape = QPushButton("Re-scrape Selected")
        popout_rescrape.setToolTip("Re-scrape selected icons with artwork selection")
        popout_rescrape.clicked.connect(self._rescrape_selected)
        controls_row.addWidget(popout_rescrape)

        controls_row.addStretch()

        # Selection count label for popout
        self._popout_selection_label = QLabel("0 selected")
        self._popout_selection_label.setStyleSheet("font-size: 10px; color: #888;")
        controls_row.addWidget(self._popout_selection_label)

        popout_layout.addLayout(controls_row)

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
        for i, preview_widget in enumerate(self.preview_items):
            if isinstance(preview_widget, ClickableIconPreview):
                # Create a new clickable preview for the popout
                popout_preview = ClickableIconPreview(
                    preview_widget.icon_path,
                    preview_widget.game_title,
                    preview_widget.platform
                )
                popout_preview.clicked.connect(self._on_preview_clicked)
                popout_preview.selection_changed.connect(self._on_popout_selection_changed)

                # Copy selection state
                popout_preview.set_selected(preview_widget.is_selected())

                row = i // 4  # 4 per row in popout
                col = i % 4
                self._popout_preview_grid.addWidget(popout_preview, row, col)
                self._popout_preview_items.append(popout_preview)

        # Update popout selection count
        self._update_popout_selection_count()

    def _on_popout_selection_changed(self, preview_widget: ClickableIconPreview, is_selected: bool):
        """Handle selection change in popout - sync to main preview."""
        # Find corresponding item in main preview and sync
        for item in self.preview_items:
            if isinstance(item, ClickableIconPreview) and item.icon_path == preview_widget.icon_path:
                item.set_selected(is_selected)
                break
        self._update_popout_selection_count()
        self._update_selection_count()

    def _update_popout_selection_count(self):
        """Update the selection count label in popout."""
        if hasattr(self, '_popout_selection_label') and hasattr(self, '_popout_preview_items'):
            count = sum(1 for item in self._popout_preview_items if isinstance(item, ClickableIconPreview) and item.is_selected())
            total = len(self._popout_preview_items)
            self._popout_selection_label.setText(f"{count}/{total} selected")

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

    def _add_preview_to_popout(self, path: str, title: str = "", platform: str = ""):
        """Add a preview to the popout window if it's open."""
        if not self._preview_popout_window or not hasattr(self, '_popout_preview_grid'):
            return

        path_obj = Path(path)
        if not path_obj.exists():
            return

        # Use filename as title fallback
        if not title:
            title = path_obj.stem

        # Create clickable preview widget
        preview_item = ClickableIconPreview(path, title, platform)
        preview_item.clicked.connect(self._on_preview_clicked)
        preview_item.selection_changed.connect(self._on_popout_selection_changed)

        row = len(self._popout_preview_items) // 4
        col = len(self._popout_preview_items) % 4
        self._popout_preview_grid.addWidget(preview_item, row, col)
        self._popout_preview_items.append(preview_item)

        # Update popout selection count
        self._update_popout_selection_count()
