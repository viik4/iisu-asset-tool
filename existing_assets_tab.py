"""
Existing Assets Tab for iiSU Asset Tool
Browse and manage previously generated icons and assets.
"""
import threading
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from PySide6.QtCore import Qt, Signal, QObject, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox,
    QMessageBox, QFrame, QGroupBox, QScrollArea, QGridLayout,
    QLineEdit
)

from app_paths import get_config_path
from icon_generator_tab import ClickableIconPreview
from rom_parser import IISU_PLATFORM_FOLDERS
import run_backend


def _build_folder_to_platform_map() -> Dict[str, str]:
    """Build reverse lookup from folder name to platform key."""
    mapping = {}
    for platform_key, folder_names in IISU_PLATFORM_FOLDERS.items():
        for folder_name in folder_names:
            mapping[folder_name.lower()] = platform_key
    return mapping

FOLDER_TO_PLATFORM = _build_folder_to_platform_map()


class ExistingAssetsTab(QWidget):
    """Tab for browsing and managing existing generated assets."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.config_path = str(get_config_path())
        self._cancel_token = None
        self._rescrape_in_progress = False
        self._rescrape_cancelled = False

        # Asset data storage
        self.all_assets = []  # All loaded assets
        self.filtered_assets = []  # Currently displayed after filtering
        self._platforms = set()  # Set of platforms found

        self._log_messages = []

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Header
        header = QLabel("Existing Assets")
        header.setObjectName("header")
        layout.addWidget(header)

        desc = QLabel("Browse and manage previously generated icons. Double-click to re-scrape, or select multiple and use batch re-scrape.")
        desc.setStyleSheet("font-size: 11px; color: #888;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Controls row
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_group)

        # First row: Scan and filter
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        self.btn_scan = QPushButton("Scan Output Folder")
        self.btn_scan.setMinimumWidth(140)
        self.btn_scan.setMinimumHeight(32)
        self.btn_scan.clicked.connect(self._scan_assets)
        row1.addWidget(self.btn_scan)

        row1.addWidget(QLabel("Platform:"))
        self.platform_filter = QComboBox()
        self.platform_filter.setMinimumWidth(150)
        self.platform_filter.addItem("All Platforms", "all")
        self.platform_filter.currentIndexChanged.connect(self._apply_filter)
        row1.addWidget(self.platform_filter)

        row1.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by game name...")
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._apply_filter)
        row1.addWidget(self.search_input)

        row1.addStretch()
        controls_layout.addLayout(row1)

        # Second row: Selection and actions
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setMinimumWidth(90)
        self.btn_select_all.clicked.connect(self._select_all)
        row2.addWidget(self.btn_select_all)

        self.btn_select_none = QPushButton("Select None")
        self.btn_select_none.setMinimumWidth(90)
        self.btn_select_none.clicked.connect(self._select_none)
        row2.addWidget(self.btn_select_none)

        row2.addSpacing(20)

        self.btn_rescrape = QPushButton("Re-scrape Selected")
        self.btn_rescrape.setMinimumWidth(140)
        self.btn_rescrape.setObjectName("btn_start")
        self.btn_rescrape.clicked.connect(self._rescrape_selected)
        row2.addWidget(self.btn_rescrape)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumWidth(80)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_rescrape)
        row2.addWidget(self.btn_cancel)

        row2.addStretch()

        # Info label
        self.info_label = QLabel("Click 'Scan Output Folder' to load existing assets")
        self.info_label.setStyleSheet("font-size: 11px; color: #888;")
        row2.addWidget(self.info_label)

        controls_layout.addLayout(row2)
        layout.addWidget(controls_group)

        # Assets grid in scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)

        self.scroll_area.setWidget(self.grid_widget)
        layout.addWidget(self.scroll_area, 1)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(self.status_label)

    def _scan_assets(self):
        """Scan output folder for existing generated icons."""
        cfg_path = Path(self.config_path)
        if not cfg_path.exists():
            QMessageBox.warning(self, "Error", "Config file not found.")
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            output_dir = cfg_path.parent / cfg.get("paths", {}).get("output_dir", "./output")
            if not output_dir.exists():
                QMessageBox.information(
                    self,
                    "No Output",
                    "Output folder does not exist yet.\nGenerate some icons first."
                )
                return

            self.status_label.setText("Scanning...")
            self.btn_scan.setEnabled(False)

            # Clear existing
            self._clear_assets()
            self._platforms.clear()

            # Reset filter
            self.platform_filter.blockSignals(True)
            self.platform_filter.clear()
            self.platform_filter.addItem("All Platforms", "all")
            self.platform_filter.blockSignals(False)

            # Scan output folder structure: output/{platform}/{game}/icon.png or icon.jpg
            found_count = 0
            for platform_dir in sorted(output_dir.iterdir()):
                if not platform_dir.is_dir():
                    continue

                platform_name = platform_dir.name
                self._platforms.add(platform_name)

                for game_dir in sorted(platform_dir.iterdir()):
                    if not game_dir.is_dir():
                        continue

                    game_name = game_dir.name

                    # Look for icon file
                    icon_path = None
                    for icon_name in ["icon.png", "icon.jpg", "icon.jpeg"]:
                        potential_icon = game_dir / icon_name
                        if potential_icon.exists():
                            icon_path = potential_icon
                            break

                    if icon_path:
                        self.all_assets.append({
                            "path": str(icon_path),
                            "title": game_name,
                            "platform": platform_name,
                            "widget": None
                        })
                        found_count += 1

            # Update platform filter dropdown
            self.platform_filter.blockSignals(True)
            for platform in sorted(self._platforms):
                display_name = platform.replace("_", " ").title()
                self.platform_filter.addItem(display_name, platform)
            self.platform_filter.blockSignals(False)

            # Display assets
            self._apply_filter()

            self.status_label.setText(f"Found {found_count} icons across {len(self._platforms)} platforms")
            self.btn_scan.setEnabled(True)

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to scan output: {e}")
            self.status_label.setText("Scan failed")
            self.btn_scan.setEnabled(True)
            import traceback
            traceback.print_exc()

    def _clear_assets(self):
        """Clear all asset widgets."""
        for asset_data in self.all_assets:
            if asset_data.get("widget"):
                self.grid_layout.removeWidget(asset_data["widget"])
                asset_data["widget"].deleteLater()
                asset_data["widget"] = None
        self.all_assets.clear()
        self.filtered_assets.clear()

    def _apply_filter(self):
        """Apply platform and search filters to display assets."""
        # Remove current widgets from grid
        for asset_data in self.all_assets:
            if asset_data.get("widget"):
                self.grid_layout.removeWidget(asset_data["widget"])
                asset_data["widget"].deleteLater()
                asset_data["widget"] = None

        self.filtered_assets.clear()

        # Get filter values
        selected_platform = self.platform_filter.currentData()
        search_text = self.search_input.text().strip().lower()

        # Filter assets
        for asset_data in self.all_assets:
            # Platform filter
            if selected_platform != "all" and asset_data["platform"] != selected_platform:
                continue

            # Search filter
            if search_text and search_text not in asset_data["title"].lower():
                continue

            self.filtered_assets.append(asset_data)

        # Create widgets and add to grid (6 per row for wider view)
        cols = 6
        for i, asset_data in enumerate(self.filtered_assets):
            preview_item = ClickableIconPreview(
                asset_data["path"],
                asset_data["title"],
                asset_data["platform"]
            )
            preview_item.clicked.connect(self._on_asset_clicked)
            preview_item.selection_changed.connect(self._on_selection_changed)

            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(preview_item, row, col)

            asset_data["widget"] = preview_item

        # Update info label
        self._update_info_label()

    def _update_info_label(self):
        """Update the info label with current counts."""
        total = len(self.all_assets)
        showing = len(self.filtered_assets)
        selected = sum(1 for a in self.filtered_assets if a.get("widget") and a["widget"].is_selected())

        if total == showing:
            self.info_label.setText(f"{showing} icons | {selected} selected")
        else:
            self.info_label.setText(f"Showing {showing}/{total} icons | {selected} selected")

    def _on_asset_clicked(self, preview_widget: ClickableIconPreview):
        """Handle double-click on asset to re-scrape."""
        print(f"[DEBUG] _on_asset_clicked called for: {preview_widget.game_title}")
        game_title = preview_widget.game_title
        platform = preview_widget.platform

        if not platform:
            QMessageBox.warning(
                self,
                "Cannot Re-scrape",
                "Platform information is not available for this icon."
            )
            return

        reply = QMessageBox.question(
            self,
            "Re-scrape Artwork",
            f"Re-scrape artwork for:\n\n"
            f"Game: {game_title}\n"
            f"Platform: {platform}\n\n"
            "This will fetch all available artwork and let you choose.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        print(f"[DEBUG] Calling _run_single_rescrape for: {game_title}")
        self._run_single_rescrape(preview_widget)

    def _on_selection_changed(self, preview_widget: ClickableIconPreview, is_selected: bool):
        """Handle selection change."""
        self._update_info_label()

    def _select_all(self):
        """Select all visible assets."""
        for asset_data in self.filtered_assets:
            if asset_data.get("widget"):
                asset_data["widget"].set_selected(True)
        self._update_info_label()

    def _select_none(self):
        """Deselect all visible assets."""
        for asset_data in self.filtered_assets:
            if asset_data.get("widget"):
                asset_data["widget"].set_selected(False)
        self._update_info_label()

    def _rescrape_selected(self):
        """Re-scrape all selected assets."""
        if self._rescrape_in_progress:
            QMessageBox.warning(self, "In Progress", "A re-scrape is already in progress.")
            return

        selected_widgets = [
            a["widget"] for a in self.filtered_assets
            if a.get("widget") and a["widget"].is_selected() and a["widget"].platform
        ]

        if not selected_widgets:
            QMessageBox.information(self, "No Selection", "Please select at least one icon to re-scrape.")
            return

        reply = QMessageBox.question(
            self,
            "Re-scrape Selected",
            f"Re-scrape {len(selected_widgets)} selected icon(s)?\n\n"
            "You will be prompted to select artwork for each one.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        self._run_batch_rescrape(selected_widgets)

    def _get_platform_key(self, folder_name: str) -> str:
        """Convert folder name (e.g. 'dc') to platform key (e.g. 'DREAMCAST')."""
        # Try direct lookup first
        platform_key = FOLDER_TO_PLATFORM.get(folder_name.lower())
        if platform_key:
            return platform_key
        # Fallback: return as-is (maybe it's already a platform key)
        return folder_name

    def _get_border_path_for_platform(self, platform: str) -> Optional[str]:
        """Get the border path for a platform from config."""
        try:
            cfg_path = Path(self.config_path)
            if not cfg_path.exists():
                return None

            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            # Convert folder name to platform key
            platform_key = self._get_platform_key(platform)
            print(f"[DEBUG] _get_border_path_for_platform: {platform} -> {platform_key}")

            platforms_cfg = cfg.get("platforms", {})
            pconf = platforms_cfg.get(platform_key, {})
            border_file = pconf.get("border_file")

            if border_file:
                # Check if absolute path
                if Path(border_file).is_absolute() and Path(border_file).exists():
                    return str(border_file)
                # Otherwise it's relative to borders dir
                borders_dir = cfg_path.parent / cfg.get("paths", {}).get("borders_dir", "./borders")
                border_path = borders_dir / border_file
                if border_path.exists():
                    return str(border_path)

            return None
        except Exception as e:
            print(f"[DEBUG] Error getting border path: {e}")
            return None

    def _run_single_rescrape(self, preview_widget: ClickableIconPreview):
        """Run re-scrape for a single asset."""
        print(f"[DEBUG] _run_single_rescrape called")
        print(f"[DEBUG] game_title: {preview_widget.game_title}")
        print(f"[DEBUG] platform (folder): {preview_widget.platform}")
        print(f"[DEBUG] icon_path: {preview_widget.icon_path}")
        self._log(f"[RE-SCRAPE] Starting for {preview_widget.game_title}")

        # Convert folder name to platform key
        platform_key = self._get_platform_key(preview_widget.platform)
        print(f"[DEBUG] platform_key: {platform_key}")

        # Get border path for this platform
        border_path = self._get_border_path_for_platform(preview_widget.platform)
        print(f"[DEBUG] border_path: {border_path}")

        def do_rescrape():
            try:
                print(f"[DEBUG] do_rescrape thread started")
                cfg_path = Path(self.config_path)
                if not cfg_path.exists():
                    self._log("[RE-SCRAPE] Config file not found")
                    print(f"[DEBUG] Config not found: {cfg_path}")
                    return

                print(f"[DEBUG] Config path: {cfg_path}")
                print(f"[DEBUG] About to call run_backend.run_job with platform_key={platform_key}")
                cancel_token = run_backend.CancelToken()

                ok, msg = run_backend.run_job(
                    config_path=cfg_path,
                    platforms=[platform_key],
                    workers=1,
                    limit=1,
                    cancel=cancel_token,
                    callbacks={
                        "log": lambda m: self._log(str(m)),
                        "preview": lambda p, t="", pl="": self._on_rescrape_complete(preview_widget, p),
                        "request_selection": self._request_artwork_selection,
                    },
                    search_term=preview_widget.game_title,
                    interactive_mode=True,
                    download_heroes=False,
                    hero_count=0,
                    fallback_settings={"enabled": False},
                    download_screenshots=False,
                    screenshot_count=0,
                    copy_to_device=False,
                    device_path="",
                    scrape_logos=False,
                    logo_fallback_to_boxart=False,
                    force_rescrape=True,
                    output_path_override=preview_widget.icon_path,
                    border_path_override=border_path
                )

                print(f"[DEBUG] run_job returned: ok={ok}, msg={msg}")
                if ok:
                    self._log(f"[RE-SCRAPE] Completed for {preview_widget.game_title}")
                else:
                    self._log(f"[RE-SCRAPE] Failed: {msg}")

            except Exception as e:
                import traceback
                print(f"[DEBUG] Exception in do_rescrape: {e}")
                print(traceback.format_exc())
                self._log(f"[RE-SCRAPE] Error: {e}")
                self._log(traceback.format_exc())

        thread = threading.Thread(target=do_rescrape, daemon=True)
        thread.start()

    def _run_batch_rescrape(self, selected_widgets: list):
        """Run batch re-scrape for selected assets."""
        self._rescrape_in_progress = True
        self._rescrape_cancelled = False
        self.btn_rescrape.setEnabled(False)
        self.btn_rescrape.setText("Re-scraping...")
        self.btn_cancel.setEnabled(True)

        self._log(f"[RE-SCRAPE] Starting batch for {len(selected_widgets)} icons")

        def do_batch():
            try:
                cfg_path = Path(self.config_path)
                if not cfg_path.exists():
                    self._log("[RE-SCRAPE] Config file not found")
                    return

                for i, preview_widget in enumerate(selected_widgets):
                    if self._rescrape_cancelled:
                        self._log("[RE-SCRAPE] Cancelled by user")
                        break

                    game_title = preview_widget.game_title
                    platform = preview_widget.platform

                    # Convert folder name to platform key
                    platform_key = self._get_platform_key(platform)

                    self._log(f"[RE-SCRAPE] ({i+1}/{len(selected_widgets)}) {game_title}")
                    self._update_status(f"Processing {i+1}/{len(selected_widgets)}: {game_title}")

                    # Get border path for this platform
                    border_path = self._get_border_path_for_platform(platform)

                    cancel_token = run_backend.CancelToken()

                    ok, msg = run_backend.run_job(
                        config_path=cfg_path,
                        platforms=[platform_key],
                        workers=1,
                        limit=1,
                        cancel=cancel_token,
                        callbacks={
                            "log": lambda m: self._log(str(m)),
                            "preview": lambda p, t="", pl="", pw=preview_widget: self._on_rescrape_complete(pw, p),
                            "request_selection": self._request_artwork_selection_batch,
                        },
                        search_term=game_title,
                        interactive_mode=True,
                        download_heroes=False,
                        hero_count=0,
                        fallback_settings={"enabled": False},
                        download_screenshots=False,
                        screenshot_count=0,
                        copy_to_device=False,
                        device_path="",
                        scrape_logos=False,
                        logo_fallback_to_boxart=False,
                        force_rescrape=True,
                        output_path_override=preview_widget.icon_path,
                        border_path_override=border_path
                    )

                    if ok:
                        self._log(f"[RE-SCRAPE] Completed: {game_title}")
                        # Deselect on main thread
                        self._deselect_widget_on_main_thread(preview_widget)
                    else:
                        self._log(f"[RE-SCRAPE] Skipped/failed: {game_title}")

                self._log("[RE-SCRAPE] Batch complete")

            except Exception as e:
                import traceback
                self._log(f"[RE-SCRAPE] Error: {e}")
                self._log(traceback.format_exc())
            finally:
                self._finish_batch_on_main_thread()

        thread = threading.Thread(target=do_batch, daemon=True)
        thread.start()

    def _cancel_rescrape(self):
        """Cancel ongoing re-scrape."""
        self._rescrape_cancelled = True
        self.btn_cancel.setEnabled(False)
        self.status_label.setText("Cancelling...")

    def _request_artwork_selection(self, title: str, platform: str, artwork_options):
        """Request user to select artwork (called from worker thread)."""
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

    def _request_artwork_selection_batch(self, title: str, platform: str, artwork_options):
        """Request artwork selection during batch (cancel stops all)."""
        result = self._request_artwork_selection(title, platform, artwork_options)
        if result == -1:
            self._rescrape_cancelled = True
        return result

    @Slot()
    def _show_selection_dialog(self):
        """Show artwork selection dialog on main thread."""
        from artwork_picker_dialog import ArtworkPickerDialog
        try:
            dialog = ArtworkPickerDialog(
                title=self._dialog_title,
                platform=self._dialog_platform,
                artwork_options=self._dialog_options,
                parent=self
            )
            dialog.exec()
            self._dialog_result.put(dialog.get_selected_index())
        except Exception as e:
            self._log(f"[ERROR] Dialog error: {e}")
            self._dialog_result.put(None)

    def _on_rescrape_complete(self, preview_widget: ClickableIconPreview, new_path: str):
        """Called when re-scrape completes for a widget."""
        self._widget_to_refresh = preview_widget
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self,
            "_refresh_widget",
            Qt.ConnectionType.QueuedConnection
        )

    @Slot()
    def _refresh_widget(self):
        """Refresh widget icon on main thread."""
        if hasattr(self, '_widget_to_refresh') and self._widget_to_refresh:
            self._widget_to_refresh.refresh_icon()
            self._widget_to_refresh = None

    def _deselect_widget_on_main_thread(self, widget):
        """Deselect widget on main thread."""
        self._widget_to_deselect = widget
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self,
            "_deselect_widget",
            Qt.ConnectionType.QueuedConnection
        )

    @Slot()
    def _deselect_widget(self):
        """Deselect widget on main thread."""
        if hasattr(self, '_widget_to_deselect') and self._widget_to_deselect:
            self._widget_to_deselect.set_selected(False)
            self._widget_to_deselect = None
            self._update_info_label()

    def _finish_batch_on_main_thread(self):
        """Finish batch processing on main thread."""
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self,
            "_on_batch_finished",
            Qt.ConnectionType.QueuedConnection
        )

    @Slot()
    def _on_batch_finished(self):
        """Called when batch re-scrape finishes."""
        self._rescrape_in_progress = False
        self.btn_rescrape.setEnabled(True)
        self.btn_rescrape.setText("Re-scrape Selected")
        self.btn_cancel.setEnabled(False)
        self.status_label.setText("Batch complete")
        self._update_info_label()

    def _update_status(self, text: str):
        """Update status label on main thread."""
        self._status_text = text
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(
            self,
            "_set_status",
            Qt.ConnectionType.QueuedConnection
        )

    @Slot()
    def _set_status(self):
        """Set status label on main thread."""
        if hasattr(self, '_status_text'):
            self.status_label.setText(self._status_text)

    def _log(self, message: str):
        """Log a message."""
        self._log_messages.append(message)
        print(message)  # Also print to console for debugging
