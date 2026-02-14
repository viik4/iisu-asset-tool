"""
Icon Generator Tab - extracted from original ui_app.py
This is the main icon generation interface moved into a tab widget.
"""
import sys
import threading
from pathlib import Path
from io import BytesIO

import yaml
from PIL import Image
from PySide6.QtCore import Qt, Signal, QObject, QSize, QUrl, Slot
from PySide6.QtGui import QIcon, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QSpinBox, QLineEdit, QProgressBar, QTextEdit, QFileDialog,
    QMessageBox, QComboBox, QCheckBox, QTabWidget, QButtonGroup, QRadioButton,
    QSplitter, QScrollArea, QGridLayout, QFrame
)

import run_backend
from preview_window import show_preview_dialog
from source_priority_widget import SourcePriorityWidget
from options_dialog import OptionsDialog
from app_paths import get_borders_dir, get_config_path, get_config, invalidate_config_cache


class BackendCallbacks(QObject):
    # Backend emits progress as (done, total) and log lines as strings
    progress = Signal(int, int)
    log = Signal(str)
    finished = Signal(bool, str)
    preview = Signal(str)  # Emits path to generated icon
    request_selection = Signal(str, str, list)  # title, platform, artwork_options


class IconGeneratorTab(QWidget):
    """Main icon generator tab widget."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._cancel_token = None
        self._worker_thread = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        layout = QHBoxLayout()
        root.addLayout(layout, 1)

        # ---------- Left column ----------
        left = QVBoxLayout()
        left.setSpacing(12)
        layout.addLayout(left, 3)

        # Store settings (not visible in UI)
        self.config_path = str(get_config_path())
        self.workers_value = 8
        self.limit_value = 0
        self.source_priority = SourcePriorityWidget()  # Hidden, managed by options dialog
        self.fallback_settings = {}  # Fallback icon settings, managed by options dialog
        self.custom_border_settings = {}  # Custom border settings, managed by options dialog
        self.steamgriddb_settings = {"square_only": True}  # SteamGridDB settings, managed by options dialog
        self.interactive_settings = {"icons": True, "heroes": False, "logos": False, "screenshots": False}  # Per-artwork interactive mode

        # ===== SEARCH CARD (Simplified - single search bar) =====
        search_card = QFrame()
        search_card.setObjectName("card")
        search_card_layout = QVBoxLayout(search_card)
        search_card_layout.setContentsMargins(12, 10, 12, 10)
        search_card_layout.setSpacing(10)

        # Unified search row with integrated controls
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search games on SteamGridDB...")
        self.search_input.setMinimumHeight(40)
        self.search_input.returnPressed.connect(self._perform_search)
        search_row.addWidget(self.search_input, 1)

        # Hidden mode selector (kept for compatibility, but always "Search by Name")
        self.search_mode = QComboBox()
        self.search_mode.addItems(["Search by Name", "Process All Games", "Filter by Letter"])
        self.search_mode.setVisible(False)  # Hidden - mode selection moved to processing dialog

        # Hidden letter filter (kept for compatibility)
        self.letter_filter = QComboBox()
        self.letter_filter.addItems(["All"] + [chr(i) for i in range(ord('A'), ord('Z')+1)] + ["0-9", "#"])
        self.letter_filter.setVisible(False)

        self.btn_search = QPushButton("Search")
        self.btn_search.setObjectName("btn_primary")
        self.btn_search.setMinimumHeight(40)
        self.btn_search.setMinimumWidth(90)
        self.btn_search.setToolTip("Search SteamGridDB for games")
        self.btn_search.clicked.connect(self._perform_search)
        search_row.addWidget(self.btn_search)

        # Settings button
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setMinimumHeight(40)
        self.btn_settings.setMinimumWidth(70)
        self.btn_settings.setToolTip("API keys, sources, output format")
        self.btn_settings.clicked.connect(self.open_options)
        self.btn_settings.setObjectName("btn_secondary")
        search_row.addWidget(self.btn_settings)

        search_card_layout.addLayout(search_row)

        # Quick options in a compact row below search
        options_row = QHBoxLayout()
        options_row.setSpacing(16)

        # Region preference (compact)
        region_label = QLabel("Region:")
        region_label.setObjectName("label_muted")
        options_row.addWidget(region_label)
        self.region_combo = QComboBox()
        self.region_combo.setToolTip("Prefer artwork from a specific region")
        self.region_combo.addItem("Any", "any")
        self.region_combo.addItem("USA", "USA")
        self.region_combo.addItem("Europe", "EUR")
        self.region_combo.addItem("Japan", "JPN")
        self.region_combo.setMinimumWidth(70)
        self.region_combo.setMinimumHeight(28)
        options_row.addWidget(self.region_combo)

        options_row.addSpacing(8)

        # Interactive mode toggle
        self.interactive_mode = QCheckBox("Interactive Mode")
        self.interactive_mode.setToolTip("Choose artwork manually for each game")
        self.interactive_mode.setChecked(True)
        self.interactive_mode.stateChanged.connect(self._on_interactive_mode_changed)
        self.interactive_mode.setObjectName("label_muted")
        options_row.addWidget(self.interactive_mode)

        options_row.addStretch()

        # Hidden settings (managed by Options dialog)
        self.download_heroes = QCheckBox()
        self.download_heroes.setChecked(True)
        self.download_heroes.setVisible(False)

        self.square_only_toggle = QCheckBox()
        self.square_only_toggle.setChecked(True)
        self.square_only_toggle.setVisible(False)
        self.square_only_toggle.stateChanged.connect(self._on_square_only_changed)

        search_card_layout.addLayout(options_row)

        left.addWidget(search_card)

        # ===== ACTION BAR (Simplified) =====
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        # Primary action button
        self.btn_start = QPushButton("Generate Icons")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setMinimumHeight(42)
        self.btn_start.setMinimumWidth(150)
        self.btn_start.clicked.connect(self.start_job)
        action_row.addWidget(self.btn_start)

        # Cancel button
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumHeight(42)
        self.btn_cancel.setMinimumWidth(70)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("Cancel processing")
        self.btn_cancel.clicked.connect(self.cancel_job)
        self.btn_cancel.setObjectName("btn_secondary")
        action_row.addWidget(self.btn_cancel)

        # Progress bar (takes remaining space)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(42)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Ready")
        action_row.addWidget(self.progress, 1)

        # Output folder button
        self.btn_open_out = QPushButton("Output")
        self.btn_open_out.setMinimumHeight(42)
        self.btn_open_out.setMinimumWidth(65)
        self.btn_open_out.setToolTip("Open output folder")
        self.btn_open_out.clicked.connect(self.open_output_dir)
        self.btn_open_out.setObjectName("btn_secondary")
        action_row.addWidget(self.btn_open_out)

        # Logs button
        self.btn_show_logs = QPushButton("Logs")
        self.btn_show_logs.setMinimumHeight(42)
        self.btn_show_logs.setMinimumWidth(55)
        self.btn_show_logs.setToolTip("View processing logs")
        self.btn_show_logs.clicked.connect(self._show_logs_dialog)
        self.btn_show_logs.setObjectName("btn_secondary")
        action_row.addWidget(self.btn_show_logs)

        left.addLayout(action_row)

        # Hidden log storage (for logs dialog)
        self.log_content = ""

        # ===== MAIN CONTENT SPLITTER =====
        splitter = QSplitter(Qt.Vertical)

        # Search Results Card
        search_results_card = QFrame()
        search_results_card.setObjectName("results_card")
        search_results_layout = QVBoxLayout(search_results_card)
        search_results_layout.setContentsMargins(10, 10, 10, 10)
        search_results_layout.setSpacing(6)

        results_header_row = QHBoxLayout()
        search_header = QLabel("Results")
        search_header.setObjectName("label_header")
        results_header_row.addWidget(search_header)
        results_header_row.addStretch()
        self.search_status = QLabel("Enter a game name and click Search")
        self.search_status.setObjectName("label_muted")
        results_header_row.addWidget(self.search_status)
        search_results_layout.addLayout(results_header_row)

        self.search_results_list = QListWidget()
        self.search_results_list.setObjectName("search_results_list")
        self.search_results_list.setSelectionMode(QListWidget.SingleSelection)
        self.search_results_list.setAlternatingRowColors(False)
        self.search_results_list.setMinimumHeight(120)
        search_results_layout.addWidget(self.search_results_list, 1)

        splitter.addWidget(search_results_card)

        # Live Preview Card
        preview_card = QFrame()
        preview_card.setObjectName("preview_card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(6)

        preview_header = QLabel("Generated Icons")
        preview_header.setObjectName("label_header")
        preview_layout.addWidget(preview_header)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        self.preview_grid_widget = QWidget()
        self.preview_grid_layout = QGridLayout(self.preview_grid_widget)
        self.preview_grid_layout.setSpacing(6)
        self.preview_grid_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self.preview_grid_widget)
        preview_layout.addWidget(scroll_area, 1)

        splitter.addWidget(preview_card)

        splitter.setSizes([300, 250])
        left.addWidget(splitter, 1)

        self.preview_items = []
        self.max_preview_items = 50

        # ===== RIGHT COLUMN - PLATFORMS (Simplified with filter chips) =====
        right = QVBoxLayout()
        right.setSpacing(8)
        layout.addLayout(right, 2)

        # Platform card
        platform_card = QFrame()
        platform_card.setObjectName("platform_card")
        platform_layout = QVBoxLayout(platform_card)
        platform_layout.setContentsMargins(12, 12, 12, 12)
        platform_layout.setSpacing(8)

        # Platform header row
        platform_header_row = QHBoxLayout()
        platform_title = QLabel("Platforms")
        platform_title.setObjectName("label_header")
        platform_header_row.addWidget(platform_title)

        # Selection counter badge
        self.platform_counter = QLabel("0 selected")
        self.platform_counter.setObjectName("badge")
        platform_header_row.addWidget(self.platform_counter)

        platform_header_row.addStretch()

        # Quick actions
        btn_all = QPushButton("All")
        btn_all.setObjectName("btn_select")
        btn_all.setMinimumHeight(26)
        btn_all.setMinimumWidth(50)
        btn_all.setToolTip("Select all visible platforms")
        btn_all.clicked.connect(self.select_all)
        platform_header_row.addWidget(btn_all)

        btn_none = QPushButton("None")
        btn_none.setObjectName("btn_small")
        btn_none.setMinimumHeight(26)
        btn_none.setMinimumWidth(50)
        btn_none.setToolTip("Clear selection")
        btn_none.clicked.connect(self.select_none)
        platform_header_row.addWidget(btn_none)

        platform_layout.addLayout(platform_header_row)

        # Filter chips row (replaces tabs for cleaner look)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        self.publisher_filter_buttons = {}
        self.current_publisher_filter = "All"

        for publisher in ["All", "Nintendo", "Sony", "Microsoft", "Sega", "Other"]:
            btn = QPushButton(publisher)
            btn.setObjectName("filter_chip")
            btn.setMinimumHeight(24)
            btn.setCheckable(True)
            btn.setChecked(publisher == "All")
            btn.clicked.connect(lambda checked, p=publisher: self._on_publisher_filter_clicked(p))
            filter_row.addWidget(btn)
            self.publisher_filter_buttons[publisher] = btn

        filter_row.addStretch()

        # Sort dropdown (compact)
        sort_label = QLabel("Sort:")
        sort_label.setObjectName("label_muted")
        filter_row.addWidget(sort_label)
        self.sort_mode = QComboBox()
        self.sort_mode.addItems(["Name", "Year", "Type"])
        self.sort_mode.setMinimumWidth(65)
        self.sort_mode.setMinimumHeight(24)
        self.sort_mode.currentIndexChanged.connect(self._on_sort_changed)
        filter_row.addWidget(self.sort_mode)

        filter_row.addSpacing(8)

        # Icon size control
        size_label = QLabel("Size:")
        size_label.setObjectName("label_muted")
        filter_row.addWidget(size_label)
        self.icon_size_combo = QComboBox()
        self.icon_size_combo.addItems(["S", "M", "L", "XL"])
        self.icon_size_combo.setCurrentIndex(1)  # Default to Medium (72px)
        self.icon_size_combo.setMinimumWidth(50)
        self.icon_size_combo.setMinimumHeight(24)
        self.icon_size_combo.setToolTip("Platform icon display size")
        self.icon_size_combo.currentIndexChanged.connect(self._on_icon_size_changed)
        filter_row.addWidget(self.icon_size_combo)

        platform_layout.addLayout(filter_row)

        # Single unified platform list (replaces tabbed view)
        self.main_platform_list = QListWidget()
        self.main_platform_list.setObjectName("platform_list")
        self.main_platform_list.setSelectionMode(QListWidget.MultiSelection)
        self.main_platform_list.setViewMode(QListWidget.IconMode)
        self.main_platform_list.setResizeMode(QListWidget.Adjust)
        self.main_platform_list.setMovement(QListWidget.Static)
        self.main_platform_list.setWrapping(True)
        self.main_platform_list.setWordWrap(True)
        self.main_platform_list.setIconSize(QSize(72, 72))
        self.main_platform_list.setSpacing(6)
        self.main_platform_list.itemSelectionChanged.connect(self._on_platform_selection_changed)

        platform_layout.addWidget(self.main_platform_list, 1)

        # Keep old data structures for compatibility (hidden)
        self.publisher_tabs = None  # No longer used
        self.platform_lists = {"All": QListWidget()}  # Internal tracking only
        for publisher in ["Nintendo", "Sony", "Microsoft", "Sega", "Other"]:
            self.platform_lists[publisher] = QListWidget()

        right.addWidget(platform_card, 1)

        # Defer platform loading to next event-loop tick so the tab
        # constructor returns immediately and the UI stays responsive.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.load_platforms_from_config)

    # ---------- Interactive mode ----------
    def _request_game_selection(self, title: str, platform: str):
        """
        Request user to search and select a game from SteamGridDB.
        Called from worker thread, so must use thread-safe Qt mechanisms.
        Returns selected game ID, None if skipped/cancelled, -1 if cancelled all.
        """
        from game_search_dialog import GameSearchDialog
        from queue import Queue
        from PySide6.QtCore import QCoreApplication

        self.append_log(f"[INTERACTIVE] Requesting game selection for '{title}'")

        # Store data in instance variables so main thread can access them
        self._game_search_title = title
        self._game_search_platform = platform
        self._game_search_result = Queue()

        # Use QMetaObject.invokeMethod to run on main thread
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self,
            "_show_game_search_dialog_on_main_thread",
            Qt.ConnectionType.BlockingQueuedConnection
        )

        # Get result from queue
        result = self._game_search_result.get()
        self.append_log(f"[INTERACTIVE] Game selection result: {result}")
        return result

    @Slot()
    def _show_game_search_dialog_on_main_thread(self):
        """Show game search dialog on main thread - called via invokeMethod."""
        from game_search_dialog import GameSearchDialog
        try:
            self.append_log(f"[INTERACTIVE] Showing game search dialog for '{self._game_search_title}'")

            selected_game = GameSearchDialog.search_and_select(
                parent=self,
                initial_query=self._game_search_title,
                title=f"Search Game: {self._game_search_title}"
            )

            if selected_game:
                game_id = selected_game.get("id")
                game_name = selected_game.get("name", "Unknown")
                self.append_log(f"[INTERACTIVE] User selected: {game_name} (ID: {game_id})")
                self._game_search_result.put(game_id)
            else:
                # User cancelled
                self.append_log(f"[INTERACTIVE] User cancelled game selection")
                self._game_search_result.put(None)

        except Exception as e:
            self.append_log(f"[INTERACTIVE] Game search dialog error: {e}")
            import traceback
            self.append_log(f"[INTERACTIVE] {traceback.format_exc()}")
            self._game_search_result.put(None)

    def _request_artwork_selection(self, title: str, platform: str, artwork_options, asset_type: str = "icon"):
        """
        Request user to select artwork from options.
        Called from worker thread, so must use thread-safe Qt mechanisms.
        Returns selected index, None if skipped, -1 if cancelled all.

        Args:
            title: Game title
            platform: Platform key
            artwork_options: List of artwork option dicts
            asset_type: Type of asset ('icon', 'hero', 'logo', 'screenshot')
        """
        from artwork_picker_dialog import ArtworkPickerDialog
        from queue import Queue
        from PySide6.QtCore import QCoreApplication
        import threading

        type_label = asset_type.upper() if asset_type else "ICON"
        self.append_log(f"[INTERACTIVE-{type_label}] Request for {title} with {len(artwork_options)} options")
        self.append_log(f"[INTERACTIVE-{type_label}] Current thread: {threading.current_thread().name}")

        # Store data in instance variables so main thread can access them
        self._dialog_title = title
        self._dialog_platform = platform
        self._dialog_options = artwork_options
        self._dialog_asset_type = asset_type
        self._dialog_result = Queue()

        # Use QMetaObject.invokeMethod to run on main thread
        from PySide6.QtCore import QMetaObject, Qt
        self.append_log(f"[INTERACTIVE-{type_label}] About to invoke dialog on main thread...")

        success = QMetaObject.invokeMethod(
            self,
            "_show_selection_dialog_on_main_thread",
            Qt.ConnectionType.BlockingQueuedConnection
        )

        self.append_log(f"[INTERACTIVE-{type_label}] invokeMethod returned: {success}")

        # Get result from queue
        result = self._dialog_result.get()
        self.append_log(f"[INTERACTIVE] Got result: {result}")
        return result

    @Slot()
    def _show_selection_dialog_on_main_thread(self):
        """Show dialog on main thread - called via invokeMethod."""
        import threading
        asset_type = getattr(self, '_dialog_asset_type', 'icon')
        type_label = asset_type.upper() if asset_type else "ICON"
        self.append_log(f"[INTERACTIVE-{type_label}] _show_selection_dialog_on_main_thread ENTERED, thread: {threading.current_thread().name}")
        from artwork_picker_dialog import ArtworkPickerDialog
        try:
            self.append_log(f"[INTERACTIVE-{type_label}] Showing dialog for {self._dialog_title} with {len(self._dialog_options)} options")

            # Determine if we should show the square filter (only for icons)
            show_filter = (asset_type == "icon")

            dialog = ArtworkPickerDialog(
                title=self._dialog_title,
                platform=self._dialog_platform,
                artwork_options=self._dialog_options,
                parent=self,
                asset_type=asset_type,
                show_filter=show_filter,
                on_filter_changed=self._handle_filter_change if show_filter else None
            )

            # Show dialog modally
            dialog_result = dialog.exec()
            selected = dialog.get_selected_index()

            self.append_log(f"[INTERACTIVE-{type_label}] Dialog result: exec={dialog_result}, selected={selected}")
            self._dialog_result.put(selected)

        except Exception as e:
            import traceback
            self.append_log(f"[ERROR] Dialog exception: {e}")
            self.append_log(f"[ERROR] Traceback: {traceback.format_exc()}")
            self._dialog_result.put(None)

    def _handle_filter_change(self, square_only: bool):
        """Handle filter change in artwork picker dialog.

        Note: Due to the backend architecture, changing the filter during dialog
        display requires re-fetching results. This stores the preference for
        future searches and updates the current dialog if possible.
        """
        self._square_only_filter = square_only
        self.append_log(f"[FILTER] Square only filter changed to: {square_only}")

        # Get current dialog and re-search if possible
        # This is a simplified implementation - full implementation would
        # require deeper integration with the backend search flow

    # ---------- UI helpers ----------
    def _find_file_case_insensitive(self, directory: Path, filename: str) -> Path:
        """Find a file in directory with case-insensitive matching."""
        if not directory.exists():
            return None

        # Try exact match first
        exact_path = directory / filename
        if exact_path.exists():
            return exact_path

        # Try case-insensitive match
        filename_lower = filename.lower()
        for file in directory.iterdir():
            if file.name.lower() == filename_lower:
                return file

        return None

    def append_log(self, msg: str):
        """Append log message to internal storage."""
        self.log_content += msg + "\n"

    def add_preview_icon(self, icon_path: str):
        """Add a generated icon to the live preview grid."""
        from pathlib import Path

        path = Path(icon_path)
        if not path.exists():
            return

        # Create preview item
        preview_item = QLabel()
        preview_item.setFixedSize(128, 128)
        preview_item.setScaledContents(True)
        preview_item.setFrameShape(QFrame.Box)
        preview_item.setLineWidth(2)
        preview_item.setObjectName("preview_border_frame")

        # Load and set pixmap
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            preview_item.setPixmap(pixmap)
            preview_item.setToolTip(path.stem)

            # Add to grid (5 columns)
            row = len(self.preview_items) // 5
            col = len(self.preview_items) % 5
            self.preview_grid_layout.addWidget(preview_item, row, col)

            self.preview_items.append(preview_item)

            # Limit preview items (remove oldest if exceeds max)
            if len(self.preview_items) > self.max_preview_items:
                old_item = self.preview_items.pop(0)
                self.preview_grid_layout.removeWidget(old_item)
                old_item.deleteLater()

                # Rebuild grid layout
                for i, item in enumerate(self.preview_items):
                    r = i // 5
                    c = i % 5
                    self.preview_grid_layout.addWidget(item, r, c)

    def clear_preview(self):
        """Clear all preview icons."""
        for item in self.preview_items:
            self.preview_grid_layout.removeWidget(item)
            item.deleteLater()
        self.preview_items.clear()

    def _on_search_mode_changed(self, index):
        """Show/hide search controls based on selected mode."""
        # Kept for compatibility but no longer used in UI
        pass

    def _on_publisher_filter_clicked(self, publisher):
        """Handle publisher filter chip click."""
        # Update button checked states - styling handled by QSS via :checked selector
        for p, btn in self.publisher_filter_buttons.items():
            btn.setChecked(p == publisher)

        self.current_publisher_filter = publisher
        self._refresh_platform_list_filter()

    def _on_sort_changed(self):
        """Re-sort platforms when sort order changes."""
        self.load_platforms_from_config()

    def _on_icon_size_changed(self, index: int):
        """Update platform icon display size."""
        # Size mapping: S=48, M=72, L=96, XL=128
        sizes = [48, 72, 96, 128]
        new_size = sizes[index] if index < len(sizes) else 72
        self.main_platform_list.setIconSize(QSize(new_size, new_size))
        # Adjust grid size to match icon size with padding
        self.main_platform_list.setGridSize(QSize(new_size + 24, new_size + 36))

    def _on_interactive_mode_changed(self, state):
        """Show warning when interactive mode is disabled."""
        if state == Qt.Unchecked:
            QMessageBox.warning(
                self,
                "Interactive Mode Disabled",
                "Warning: With Interactive Mode disabled, artwork will be automatically selected "
                "without prompting you for each game.\n\n"
                "The first matching result from your enabled sources will be used."
            )

    def _on_square_only_changed(self, state):
        """Update steamgriddb_settings when square_only toggle changes."""
        self.steamgriddb_settings["square_only"] = (state == Qt.Checked)

        # Save the setting to config
        self._save_steamgriddb_setting_to_config()

        if state == Qt.Unchecked:
            # Show info about cropping when disabled
            QMessageBox.information(
                self,
                "All Dimensions Enabled",
                "SteamGridDB will now show artwork of all dimensions.\n\n"
                "In Interactive Mode, you can use the 'Crop' button on\n"
                "non-square artwork to crop it to a square format."
            )

    def _save_steamgriddb_setting_to_config(self):
        """Save steamgriddb_settings to config file."""
        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            if "art_sources" not in cfg:
                cfg["art_sources"] = {}

            cfg["art_sources"]["steamgriddb_square_only"] = self.steamgriddb_settings.get("square_only", True)

            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
            invalidate_config_cache()

            self.append_log(f"[CONFIG] SteamGridDB square_only set to {self.steamgriddb_settings.get('square_only', True)}")

        except Exception as e:
            self.append_log(f"[ERROR] Failed to save steamgriddb setting: {e}")

    # ---------- Config and platforms ----------
    def _show_logs_dialog(self):
        """Show logs in a popup dialog."""
        from PySide6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Processing Logs")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        log_view = QTextEdit()
        log_view.setReadOnly(True)
        log_view.setPlainText(self.log_content if self.log_content else "No logs yet.")
        layout.addWidget(log_view)

        # Buttons
        button_box = QDialogButtonBox()
        clear_btn = button_box.addButton("Clear", QDialogButtonBox.ActionRole)
        clear_btn.clicked.connect(lambda: (setattr(self, 'log_content', ''), log_view.clear()))
        button_box.addButton(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.exec()

    def _perform_search(self):
        """Search for games by name using SteamGridDB API."""
        import os
        search_term = self.search_input.text().strip()

        if not search_term:
            self.search_status.setText("Please enter a game name to search")
            return

        # Check for API key
        api_key = os.environ.get("SGDB_API_KEY", "").strip()
        if not api_key:
            self.search_status.setText("SteamGridDB API key required. Set it in Settings (gear icon).")
            return

        # Clear previous results
        self.search_results_list.clear()
        self.search_status.setText("Searching SteamGridDB...")
        self.btn_search.setEnabled(False)

        # Run search in background thread
        def do_search():
            try:
                results = run_backend.search_autocomplete(
                    api_key=api_key,
                    base_url="https://www.steamgriddb.com/api/v2",
                    term=search_term,
                    timeout_s=30
                )
                return results
            except Exception as e:
                return {"error": str(e)}

        def on_search_complete(results):
            self.btn_search.setEnabled(True)

            if isinstance(results, dict) and "error" in results:
                self.search_status.setText(f"Search error: {results['error']}")
                return

            if not results:
                self.search_status.setText(f"No games found for '{search_term}'")
                return

            # Store results and populate list
            self.search_results_data = results
            for game in results:
                game_name = game.get("name", "Unknown")
                game_id = game.get("id", "")
                release_date = game.get("release_date")
                year = ""
                if release_date:
                    try:
                        from datetime import datetime
                        year = f" ({datetime.fromtimestamp(release_date).year})"
                    except (ValueError, OSError, OverflowError):
                        pass

                item_text = f"{game_name}{year}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, {
                    "name": game_name,
                    "game_id": game_id,
                    "sgdb_data": game
                })
                self.search_results_list.addItem(item)

            self.search_status.setText(f"Found {len(results)} games. Select one and click 'Start Processing'")

        # Use QThread for background search
        from PySide6.QtCore import QThread, Signal

        class SearchThread(QThread):
            finished = Signal(object)

            def __init__(self, search_func):
                super().__init__()
                self.search_func = search_func

            def run(self):
                result = self.search_func()
                self.finished.emit(result)

        self._search_thread = SearchThread(do_search)
        self._search_thread.finished.connect(on_search_complete)
        self._search_thread.start()

    def _get_selected_platforms(self):
        """Get list of currently selected platform IDs."""
        selected = []
        seen = set()

        # Use the main unified platform list
        for item in self.main_platform_list.selectedItems():
            plat_id = item.data(Qt.UserRole + 3)
            if not plat_id:
                plat_id = item.text()
            if plat_id not in seen:
                selected.append(plat_id)
                seen.add(plat_id)
        return selected

    def _refresh_platform_list_filter(self):
        """Refresh the main platform list based on current publisher filter."""
        # Store current selections
        selected_ids = set()
        for i in range(self.main_platform_list.count()):
            item = self.main_platform_list.item(i)
            if item.isSelected():
                plat_id = item.data(Qt.UserRole + 3) or item.text()
                selected_ids.add(plat_id)

        # Show/hide items based on filter
        publisher_filter = self.current_publisher_filter

        for i in range(self.main_platform_list.count()):
            item = self.main_platform_list.item(i)
            item_publisher = item.data(Qt.UserRole)  # Publisher stored in UserRole

            if publisher_filter == "All":
                item.setHidden(False)
            elif publisher_filter in ["Nintendo", "Sony", "Microsoft", "Sega"]:
                item.setHidden(item_publisher != publisher_filter)
            else:  # "Other"
                major_publishers = ["Nintendo", "Sony", "Microsoft", "Sega"]
                item.setHidden(item_publisher in major_publishers)

    def _show_processing_options_dialog(self, selected_game_names, search_input_text, platforms, total_games_estimate):
        """Show dialog to choose what to process."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QRadioButton, QButtonGroup

        dialog = QDialog(self)
        dialog.setWindowTitle("Processing Options")
        dialog.setMinimumWidth(450)

        layout = QVBoxLayout(dialog)

        # Header
        header = QLabel(f"<b>What would you like to process?</b><br>"
                       f"<span style='color: #888;'>Selected platforms: {len(platforms)}</span>")
        layout.addWidget(header)

        layout.addSpacing(10)

        # Radio button group
        button_group = QButtonGroup(dialog)
        selected_choice = [None]  # Use list to allow modification in nested function
        selected_term = [None]

        # Option 1: Selected game(s) from search results
        if selected_game_names:
            games_text = selected_game_names[0] if len(selected_game_names) == 1 else f"{len(selected_game_names)} games"
            radio_selected = QRadioButton(f"Selected game: \"{games_text}\" ({len(selected_game_names)} game{'s' if len(selected_game_names) > 1 else ''})")
            radio_selected.setChecked(True)
            button_group.addButton(radio_selected, 1)
            layout.addWidget(radio_selected)

        # Option 2: Search keyword
        if search_input_text:
            radio_keyword = QRadioButton(f"Search keyword: \"{search_input_text}\" (search across all games)")
            if not selected_game_names:
                radio_keyword.setChecked(True)
            button_group.addButton(radio_keyword, 2)
            layout.addWidget(radio_keyword)

        # Option 3: All games
        radio_all = QRadioButton(f"All games for selected platforms (~{total_games_estimate:,} games)")
        if not selected_game_names and not search_input_text:
            radio_all.setChecked(True)
        button_group.addButton(radio_all, 3)
        layout.addWidget(radio_all)

        layout.addSpacing(10)

        # Warning for "all" option
        warning = QLabel("<span style='color: #ffaa00; font-size: 11px;'>"
                        "Note: Processing all games may take a long time.</span>")
        warning.setVisible(False)
        layout.addWidget(warning)

        def on_selection_changed(button):
            warning.setVisible(button_group.id(button) == 3)

        button_group.buttonClicked.connect(on_selection_changed)
        # Show warning if "all" is initially selected
        if button_group.checkedId() == 3:
            warning.setVisible(True)

        layout.addStretch()

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() == QDialog.Accepted:
            checked_id = button_group.checkedId()
            if checked_id == 1 and selected_game_names:
                # Selected game(s)
                return ("selected", selected_game_names[0] if len(selected_game_names) == 1 else None)
            elif checked_id == 2 and search_input_text:
                # Keyword search
                return ("keyword", search_input_text)
            else:
                # All games
                return ("all", None)

        return (None, None)  # Cancelled

    def open_options(self):
        """Open options dialog."""
        dialog = OptionsDialog(
            parent=self,
            config_path=self.config_path,
            workers=self.workers_value,
            limit=self.limit_value,
            source_priority_widget=self.source_priority
        )

        # Set current settings
        if self.custom_border_settings:
            dialog.set_custom_border_settings(self.custom_border_settings)
        dialog.set_steamgriddb_settings(self.steamgriddb_settings)
        dialog.set_interactive_settings(self.interactive_settings)

        if dialog.exec() == QDialog.Accepted:
            # Update stored values
            self.config_path = dialog.get_config_path()
            self.workers_value = dialog.get_workers()
            self.limit_value = dialog.get_limit()

            # Update source priority and save to config
            source_order = dialog.get_source_order()
            self.source_priority.set_source_order(source_order)
            self.save_source_order_to_config(source_order)

            # Save export settings to config
            export_settings = dialog.get_export_settings()
            self._save_export_settings_to_config(export_settings)

            # Update custom border settings
            self.custom_border_settings = dialog.get_custom_border_settings()

            # Sync hero settings
            hero_settings = dialog.get_hero_settings()
            self.download_heroes.setChecked(hero_settings.get("enabled", True))

            # Sync SteamGridDB settings
            self.steamgriddb_settings = dialog.get_steamgriddb_settings()
            self.square_only_toggle.setChecked(self.steamgriddb_settings.get("square_only", True))

            # Sync interactive mode settings
            self.interactive_settings = dialog.get_interactive_settings()
            self._save_interactive_settings_to_config()

            # Reload platforms if config changed
            self.load_platforms_from_config()

    def browse_config(self):
        """This method is kept for compatibility but now opens options dialog."""
        self.open_options()

    def load_platforms_from_config(self):
        try:
            cfg = get_config()
        except Exception as e:
            self.main_platform_list.clear()
            self.append_log(f"Failed to load config: {e}")
            return

        # Load SteamGridDB square_only setting from config
        art_sources = cfg.get("art_sources", {})
        if "steamgriddb_square_only" in art_sources:
            self.steamgriddb_settings["square_only"] = art_sources["steamgriddb_square_only"]
            self.square_only_toggle.setChecked(self.steamgriddb_settings["square_only"])

        # Load interactive mode settings from config
        interactive_cfg = cfg.get("interactive_mode", {})
        if interactive_cfg:
            self.interactive_settings["icons"] = interactive_cfg.get("icons", True)
            self.interactive_settings["heroes"] = interactive_cfg.get("heroes", False)
            self.interactive_settings["logos"] = interactive_cfg.get("logos", False)
            self.interactive_settings["screenshots"] = interactive_cfg.get("screenshots", False)
            self.append_log(f"[CONFIG] Interactive settings: {self.interactive_settings}")

        platforms_cfg = cfg.get("platforms", {})
        platform_icons_dir = Path(cfg.get("paths", {}).get("platform_icons_dir", "./platform_icons"))

        # Store current selections before clearing
        selected_ids = set()
        for i in range(self.main_platform_list.count()):
            item = self.main_platform_list.item(i)
            if item.isSelected():
                plat_id = item.data(Qt.UserRole + 3) or item.text()
                selected_ids.add(plat_id)

        # Clear the main list
        self.main_platform_list.clear()

        # Build platform data with metadata
        platform_data = []
        for plat_id, plat_config in platforms_cfg.items():
            publisher = plat_config.get("publisher", "Unknown")
            year = plat_config.get("year", 9999)
            plat_type = plat_config.get("type", "unknown")

            platform_data.append({
                "id": plat_id,
                "publisher": publisher,
                "year": year,
                "type": plat_type,
                "config": plat_config
            })

        # Build sort key based on selected sort mode
        def get_sort_key(platform):
            type_order = {"console": 0, "handheld": 1, "hybrid": 2, "mobile": 3, "unknown": 4}
            sort_text = self.sort_mode.currentText()

            if sort_text == "Name":
                return (platform["id"],)
            elif sort_text == "Year":
                return (platform["year"], platform["id"])
            elif sort_text == "Type":
                return (type_order.get(platform["type"], 99), platform["year"], platform["id"])

            return (platform["id"],)

        platform_data.sort(key=get_sort_key)

        # Check which platforms have borders
        borders_dir = get_borders_dir()

        # Platform name abbreviations
        name_abbreviations = {
            "GAME_BOY_ADVANCE": "GBA",
            "GAME_BOY_COLOR": "GBC",
            "GAME_BOY": "GB",
            "GAME_GEAR": "GG",
            "NINTENDO_3DS": "3DS",
            "NINTENDO_DS": "DS",
            "NINTENDO_64": "N64",
            "PLAYSTATION_VITA": "PS Vita",
            "PLAYSTATION_2": "PS2",
            "PLAYSTATION_3": "PS3",
            "PLAYSTATION_4": "PS4",
            "PLAYSTATION_5": "PS5",
            "PLAYSTATION_PORTABLE": "PSP",
            "PLAYSTATION": "PS1",
            "SEGA_GENESIS": "Genesis",
            "SEGA_DREAMCAST": "Dreamcast",
            "SEGA_MASTER_SYSTEM": "Master System",
            "SUPER_NINTENDO": "SNES",
            "NEO_GEO_POCKET_COLOR": "NGPC",
        }

        # Add platforms to the unified list
        for plat in platform_data:
            plat_id = plat["id"]
            publisher = plat["publisher"]
            plat_config = plat["config"]

            # Check if platform has a border (skip if not)
            border_filename = plat_config.get("border_file", f"{plat_id}.png")
            border_path = borders_dir / border_filename
            if not border_path.exists():
                continue

            # Simplify platform name
            display_name = name_abbreviations.get(plat_id, plat_id.replace("_", " "))

            # Create item
            item = QListWidgetItem()
            item.setText(display_name)
            item.setData(Qt.UserRole, publisher)  # Store publisher for filtering
            item.setData(Qt.UserRole + 1, plat["year"])
            item.setData(Qt.UserRole + 2, plat["type"])
            item.setData(Qt.UserRole + 3, plat_id)  # Actual platform ID

            # Try to find platform icon
            icon_filename = f"{plat_id}.png"
            icon_path = self._find_file_case_insensitive(platform_icons_dir, icon_filename)

            if icon_path and icon_path.exists():
                icon = QIcon(str(icon_path))
                item.setIcon(icon)

            # Add to main list
            self.main_platform_list.addItem(item)

            # Restore selection if was selected before
            if plat_id in selected_ids:
                item.setSelected(True)

        # Apply current filter
        self._refresh_platform_list_filter()

        # Update counter
        self._update_platform_counter()

        # Also load source order
        self.load_source_order_from_config()

    def load_source_order_from_config(self):
        """Load source priority from config file."""
        try:
            cfg = get_config()

            art_sources = cfg.get("art_sources", {})

            # Migrate legacy format if needed
            art_sources = run_backend.migrate_legacy_art_sources(art_sources)

            providers = art_sources.get("providers", [])

            # Add display names
            display_map = {
                "steamgriddb": "SteamGridDB",
                "libretro": "Libretro Thumbnails",
                "igdb": "IGDB (Twitch)",
                "thegamesdb": "TheGamesDB",
                "steam": "Steam Store"
            }

            for p in providers:
                p["display_name"] = display_map.get(p["id"], p["id"])

            self.source_priority.set_source_order(providers)

        except Exception as e:
            self.append_log(f"Failed to load source priority: {e}")

    def _save_export_settings_to_config(self, export_settings: dict):
        """Save export format settings to config file."""
        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            return

        try:
            # Load current config
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            # Update export format settings
            cfg["export_format"] = export_settings.get("format", "JPEG")
            cfg["jpeg_quality"] = export_settings.get("jpeg_quality", 95)

            # Write back
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
            invalidate_config_cache()

            self.append_log(f"[CONFIG] Export format set to {export_settings.get('format', 'JPEG')}")

        except Exception as e:
            self.append_log(f"Failed to save export settings: {e}")

    def _save_interactive_settings_to_config(self):
        """Save interactive mode settings to config file."""
        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            return

        try:
            # Load current config
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            # Update interactive_mode settings
            cfg["interactive_mode"] = {
                "icons": self.interactive_settings.get("icons", True),
                "heroes": self.interactive_settings.get("heroes", False),
                "logos": self.interactive_settings.get("logos", False),
                "screenshots": self.interactive_settings.get("screenshots", False)
            }

            # Write back
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
            invalidate_config_cache()

            self.append_log(f"[CONFIG] Interactive settings saved: {self.interactive_settings}")

        except Exception as e:
            self.append_log(f"Failed to save interactive settings: {e}")

    def save_source_order_to_config(self, source_order=None):
        """Save current source priority to config file."""
        if source_order is None:
            source_order = self.source_priority.get_source_order()

        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            QMessageBox.warning(self, "Config Error", "Config file not found.")
            return

        try:
            # Load current config
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            # Update art_sources section
            sources = source_order

            # Remove display_name before saving (it's only for UI)
            sources_clean = []
            for src in sources:
                clean_src = {"id": src["id"], "enabled": src["enabled"]}
                # Preserve provider-specific settings if they exist
                if src["id"] == "steamgriddb" and "square_only" in src:
                    clean_src["square_only"] = src["square_only"]
                if src["id"] == "libretro" and "crop_mode" in src:
                    clean_src["crop_mode"] = src["crop_mode"]
                sources_clean.append(clean_src)

            if "art_sources" not in cfg:
                cfg["art_sources"] = {}

            cfg["art_sources"]["providers"] = sources_clean

            # Write back
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
            invalidate_config_cache()

            self.append_log("[CONFIG] Source priority saved to config.yaml")
            QMessageBox.information(self, "Success", "Source priority saved to config.yaml")

        except Exception as e:
            self.append_log(f"Failed to save source priority: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save config: {e}")

    def _on_source_order_changed(self, sources):
        """Handle source order changes (for future auto-save or validation)."""
        # Could add validation or auto-save here
        pass

    def _on_platform_selection_changed(self):
        """Handle platform selection change."""
        self._update_platform_counter()

    def _update_platform_counter(self):
        """Update the platform selection counter badge."""
        count = len(self._get_selected_platforms())
        if count == 0:
            self.platform_counter.setText("0 selected")
            self.platform_counter.setObjectName("label_muted")
        else:
            self.platform_counter.setText(f"{count} selected")
            self.platform_counter.setObjectName("badge")
        # Force style recalculation after objectName change
        self.platform_counter.style().unpolish(self.platform_counter)
        self.platform_counter.style().polish(self.platform_counter)

    def select_all(self):
        """Select all visible platforms."""
        for i in range(self.main_platform_list.count()):
            item = self.main_platform_list.item(i)
            if not item.isHidden():
                item.setSelected(True)

    def select_none(self):
        """Deselect all platforms."""
        self.main_platform_list.clearSelection()

    # ---------- Job control ----------
    def start_job(self):
        cfg_path = Path(self.config_path).expanduser()
        if not cfg_path.exists():
            QMessageBox.warning(self, "Config missing", "Please choose a valid config.yaml")
            return

        # Get selected platforms from all tabs (using selection instead of checkState)
        platforms = self._get_selected_platforms()

        if not platforms:
            QMessageBox.information(self, "No platforms selected", "Select at least one platform.")
            return

        # Check API keys and warn user about missing ones
        self._check_api_keys_warning()

        # Get selected search results
        selected_search_items = self.search_results_list.selectedItems()
        selected_game_names = []
        if selected_search_items:
            for item in selected_search_items:
                data = item.data(Qt.UserRole)
                if data and "name" in data:
                    selected_game_names.append(data["name"])

        # Get search input text
        search_input_text = self.search_input.text().strip()

        # Count total games for "all" option (estimate from config)
        try:
            cfg = get_config()
            total_games = 0
            for plat_id in platforms:
                plat_cfg = cfg.get("platforms", {}).get(plat_id, {})
                games = plat_cfg.get("games", [])
                if games:
                    total_games += len(games)
                else:
                    total_games += 100  # Estimate if no local list
        except Exception:
            total_games = len(platforms) * 100  # Rough estimate

        # Show processing options dialog
        choice, search_term = self._show_processing_options_dialog(
            selected_game_names=selected_game_names,
            search_input_text=search_input_text,
            platforms=platforms,
            total_games_estimate=total_games
        )

        if choice is None:
            return  # User cancelled

        # Use stored values from options
        workers = self.workers_value
        limit = self.limit_value
        if limit <= 0:
            limit = 0

        # Force sequential processing in interactive mode
        if self.interactive_mode.isChecked():
            workers = 1
            self.append_log("[INTERACTIVE] Using 1 worker for sequential processing")

        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        # Clear previous preview
        self.clear_preview()

        self._cancel_token = run_backend.CancelToken()
        callbacks = BackendCallbacks()
        callbacks.progress.connect(self.on_progress)
        callbacks.log.connect(self.append_log)
        callbacks.finished.connect(self.on_finished)
        callbacks.preview.connect(self.add_preview_icon)  # Connect live preview

        # Get source configuration from widget
        source_order_config = self.source_priority.get_source_order()

        # Set letter filter if applicable
        letter_filter = None
        if self.search_mode.currentText() == "Filter by Letter" and choice == "all":
            letter_filter = self.letter_filter.currentText()

        # Get region preference
        region_pref = self.region_combo.currentData()

        self.append_log(f"[PROCESS] Mode: {choice}, Search: {search_term or 'None'}, Platforms: {len(platforms)}, Region: {region_pref}")

        def _run():
            try:
                # Bridge backend callbacks (expects callables) -> Qt signals
                cb_dict = {
                    "progress": lambda done, total: callbacks.progress.emit(done, total),
                    "log": lambda msg: callbacks.log.emit(str(msg)),
                    "preview": lambda path: callbacks.preview.emit(str(path)),
                    "request_selection": self._request_artwork_selection,
                    # Asset-specific selection callbacks for interactive mode
                    "request_hero_selection": lambda t, p, opts: self._request_artwork_selection(t, p, opts, "hero"),
                    "request_logo_selection": lambda t, p, opts: self._request_artwork_selection(t, p, opts, "logo"),
                    "request_screenshot_selection": lambda t, p, opts: self._request_artwork_selection(t, p, opts, "screenshot"),
                }

                ok, msg = run_backend.run_job(
                    config_path=cfg_path,
                    platforms=platforms,
                    workers=workers,
                    limit=limit,
                    cancel=self._cancel_token,
                    callbacks=cb_dict,
                    source_order=source_order_config,
                    search_term=search_term,
                    letter_filter=letter_filter,
                    interactive_mode=self.interactive_mode.isChecked(),
                    download_heroes=self.download_heroes.isChecked(),
                    hero_count=1,
                    region_preference=region_pref,
                    fallback_settings=self.fallback_settings,
                    custom_border_settings=self.custom_border_settings,
                    steamgriddb_square_only=self.steamgriddb_settings.get("square_only", True),
                    interactive_settings=self.interactive_settings if self.interactive_mode.isChecked() else None
                )

            except Exception as e:
                ok, msg = False, f"Unhandled error: {e}"

            callbacks.finished.emit(ok, msg)

        self._worker_thread = threading.Thread(target=_run, daemon=True)
        self._worker_thread.start()

    def cancel_job(self):
        if self._cancel_token is not None:
            self._cancel_token.cancel()
            self.append_log("[UI] Cancel requested…")
        self.btn_cancel.setEnabled(False)

    def on_progress(self, done: int, total: int):
        if total <= 0:
            self.progress.setValue(0)
            self.progress.setFormat("Ready")
            return
        pct = int(round((done / total) * 100))
        pct = max(0, min(100, pct))
        self.progress.setValue(pct)
        self.progress.setFormat(f"{done}/{total} ({pct}%)")

    def on_finished(self, ok: bool, msg: str):
        self.append_log(f"[DONE] {msg}")
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if not ok:
            self.progress.setFormat("Cancelled" if "cancel" in msg.lower() else "Error")
        else:
            self.progress.setFormat("Complete")
            # Auto-push to device if enabled
            if hasattr(self, 'device_settings') and self.device_settings.get("enabled", False):
                self._auto_push_to_device()

    # ---------- Preview and output ----------
    def _check_api_keys_warning(self):
        """Check for missing API keys and show a warning if any are missing."""
        from api_key_manager import get_manager

        key_manager = get_manager()
        missing_keys = []

        # Check SteamGridDB
        if not key_manager.get_key("steamgriddb"):
            missing_keys.append("SteamGridDB")

        # Check IGDB (needs both client ID and secret)
        igdb_id = key_manager.get_key("igdb_client_id")
        igdb_secret = key_manager.get_key("igdb_client_secret")
        if not igdb_id or not igdb_secret:
            missing_keys.append("IGDB")

        # TheGamesDB has an embedded key, so it should always work
        # No need to check it

        if missing_keys:
            missing_list = ", ".join(missing_keys)
            QMessageBox.warning(
                self,
                "API Keys Not Configured",
                f"The following API sources are not configured:\n\n"
                f"• {chr(10).join(missing_keys)}\n\n"
                f"Results may be limited. Configure API keys in Settings (gear icon) "
                f"to access more artwork sources.\n\n"
                f"TheGamesDB and Libretro will still work without configuration."
            )

    def open_preview(self):
        """Open preview dialog to adjust artwork positioning."""
        from preview_window import PreviewWindow

        dialog = PreviewWindow(self)
        dialog.exec()

    def open_output_dir(self):
        """Open output directory in file explorer."""
        try:
            cfg = get_config()
        except Exception as e:
            QMessageBox.warning(self, "Config Error", f"Failed to load config: {e}")
            return

        output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir.absolute())))

    def _auto_push_to_device(self):
        """Automatically push generated assets to connected Android device via ADB."""
        import subprocess
        from rom_parser import check_adb_available, get_adb_path, get_adb_devices

        # Check if ADB is available
        if not check_adb_available():
            self.append_log("[DEVICE] ADB not available - skipping auto-push")
            return

        # Get connected devices
        devices = get_adb_devices()
        if not devices:
            self.append_log("[DEVICE] No Android devices connected - skipping auto-push")
            return

        # Use first connected device
        device_id = devices[0][0]
        adb_path = get_adb_path()
        device_base_path = self.device_settings.get("path", "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles")

        # Get output directory
        try:
            cfg = get_config()
            cfg_path = Path(self.config_path)
            output_dir = cfg_path.parent / cfg.get("paths", {}).get("output_dir", "./output")
        except Exception:
            cfg_path = Path(self.config_path)
            output_dir = cfg_path.parent / "output"

        if not output_dir.exists():
            self.append_log("[DEVICE] No output directory found - skipping auto-push")
            return

        self.append_log(f"[DEVICE] Auto-pushing to device {device_id}...")
        self.progress.setFormat("Pushing to device...")

        # Find all game folders in output that have icon.png or icon.jpg
        pushed = 0
        errors = 0

        # Scan platform folders
        for platform_dir in output_dir.iterdir():
            if not platform_dir.is_dir():
                continue

            platform_name = platform_dir.name

            # Scan game folders within platform
            for game_dir in platform_dir.iterdir():
                if not game_dir.is_dir():
                    continue

                game_name = game_dir.name
                device_game_path = f"{device_base_path}/{platform_name}/{game_name}"

                # Find all asset files to push
                asset_files = []
                for asset_file in game_dir.iterdir():
                    if asset_file.is_file() and asset_file.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                        asset_files.append(asset_file)

                if not asset_files:
                    continue

                # Create game folder on device if needed
                try:
                    subprocess.run(
                        [adb_path, "-s", device_id, "shell", f'mkdir -p "{device_game_path}"'],
                        capture_output=True, text=True, timeout=10
                    )
                except Exception:
                    pass

                # Push each asset file
                for asset_file in asset_files:
                    try:
                        result = subprocess.run(
                            [adb_path, "-s", device_id, "push", str(asset_file), f"{device_game_path}/{asset_file.name}"],
                            capture_output=True, text=True, timeout=30
                        )
                        if result.returncode == 0:
                            pushed += 1
                        else:
                            errors += 1
                            self.append_log(f"[DEVICE] Failed to push {asset_file.name}: {result.stderr}")
                    except Exception as e:
                        errors += 1
                        self.append_log(f"[DEVICE] Error pushing {asset_file.name}: {e}")

        if pushed > 0:
            self.append_log(f"[DEVICE] Pushed {pushed} files to device ({errors} errors)")
            self.progress.setFormat(f"Complete - {pushed} pushed")
        else:
            self.append_log("[DEVICE] No files to push")
            self.progress.setFormat("Complete")
