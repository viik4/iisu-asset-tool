"""
iiSU Workshop Tab

Browse and download assets from the iiSU Workshop.
Assets are already styled for iiSU Launcher - just pick and apply.
"""

import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

import yaml
from PySide6.QtCore import Qt, Signal, QObject, QSize, QTimer, QRect
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QLinearGradient, QPen, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QProgressBar, QComboBox,
    QMessageBox, QTreeWidget, QTreeWidgetItem, QFrame, QGroupBox,
    QScrollArea, QGridLayout, QDialog, QDialogButtonBox,
    QRadioButton, QButtonGroup, QStackedWidget, QTabWidget,
    QApplication, QLayout, QSizePolicy, QCheckBox
)

from app_paths import get_config_path, get_config, invalidate_config_cache, get_logo_path, get_workshop_logo_path
from iisu_asset_db_local import IisuAssetDBLocal, ThemedGame, ThemedApp, ThemedAssetVariant, ThemedAssetFile, AssetType
from device_asset_dialog import get_adb_path, get_subprocess_kwargs
import requests
import subprocess
import shutil
import tempfile


class FlowLayout(QLayout):
    """A layout that arranges widgets in a flowing grid that adapts to width."""

    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing if spacing >= 0 else 12
        self._items = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def spacing(self):
        return self._spacing

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            space_x = self._spacing
            space_y = self._spacing

            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(x, y, item.sizeHint().width(), item.sizeHint().height()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + margins.bottom()


class GradientLabel(QLabel):
    """QLabel that renders text with a horizontal gradient fill (cyan → purple → magenta)."""

    def __init__(self, text: str, colors: list = None, parent=None):
        super().__init__(text, parent)
        self._colors = colors or [
            (0.0, QColor("#00DDFF")),
            (0.5, QColor("#C8B1FF")),
            (1.0, QColor("#B71AEB")),
        ]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font())

        gradient = QLinearGradient(0, 0, self.width(), 0)
        for pos, color in self._colors:
            gradient.setColorAt(pos, color)

        pen = QPen()
        pen.setBrush(gradient)
        painter.setPen(pen)
        painter.drawText(self.rect(), self.alignment() | Qt.AlignVCenter, self.text())
        painter.end()


class WorkerSignals(QObject):
    """Signals for background worker threads."""
    finished = Signal()
    error = Signal(str)
    progress = Signal(int, int)  # current, total
    result = Signal(object)
    image_loaded = Signal(str, bytes)  # preview_id, image_data (use bytes, not QPixmap for thread safety)
    connected = Signal(bool)  # success
    connect_error = Signal(str)  # error message
    refreshed = Signal(bool)  # refresh success
    download_progress = Signal(int, int, str)  # current, total, filename
    download_complete = Signal(str)  # game folder path
    download_error = Signal(str)  # error message
    device_push_progress = Signal(int, int, str)  # current, total, filename
    device_push_complete = Signal(int, int)  # copied, errors
    device_push_error = Signal(str)  # error message


class AssetVariantCard(QFrame):
    """
    Card widget displaying a single asset variant with preview.
    Shows icon preview and available asset types.
    """

    selected = Signal(object)  # Emits the variant when selected

    def __init__(self, variant: ThemedAssetVariant, parent=None):
        super().__init__(parent)
        self.variant = variant
        self._selected = False

        self.setObjectName("variant_card")
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(2)
        self.setFixedSize(160, 200)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Icon preview
        self.preview_label = QLabel()
        self.preview_label.setObjectName("variant_preview")
        self.preview_label.setFixedSize(140, 140)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("Loading...")
        layout.addWidget(self.preview_label)

        # Variant label
        if variant.variant_number > 1:
            label_text = f"Variant {variant.variant_number}"
        else:
            label_text = "Original"
        self.variant_label = QLabel(label_text)
        self.variant_label.setObjectName("label_accent")
        self.variant_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.variant_label)

        # Asset badges
        badges_layout = QHBoxLayout()
        badges_layout.setSpacing(2)

        if variant.has_icon:
            badges_layout.addWidget(self._create_badge("IC", "#00DDFF"))
        if variant.has_hero:
            badges_layout.addWidget(self._create_badge("HR", "#C8B1FF"))
        if variant.has_logo:
            badges_layout.addWidget(self._create_badge("LG", "#FF6EC7"))

        badges_layout.addStretch()
        layout.addLayout(badges_layout)

        # Tooltip
        asset_list = []
        if variant.has_icon:
            asset_list.append("Icon")
        if variant.has_hero:
            asset_list.append("Hero")
        if variant.has_logo:
            asset_list.append("Logo")

        self.setToolTip(
            f"{variant.game_name}\n"
            f"Variant {variant.variant_number}\n"
            f"Assets: {', '.join(asset_list) if asset_list else 'None'}"
        )

    def _create_badge(self, text: str, color: str) -> QLabel:
        """Create a small badge label."""
        badge = QLabel(text)
        badge.setFixedSize(22, 16)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: #000;
                border-radius: 3px;
                font-size: 9px;
                font-weight: bold;
            }}
        """)
        return badge

    def _update_style(self):
        """Update style based on selection state using Qt property."""
        self.setProperty("selected", "true" if self._selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_preview(self, pixmap: QPixmap):
        """Set the preview image."""
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.preview_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)
        else:
            self.preview_label.setText("No Preview")

    def set_preview_error(self, error_text: str):
        """Set error message on preview."""
        self.preview_label.setText(error_text)

    def update_badges(self):
        """Update badges after variant assets are scanned."""
        # Find the badges layout (it's the last layout in the main layout)
        main_layout = self.layout()
        badges_layout = None
        for i in range(main_layout.count()):
            item = main_layout.itemAt(i)
            if item.layout() is not None:
                badges_layout = item.layout()

        if not badges_layout:
            return

        # Clear existing badges
        while badges_layout.count() > 0:
            item = badges_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add badges based on scanned assets
        if self.variant.has_icon:
            badges_layout.addWidget(self._create_badge("IC", "#00DDFF"))
        if self.variant.has_hero:
            badges_layout.addWidget(self._create_badge("HR", "#C8B1FF"))
        if self.variant.has_logo:
            badges_layout.addWidget(self._create_badge("LG", "#FF6EC7"))

        badges_layout.addStretch()

        # Update tooltip
        asset_list = []
        if self.variant.has_icon:
            asset_list.append("Icon")
        if self.variant.has_hero:
            asset_list.append("Hero")
        if self.variant.has_logo:
            asset_list.append("Logo")

        self.setToolTip(
            f"{self.variant.game_name}\n"
            f"Variant {self.variant.variant_number}\n"
            f"Assets: {', '.join(asset_list) if asset_list else 'None'}"
        )

    def set_selected(self, selected: bool):
        """Set selection state."""
        self._selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        """Handle click to select."""
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.variant)
        super().mousePressEvent(event)


class GameFolderSelectDialog(QDialog):
    """Dialog to select a game folder to save assets to."""

    # Default iiSU Launcher assets path
    IISU_DEFAULT_PATH = "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"

    def __init__(self, output_dir: Path, platform: str, suggested_name: str = "", parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self.suggested_platform = platform
        self.selected_path: Optional[Path] = None
        self.push_to_device = False
        self.device_path = ""
        self.adb_path = get_adb_path()

        self.setWindowTitle("Select Game Folder")
        self.setMinimumSize(500, 600)
        self.setModal(True)

        self._setup_ui(suggested_name)
        self._scan_library()
        self._check_adb()

    def _setup_ui(self, suggested_name: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Select a game to save assets to:")
        header.setObjectName("label_header")
        layout.addWidget(header)

        desc = QLabel("Choose an existing game from your library, or create a new folder.")
        desc.setObjectName("label_muted")
        layout.addWidget(desc)

        # Search/filter
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Type to filter games...")
        self.filter_input.textChanged.connect(self._filter_games)
        search_row.addWidget(self.filter_input)
        layout.addLayout(search_row)

        # Game list
        self.game_tree = QTreeWidget()
        self.game_tree.setHeaderLabels(["Platform / Game", "Has Assets"])
        self.game_tree.setColumnWidth(0, 350)
        self.game_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.game_tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.game_tree, 1)

        # Create new folder section
        new_frame = QFrame()
        new_frame.setObjectName("card")
        new_layout = QVBoxLayout(new_frame)

        new_header = QLabel("Or create a new game folder:")
        new_header.setObjectName("label_header")
        new_layout.addWidget(new_header)

        create_row = QHBoxLayout()

        self.platform_combo = QComboBox()
        self.platform_combo.setMinimumWidth(120)
        # Add common platforms
        platforms = [
            "3DS", "Arcade", "DS", "Dreamcast", "FDS", "GameCube", "GB", "GBA",
            "GBC", "GG", "MD", "MS", "N64", "NES", "NGP", "PC", "PCE", "PS1",
            "PS2", "PSP", "Saturn", "SNES", "Wii", "WiiU"
        ]
        for p in platforms:
            self.platform_combo.addItem(p)
        # Try to select the suggested platform
        idx = self.platform_combo.findText(self.suggested_platform)
        if idx >= 0:
            self.platform_combo.setCurrentIndex(idx)
        create_row.addWidget(self.platform_combo)

        self.new_game_input = QLineEdit()
        self.new_game_input.setPlaceholderText("New game folder name...")
        if suggested_name:
            self.new_game_input.setText(suggested_name)
        create_row.addWidget(self.new_game_input, 1)

        self.create_btn = QPushButton("Create && Select")
        self.create_btn.clicked.connect(self._create_new_folder)
        create_row.addWidget(self.create_btn)

        new_layout.addLayout(create_row)
        layout.addWidget(new_frame)

        # Selected path display
        self.selected_label = QLabel("No folder selected")
        self.selected_label.setObjectName("label_muted")
        layout.addWidget(self.selected_label)

        # ADB Device Push section (primary action)
        device_frame = QFrame()
        device_frame.setObjectName("card")
        device_layout = QVBoxLayout(device_frame)

        device_header = QLabel("Push to Android Device (ADB)")
        device_header.setObjectName("label_header")
        device_layout.addWidget(device_header)

        self.device_checkbox = QCheckBox("Push assets to connected Android device")
        self.device_checkbox.setToolTip("Push the downloaded assets directly to your iiSU Launcher on device")
        self.device_checkbox.toggled.connect(self._on_device_checkbox_toggled)
        device_layout.addWidget(self.device_checkbox)

        device_path_row = QHBoxLayout()
        device_path_row.addWidget(QLabel("Device Path:"))
        self.device_path_input = QLineEdit(self.IISU_DEFAULT_PATH)
        self.device_path_input.setPlaceholderText(self.IISU_DEFAULT_PATH)
        self.device_path_input.setEnabled(False)
        device_path_row.addWidget(self.device_path_input, 1)
        device_layout.addLayout(device_path_row)

        self.device_status_label = QLabel("")
        self.device_status_label.setObjectName("label_muted")
        device_layout.addWidget(self.device_status_label)

        layout.addWidget(device_frame)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.select_btn = QPushButton("Download && Push to Device")
        self.select_btn.setObjectName("btn_primary")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.select_btn)

        self.local_only_btn = QPushButton("Save to Local Only")
        self.local_only_btn.setObjectName("btn_secondary")
        self.local_only_btn.setEnabled(False)
        self.local_only_btn.clicked.connect(self._accept_local_only)
        button_layout.addWidget(self.local_only_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _scan_library(self):
        """Scan the output directory for existing games."""
        self.game_tree.clear()
        self._all_items = []

        if not self.output_dir.exists():
            return

        for platform_folder in sorted(self.output_dir.iterdir()):
            if not platform_folder.is_dir():
                continue

            platform_item = QTreeWidgetItem([platform_folder.name, ""])
            platform_item.setData(0, Qt.UserRole, None)  # Platform items aren't selectable

            game_count = 0
            for game_folder in sorted(platform_folder.iterdir()):
                if not game_folder.is_dir():
                    continue

                # Check existing assets
                has_icon = (game_folder / "icon.png").exists()
                has_hero = any((game_folder / f"hero_{i}.png").exists() for i in range(1, 10))

                status = ""
                if has_icon and has_hero:
                    status = "✓ Full"
                elif has_icon:
                    status = "✓ Icon"
                elif has_hero:
                    status = "✓ Hero"

                game_item = QTreeWidgetItem([game_folder.name, status])
                game_item.setData(0, Qt.UserRole, game_folder)
                if status:
                    game_item.setForeground(1, Qt.green)
                platform_item.addChild(game_item)
                self._all_items.append((game_item, game_folder.name.lower()))
                game_count += 1

            if game_count > 0:
                platform_item.setText(0, f"{platform_folder.name} ({game_count})")
                self.game_tree.addTopLevelItem(platform_item)

                # Expand the suggested platform
                if platform_folder.name == self.suggested_platform:
                    platform_item.setExpanded(True)

    def _filter_games(self, text: str):
        """Filter games by search text."""
        search = text.lower().strip()

        for i in range(self.game_tree.topLevelItemCount()):
            platform_item = self.game_tree.topLevelItem(i)
            visible_children = 0

            for j in range(platform_item.childCount()):
                game_item = platform_item.child(j)
                game_name = game_item.text(0).lower()
                visible = not search or search in game_name
                game_item.setHidden(not visible)
                if visible:
                    visible_children += 1

            platform_item.setHidden(visible_children == 0)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click."""
        path = item.data(0, Qt.UserRole)
        if path:
            self.selected_path = path
            self.selected_label.setText(f"Selected: {path}")
            self.selected_label.setStyleSheet("color: #4CAF50;")
            self.select_btn.setEnabled(True)
            self.local_only_btn.setEnabled(True)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle double-click to select and close."""
        path = item.data(0, Qt.UserRole)
        if path:
            self.selected_path = path
            self.accept()

    def _create_new_folder(self):
        """Create a new game folder."""
        platform = self.platform_combo.currentText()
        game_name = self.new_game_input.text().strip()

        if not game_name:
            QMessageBox.warning(self, "Error", "Please enter a game name.")
            return

        # Sanitize folder name
        safe_name = "".join(c for c in game_name if c.isalnum() or c in " -_().").strip()
        if not safe_name:
            QMessageBox.warning(self, "Error", "Invalid game name.")
            return

        new_path = self.output_dir / platform / safe_name
        try:
            new_path.mkdir(parents=True, exist_ok=True)
            self.selected_path = new_path
            self.selected_label.setText(f"Created: {new_path}")
            self.selected_label.setStyleSheet("color: #4CAF50;")
            self.select_btn.setEnabled(True)
            self.local_only_btn.setEnabled(True)
            # Refresh the tree
            self._scan_library()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create folder:\n{e}")

    def _check_adb(self):
        """Check if ADB is available and device is connected."""
        self._has_device = False

        if not self.adb_path:
            self.device_checkbox.setEnabled(False)
            self.device_status_label.setText("ADB not found. Install Android SDK Platform Tools.")
            self.device_status_label.setStyleSheet("color: #E53935;")
            # No device: hide push button, make local button primary
            self.select_btn.setVisible(False)
            self.local_only_btn.setObjectName("btn_primary")
            self.local_only_btn.style().unpolish(self.local_only_btn)
            self.local_only_btn.style().polish(self.local_only_btn)
            return

        try:
            kwargs = get_subprocess_kwargs()
            result = subprocess.run(
                [self.adb_path, "devices"],
                timeout=10, **kwargs
            )
            lines = result.stdout.strip().split('\n')[1:]
            devices = [l.split('\t')[0] for l in lines if '\tdevice' in l]

            if devices:
                self._has_device = True
                self.device_checkbox.setEnabled(True)
                self.device_checkbox.setChecked(True)  # Auto-enable push
                self.device_path_input.setEnabled(True)
                self.device_status_label.setText(f"Device connected: {devices[0]}")
                self.device_status_label.setStyleSheet("color: #4CAF50;")
            else:
                self.device_checkbox.setEnabled(False)
                self.device_status_label.setText("No Android device connected")
                self.device_status_label.setStyleSheet("color: #FFB300;")
                # No device: hide push button, make local button primary
                self.select_btn.setVisible(False)
                self.local_only_btn.setObjectName("btn_primary")
                self.local_only_btn.style().unpolish(self.local_only_btn)
                self.local_only_btn.style().polish(self.local_only_btn)
        except Exception as e:
            self.device_checkbox.setEnabled(False)
            self.device_status_label.setText(f"ADB error: {str(e)[:50]}")
            self.device_status_label.setStyleSheet("color: #E53935;")
            self.select_btn.setVisible(False)
            self.local_only_btn.setObjectName("btn_primary")
            self.local_only_btn.style().unpolish(self.local_only_btn)
            self.local_only_btn.style().polish(self.local_only_btn)

    def _on_device_checkbox_toggled(self, checked: bool):
        """Handle device checkbox toggle."""
        self.device_path_input.setEnabled(checked)

    def _accept_local_only(self):
        """Accept dialog for local-only download (no device push)."""
        self.device_checkbox.setChecked(False)
        self.accept()

    def get_selected_path(self) -> Optional[Path]:
        """Get the selected game folder path."""
        return self.selected_path

    def get_push_to_device(self) -> bool:
        """Check if user wants to push to device."""
        return self.device_checkbox.isChecked()

    def get_device_path(self) -> str:
        """Get the device path for pushing."""
        return self.device_path_input.text().strip()


class AssetPreviewPopup(QDialog):
    """
    Dialog showing visual previews of all assets in a variant.
    Displays icon, hero(s), logo, and screenshot(s) in a tabbed/grid layout.
    """

    def __init__(self, variant: ThemedAssetVariant, db: IisuAssetDBLocal, parent=None):
        super().__init__(parent)
        self.variant = variant
        self.db = db
        self._image_cache: Dict[str, QPixmap] = {}

        self.setWindowTitle(f"Asset Preview - {variant.game_name}")
        self.setMinimumSize(700, 550)
        self.setModal(True)

        self._setup_ui()
        self._load_all_assets()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(f"{self.variant.game_name}")
        header.setObjectName("label_header")
        layout.addWidget(header)

        variant_label = QLabel(f"Variant {self.variant.variant_number} • {self.variant.platform}")
        variant_label.setObjectName("label_muted")
        layout.addWidget(variant_label)

        # Tab widget for different asset types
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("asset_preview_tabs")

        # Create tabs for each asset type
        self._create_asset_type_tab("Icon", AssetType.ICON, (256, 256))
        self._create_asset_type_tab("Hero", AssetType.HERO, (460, 215))
        self._create_asset_type_tab("Logo", AssetType.LOGO, (300, 180))

        layout.addWidget(self.tab_widget, 1)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _create_asset_type_tab(self, label: str, asset_type: AssetType, preview_size: tuple):
        """Create a preview tab for an asset type."""
        widget = QWidget()
        tab_layout = QVBoxLayout(widget)

        asset = self.variant.get_asset(asset_type)
        if asset:
            preview = QLabel()
            preview.setObjectName("asset_preview_frame")
            preview.setFixedSize(preview_size[0], preview_size[1])
            preview.setAlignment(Qt.AlignCenter)
            preview.setText("Loading...")
            tab_layout.addWidget(preview, 0, Qt.AlignCenter)

            info = QLabel(asset.filename)
            info.setObjectName("label_muted")
            info.setAlignment(Qt.AlignCenter)
            tab_layout.addWidget(info)

            # Store references for loading
            setattr(self, f"{asset_type.value}_preview", preview)
            setattr(self, f"{asset_type.value}_info", info)
        else:
            no_asset = QLabel(f"No {label.lower()} in this variant")
            no_asset.setObjectName("label_muted")
            no_asset.setAlignment(Qt.AlignCenter)
            tab_layout.addWidget(no_asset)

        tab_layout.addStretch()
        self.tab_widget.addTab(widget, label)

    def _load_all_assets(self):
        """Load all asset previews in background threads."""
        for asset_type, max_size in [(AssetType.ICON, 256), (AssetType.HERO, 460), (AssetType.LOGO, 300)]:
            asset = self.variant.get_asset(asset_type)
            preview = getattr(self, f"{asset_type.value}_preview", None)
            info = getattr(self, f"{asset_type.value}_info", None)
            if asset and preview:
                self._load_asset_preview(asset, preview, info, max_size=max_size)

    def _load_asset_preview(self, asset, preview_label: QLabel, info_label: Optional[QLabel], max_size: int):
        """Load a single asset preview in a background thread."""
        def load_thread():
            try:
                # Use the preview URL which is more reliable than download URL
                preview_url = asset.get_preview_url(width=max_size)
                response = self.db.session.get(preview_url, timeout=30)

                # If the direct URL fails, try the thumbnail URL as fallback
                if response.status_code != 200 or 'image' not in response.headers.get('Content-Type', ''):
                    preview_url = asset.get_thumbnail_url(width=max_size)
                    response = self.db.session.get(preview_url, timeout=30)

                # Last resort: try the download URL with confirmation handling
                if response.status_code != 200 or 'image' not in response.headers.get('Content-Type', ''):
                    response = self.db.session.get(asset.download_url, timeout=30)
                    if 'text/html' in response.headers.get('Content-Type', ''):
                        confirm_token = None
                        for key, value in response.cookies.items():
                            if key.startswith('download_warning'):
                                confirm_token = value
                                break
                        if confirm_token:
                            response = self.db.session.get(
                                asset.download_url + f"&confirm={confirm_token}",
                                timeout=30
                            )

                if response.status_code == 200:
                    image_data = response.content
                    # Verify it's actually image data, not an HTML error page
                    content_type = response.headers.get('Content-Type', '')
                    if 'image' in content_type or len(image_data) > 100 and image_data[:4] in [b'\x89PNG', b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1', b'\xff\xd8\xff\xdb', b'GIF8', b'RIFF']:
                        # Use QTimer to update UI from main thread
                        # Capture variables explicitly using default argument values
                        fname = asset.filename
                        QTimer.singleShot(0, lambda data=image_data, lbl=preview_label, info=info_label, fn=fname, ms=max_size:
                            self._set_preview_image(lbl, info, data, fn, ms)
                        )
                    else:
                        QTimer.singleShot(0, lambda lbl=preview_label: lbl.setText("Invalid image"))
                else:
                    status = response.status_code
                    QTimer.singleShot(0, lambda lbl=preview_label, s=status: lbl.setText(f"HTTP {s}"))
            except Exception as e:
                print(f"Error loading preview: {e}")
                error_msg = str(e)[:30]
                QTimer.singleShot(0, lambda lbl=preview_label, msg=error_msg: lbl.setText(f"Error: {msg}"))

        thread = threading.Thread(target=load_thread)
        thread.daemon = True
        thread.start()

    def _set_preview_image(self, preview_label: QLabel, info_label: Optional[QLabel],
                           image_data: bytes, filename: str, max_size: int):
        """Set the preview image on the label (must be called from main thread)."""
        try:
            image = QImage()
            image.loadFromData(image_data)
            pixmap = QPixmap.fromImage(image)

            if not pixmap.isNull():
                # Scale to fit while maintaining aspect ratio
                scaled = pixmap.scaled(
                    max_size, max_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                preview_label.setPixmap(scaled)

                # Update info label with dimensions
                if info_label:
                    info_label.setText(f"{filename} ({pixmap.width()} x {pixmap.height()})")
            else:
                preview_label.setText("Failed to load")
        except Exception as e:
            preview_label.setText(f"Error: {str(e)[:30]}")


class GameDetailDialogSignals(QObject):
    """Signals for GameDetailDialog background operations."""
    variants_scanned = Signal(list)  # List of scanned variants
    preview_loaded = Signal(str, bytes)  # key, image_data
    preview_error = Signal(str, str)  # key, error message


class GameDetailDialog(QDialog):
    """
    Dialog showing all variants for a game with per-asset-type variant selection.
    Users can mix and match: pick icon from variant 1, hero from variant 2, etc.
    """

    def __init__(self, game: ThemedGame, db: IisuAssetDBLocal, parent=None):
        super().__init__(parent)
        self.game = game
        self.db = db
        self._scanned_variants: List[ThemedAssetVariant] = []
        self._preview_widgets: Dict[str, QLabel] = {}
        # Per-type variant selection: {AssetType: variant_index}
        self._type_selections: Dict[AssetType, int] = {}
        # Per-type combos for mix & match
        self._type_combos: Dict[AssetType, QComboBox] = {}

        self._signals = GameDetailDialogSignals()
        self._signals.variants_scanned.connect(self._on_variants_scanned)
        self._signals.preview_loaded.connect(self._on_preview_loaded)
        self._signals.preview_error.connect(self._on_preview_error)

        self.setWindowTitle(f"{game.game_name} - iiSU Workshop")
        self.setMinimumSize(850, 650)
        self.setModal(True)

        self._setup_ui()
        self._scan_and_load_variants()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        header = QLabel(f"{self.game.game_name}")
        header.setObjectName("label_header")
        header_layout.addWidget(header)

        platform_label = QLabel(f"Platform: {self.game.platform}")
        platform_label.setObjectName("label_muted")
        header_layout.addWidget(platform_label)
        header_layout.addStretch()

        self.variants_label = QLabel(f"Available Variants ({self.game.variant_count})")
        self.variants_label.setObjectName("label_accent")
        header_layout.addWidget(self.variants_label)

        layout.addLayout(header_layout)

        # Tab widget for asset types
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("asset_tabs")

        self.icon_tab = self._create_asset_tab("Icons")
        self.hero_tab = self._create_asset_tab("Heroes")
        self.logo_tab = self._create_asset_tab("Logos")

        self.tab_widget.addTab(self.icon_tab, "Icons")
        self.tab_widget.addTab(self.hero_tab, "Heroes")
        self.tab_widget.addTab(self.logo_tab, "Logos")

        layout.addWidget(self.tab_widget, 1)

        # Loading indicator
        self.loading_label = QLabel("Loading variants...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setObjectName("label_warning")
        layout.addWidget(self.loading_label)

        # Mix & match selection panel
        self.select_frame = QFrame()
        self.select_frame.setObjectName("card")
        self.select_frame.setVisible(False)
        select_main = QVBoxLayout(self.select_frame)
        select_main.setSpacing(8)

        select_header = QLabel("Mix && Match — choose a variant for each asset type:")
        select_header.setObjectName("label_header")
        select_main.addWidget(select_header)

        select_grid = QGridLayout()
        select_grid.setSpacing(8)

        for row, (asset_type, label_text) in enumerate([
            (AssetType.ICON, "Icon:"),
            (AssetType.HERO, "Hero:"),
            (AssetType.LOGO, "Logo:"),
        ]):
            lbl = QLabel(label_text)
            lbl.setObjectName("label_header")
            select_grid.addWidget(lbl, row, 0)

            combo = QComboBox()
            combo.setMinimumWidth(200)
            combo.setProperty("asset_type", asset_type.value)
            combo.currentIndexChanged.connect(
                lambda idx, at=asset_type: self._on_type_combo_changed(at, idx)
            )
            select_grid.addWidget(combo, row, 1)
            self._type_combos[asset_type] = combo

            status = QLabel("")
            status.setObjectName(f"status_{asset_type.value}")
            select_grid.addWidget(status, row, 2)

        select_grid.setColumnStretch(1, 1)
        select_main.addLayout(select_grid)

        layout.addWidget(self.select_frame)

        # Buttons
        button_layout = QHBoxLayout()

        self.download_btn = QPushButton("Download && Replace")
        self.download_btn.setObjectName("btn_primary")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download)
        button_layout.addWidget(self.download_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _create_asset_tab(self, asset_type: str) -> QScrollArea:
        """Create a scrollable tab for an asset type."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content = QWidget()
        content.setObjectName(f"{asset_type.lower()}_content")
        layout = QHBoxLayout(content)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setAlignment(Qt.AlignLeft)

        scroll.setWidget(content)
        return scroll

    def _scan_and_load_variants(self):
        """Scan all variants and load their assets in background."""
        signals = self._signals

        def scan_all():
            scanned = []
            for variant in self.game.variants:
                try:
                    scanned_variant = self.db.get_variant_with_assets(variant)
                    scanned.append(scanned_variant)
                except Exception as e:
                    print(f"Error scanning variant {variant.folder_name}: {e}")
                    scanned.append(variant)
            signals.variants_scanned.emit(scanned)

        thread = threading.Thread(target=scan_all)
        thread.daemon = True
        thread.start()

    def _on_variants_scanned(self, scanned_variants: List[ThemedAssetVariant]):
        """Called when all variants have been scanned."""
        self._scanned_variants = scanned_variants
        self.loading_label.setVisible(False)
        self.select_frame.setVisible(True)

        # Populate per-type combos
        for asset_type, combo in self._type_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("None (skip)", None)

            first_with_assets = -1
            for i, variant in enumerate(scanned_variants):
                v_label = f"Variant {variant.variant_number}" if variant.variant_number > 1 else "Original"
                # Check if this variant has this asset type
                has = variant.get_asset(asset_type) is not None
                count_str = ""

                if has:
                    combo.addItem(f"{v_label}{count_str}", i)
                    if first_with_assets < 0:
                        first_with_assets = combo.count() - 1
                else:
                    combo.addItem(f"{v_label} — no assets", i)
                    item_idx = combo.count() - 1
                    combo.model().item(item_idx).setEnabled(False)

            # Default to first variant that has assets
            if first_with_assets >= 0:
                combo.setCurrentIndex(first_with_assets)
                variant_idx = combo.itemData(first_with_assets)
                self._type_selections[asset_type] = variant_idx
            else:
                combo.setCurrentIndex(0)

            combo.blockSignals(False)

        if scanned_variants:
            self.download_btn.setEnabled(True)

        self._populate_asset_tabs()
        self._update_status_labels()

    def _on_type_combo_changed(self, asset_type: AssetType, combo_index: int):
        """Handle per-type variant combo change."""
        combo = self._type_combos[asset_type]
        variant_idx = combo.itemData(combo_index)
        if variant_idx is not None:
            self._type_selections[asset_type] = variant_idx
        else:
            self._type_selections.pop(asset_type, None)
        self._update_status_labels()

    def _update_status_labels(self):
        """Update the status labels next to each combo."""
        for asset_type, combo in self._type_combos.items():
            status = self.select_frame.findChild(QLabel, f"status_{asset_type.value}")
            if not status:
                continue
            if asset_type in self._type_selections:
                idx = self._type_selections[asset_type]
                variant = self._scanned_variants[idx]
                assets = [variant.get_asset(asset_type)] if variant.get_asset(asset_type) else []
                assets = [a for a in assets if a]
                if assets:
                    status.setText(f"{len(assets)} file(s)")
                    status.setStyleSheet("color: #4CAF50;")
                else:
                    status.setText("No files")
                    status.setStyleSheet("color: #808080;")
            else:
                status.setText("Skipped")
                status.setStyleSheet("color: #808080;")

    def _populate_asset_tabs(self):
        """Populate all asset tabs with variant columns."""
        for tab, asset_type in [(self.icon_tab, AssetType.ICON), (self.hero_tab, AssetType.HERO), (self.logo_tab, AssetType.LOGO)]:
            content = tab.widget()
            layout = content.layout()

            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            for variant in self._scanned_variants:
                column = self._create_variant_column(variant, asset_type)
                layout.addWidget(column)

            layout.addStretch()

    def _create_variant_column(self, variant: ThemedAssetVariant, asset_type: AssetType) -> QFrame:
        """Create a column showing assets of one type for one variant."""
        column = QFrame()
        column.setObjectName("variant_card")
        column.setMinimumWidth(180)
        column.setMaximumWidth(300)

        layout = QVBoxLayout(column)
        layout.setSpacing(8)

        header_text = f"Variant {variant.variant_number}" if variant.variant_number > 1 else "Original"
        header = QLabel(header_text)
        header.setObjectName("label_accent")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        assets = variant.get_assets(asset_type)
        # Adjust preview size based on asset type
        if asset_type == AssetType.HERO:
            preview_size = (250, 117)  # ~920x430 aspect ratio
        elif asset_type == AssetType.LOGO:
            preview_size = (200, 120)  # Logo aspect varies
        else:
            preview_size = (150, 150)

        if not assets:
            no_asset = QLabel("No assets")
            no_asset.setObjectName("label_muted")
            no_asset.setAlignment(Qt.AlignCenter)
            layout.addWidget(no_asset)
        else:
            for asset in assets:
                preview_frame = QFrame()
                preview_frame.setObjectName("workshop_card_preview")
                preview_layout = QVBoxLayout(preview_frame)
                preview_layout.setContentsMargins(4, 4, 4, 4)

                preview = QLabel()
                preview.setFixedSize(preview_size[0], preview_size[1])
                preview.setAlignment(Qt.AlignCenter)
                preview.setText("Loading...")
                preview_layout.addWidget(preview)

                filename_label = QLabel(asset.filename)
                filename_label.setObjectName("label_muted")
                filename_label.setAlignment(Qt.AlignCenter)
                preview_layout.addWidget(filename_label)

                layout.addWidget(preview_frame)

                key = f"{variant.variant_number}_{asset.filename}"
                self._preview_widgets[key] = preview
                self._queue_preview_load(asset, key, max(preview_size))

        layout.addStretch()
        return column

    def _queue_preview_load(self, asset, key: str, max_size: int):
        """Queue a preview load instead of spawning a thread immediately."""
        if not hasattr(self, '_preview_load_queue'):
            self._preview_load_queue = []
            self._preview_active_loaders = 0
            self._preview_max_loaders = 3  # Conservative limit for dialog
        self._preview_load_queue.append((asset, key, max_size))
        self._start_next_preview_load()

    def _start_next_preview_load(self):
        """Start the next queued preview load if under concurrency limit."""
        if not hasattr(self, '_preview_load_queue'):
            return
        while self._preview_active_loaders < self._preview_max_loaders and self._preview_load_queue:
            asset, key, max_size = self._preview_load_queue.pop(0)
            self._preview_active_loaders += 1
            self._load_single_preview(asset, key, max_size)

    def _load_single_preview(self, asset, key: str, max_size: int):
        """Load a single asset preview in background thread."""
        signals = self._signals
        db_session = self.db.session

        def load():
            try:
                preview_url = asset.get_preview_url(width=max_size)
                response = db_session.get(preview_url, timeout=10)

                if response.status_code != 200 or 'image' not in response.headers.get('Content-Type', ''):
                    preview_url = asset.get_thumbnail_url(width=max_size)
                    response = db_session.get(preview_url, timeout=10)

                if response.status_code != 200 or 'image' not in response.headers.get('Content-Type', ''):
                    response = db_session.get(asset.download_url, timeout=10)

                if response.status_code == 200:
                    image_data = response.content
                    if len(image_data) > 4 and image_data[:4] in [b'\x89PNG', b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1', b'\xff\xd8\xff\xdb', b'GIF8', b'RIFF']:
                        signals.preview_loaded.emit(key, image_data)
                    else:
                        signals.preview_error.emit(key, "Invalid")
                else:
                    signals.preview_error.emit(key, f"HTTP {response.status_code}")
            except Exception as e:
                print(f"Error loading {key}: {e}")
                signals.preview_error.emit(key, "Error")

        thread = threading.Thread(target=load)
        thread.daemon = True
        thread.start()

    def _on_preview_loaded(self, key: str, image_data: bytes):
        """Handle preview loaded signal (called on main thread)."""
        # Decrement active loaders and start next queued load
        if hasattr(self, '_preview_active_loaders'):
            self._preview_active_loaders = max(0, self._preview_active_loaders - 1)
            self._start_next_preview_load()

        if key not in self._preview_widgets:
            return
        label = self._preview_widgets[key]
        try:
            image = QImage()
            image.loadFromData(image_data)
            pixmap = QPixmap.fromImage(image)
            scaled = pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(scaled)
        except Exception:
            label.setText("Failed")

    def _on_preview_error(self, key: str, error: str):
        """Handle preview error signal (called on main thread)."""
        # Decrement active loaders and start next queued load
        if hasattr(self, '_preview_active_loaders'):
            self._preview_active_loaders = max(0, self._preview_active_loaders - 1)
            self._start_next_preview_load()

        if key in self._preview_widgets:
            self._preview_widgets[key].setText(error)

    def _on_download(self):
        """Handle download button click."""
        # Must have at least one asset type selected
        if self._type_selections:
            self.accept()
        else:
            QMessageBox.warning(self, "Nothing Selected",
                                "Please select at least one asset type to download.")

    def get_mixed_selections(self) -> Dict[AssetType, ThemedAssetVariant]:
        """Get the per-type variant selections for download."""
        result = {}
        for asset_type, variant_idx in self._type_selections.items():
            if 0 <= variant_idx < len(self._scanned_variants):
                result[asset_type] = self._scanned_variants[variant_idx]
        return result

    def get_game_name(self) -> str:
        return self.game.game_name

    def get_platform(self) -> str:
        return self.game.platform


class UploadDialog(QDialog):
    """Dialog for uploading assets to the community database."""

    def __init__(self, db: IisuAssetDBLocal, platforms: List[str], parent=None):
        super().__init__(parent)
        self.db = db
        self.platforms = platforms
        self._selected_file: Optional[Path] = None

        self.setWindowTitle("Upload to iiSU Workshop")
        self.setMinimumSize(500, 400)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Upload Asset")
        header.setObjectName("label_header")
        layout.addWidget(header)

        desc = QLabel("Share your assets on the iiSU Workshop!")
        desc.setObjectName("label_muted")
        layout.addWidget(desc)

        # File selection
        file_frame = QFrame()
        file_frame.setObjectName("card")
        file_layout = QVBoxLayout(file_frame)

        file_row = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("label_muted")
        file_row.addWidget(self.file_label, 1)

        self.file_btn = QPushButton("Browse...")
        self.file_btn.clicked.connect(self._browse_file)
        file_row.addWidget(self.file_btn)
        file_layout.addLayout(file_row)

        # Preview
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(200, 200)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setObjectName("variant_preview")
        file_layout.addWidget(self.preview_label, 0, Qt.AlignCenter)

        layout.addWidget(file_frame)

        # Game info
        form_frame = QFrame()
        form_frame.setObjectName("card")
        form_layout = QVBoxLayout(form_frame)

        # Game name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Game Name:"))
        self.game_name_input = QLineEdit()
        self.game_name_input.setPlaceholderText("e.g., Super Mario World")
        name_row.addWidget(self.game_name_input, 1)
        form_layout.addLayout(name_row)

        # Platform
        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Platform:"))
        self.platform_combo = QComboBox()
        for p in self.platforms:
            self.platform_combo.addItem(p)
        platform_row.addWidget(self.platform_combo, 1)
        form_layout.addLayout(platform_row)

        # Asset type
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Asset Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["icon", "hero", "logo"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        type_row.addWidget(self.type_combo, 1)
        form_layout.addLayout(type_row)

        # Variant number
        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel("Variant:"))
        self.variant_spin = QComboBox()
        self.variant_spin.addItems([str(i) for i in range(1, 11)])
        variant_row.addWidget(self.variant_spin, 1)
        form_layout.addLayout(variant_row)

        layout.addWidget(form_frame)

        # Upload button and status
        self.upload_status = QLabel("")
        self.upload_status.setObjectName("label_muted")
        layout.addWidget(self.upload_status)

        self.upload_progress = QProgressBar()
        self.upload_progress.setRange(0, 0)
        self.upload_progress.setVisible(False)
        layout.addWidget(self.upload_progress)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.upload_btn = QPushButton("Upload")
        self.upload_btn.setObjectName("btn_primary")
        self.upload_btn.setEnabled(False)
        self.upload_btn.clicked.connect(self._do_upload)
        button_layout.addWidget(self.upload_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _on_type_changed(self, asset_type: str):
        """Adjust preview size when asset type changes."""
        if asset_type == "hero":
            self.preview_label.setFixedSize(320, 180)
        elif asset_type == "logo":
            self.preview_label.setFixedSize(260, 150)
        else:
            self.preview_label.setFixedSize(200, 200)

        # Re-render preview if file is selected
        if self._selected_file and self._selected_file.exists():
            pixmap = QPixmap(str(self._selected_file))
            if not pixmap.isNull():
                w, h = self.preview_label.width(), self.preview_label.height()
                scaled = pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview_label.setPixmap(scaled)

    def _browse_file(self):
        """Open file dialog to select an asset file."""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Asset File", "",
            "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)"
        )
        if file_path:
            self._selected_file = Path(file_path)
            self.file_label.setText(self._selected_file.name)
            self.upload_btn.setEnabled(True)

            # Show preview (size depends on current asset type)
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                w, h = self.preview_label.width(), self.preview_label.height()
                scaled = pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview_label.setPixmap(scaled)

    def _do_upload(self):
        """Upload the selected asset."""
        if not self._selected_file:
            return

        game_name = self.game_name_input.text().strip()
        if not game_name:
            QMessageBox.warning(self, "Error", "Please enter a game name.")
            return

        platform = self.platform_combo.currentText()
        asset_type = self.type_combo.currentText()
        variant_number = int(self.variant_spin.currentText())

        self.upload_btn.setEnabled(False)
        self.upload_status.setText("Uploading...")
        self.upload_status.setStyleSheet("color: #FFB300;")
        self.upload_progress.setVisible(True)

        db = self.db
        file_path = self._selected_file

        def upload_thread():
            try:
                result = db.upload_asset(
                    file_path=file_path,
                    game_name=game_name,
                    platform=platform,
                    asset_type=asset_type,
                    variant_number=variant_number
                )

                QTimer.singleShot(0, lambda r=result: self._on_upload_complete(r))
            except Exception as e:
                QTimer.singleShot(0, lambda err=str(e): self._on_upload_error(err))

        thread = threading.Thread(target=upload_thread)
        thread.daemon = True
        thread.start()

    def _on_upload_complete(self, result: dict):
        """Handle upload completion."""
        self.upload_progress.setVisible(False)
        self.upload_btn.setEnabled(True)

        if result.get('success'):
            self.upload_status.setText("Upload successful!")
            self.upload_status.setStyleSheet("color: #8FFFB1;")
            QMessageBox.information(self, "Upload Complete", result.get('message', 'Asset uploaded successfully!'))
            self.accept()
        else:
            self.upload_status.setText(f"Upload failed: {result.get('message', 'Unknown error')}")
            self.upload_status.setStyleSheet("color: #ff6464;")

    def _on_upload_error(self, error: str):
        """Handle upload error."""
        self.upload_progress.setVisible(False)
        self.upload_btn.setEnabled(True)
        self.upload_status.setText(f"Error: {error}")
        self.upload_status.setStyleSheet("color: #ff6464;")


class AssetDBTab(QWidget):
    """
    Tab for browsing the iiSU Workshop.
    """

    # Default iiSU Workshop server URL
    DEFAULT_SERVER_URL = "https://assets.iisu.community"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.config_path = str(get_config_path())
        self.db: Optional[IisuAssetDBLocal] = None
        self._load_config()

        # Create signals for thread communication
        self._signals = WorkerSignals()
        self._signals.connected.connect(self._on_connected)
        self._signals.connect_error.connect(self._on_connect_error)
        self._signals.refreshed.connect(self._on_refresh_complete)
        self._signals.image_loaded.connect(self._on_image_loaded)
        self._signals.download_progress.connect(self._on_download_progress)
        self._signals.download_complete.connect(self._on_download_complete)
        self._signals.download_error.connect(self._on_download_error)
        self._signals.device_push_progress.connect(self._on_device_push_progress)
        self._signals.device_push_complete.connect(self._on_device_push_complete)
        self._signals.device_push_error.connect(self._on_device_push_error)

        # Device push settings (from download dialog)
        self._pending_device_push = False
        self._device_push_path = ""
        self._device_push_platform = ""
        self._device_push_game_name = ""

        # Track preview labels for image loading
        self._preview_labels: Dict[str, QLabel] = {}

        # Image loading thread pool (limit concurrent loads)
        self._image_load_queue: List[Tuple] = []
        self._active_loaders = 0
        self._max_loaders = 4  # Limit concurrent image loads

        self._setup_ui()

        # Auto-connect if configured
        if self.server_url:
            QTimer.singleShot(500, self._connect_to_db)

    def _load_config(self):
        """Load database config."""
        self.server_url = self.DEFAULT_SERVER_URL
        self.output_dir = Path("./output")

        try:
            cfg = get_config()

            db_cfg = cfg.get("iisu_asset_db", {})
            self.server_url = db_cfg.get("server_url", "") or self.DEFAULT_SERVER_URL

            # Load output directory from paths config
            self.output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception as e:
            print(f"Error loading config: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Header card ──────────────────────────────────────────────
        header_card = QFrame()
        header_card.setObjectName("workshop_header")
        header_outer = QHBoxLayout(header_card)
        header_outer.setContentsMargins(16, 14, 16, 14)
        header_outer.setSpacing(16)

        # Workshop logo image (left side)
        logo_label = QLabel()
        workshop_logo_path = str(get_workshop_logo_path())
        logo_pixmap = QPixmap(workshop_logo_path)
        if logo_pixmap.isNull():
            # Fallback to main app logo
            logo_pixmap = QPixmap(str(get_logo_path()))
        if not logo_pixmap.isNull():
            logo_label.setPixmap(logo_pixmap.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo_label.setFixedSize(52, 52)
        header_outer.addWidget(logo_label)

        # Title + desc + badges (center)
        header_text = QVBoxLayout()
        header_text.setSpacing(4)

        # Title row (title + stats)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = GradientLabel("iiSU Workshop")
        title.setFont(QFont("Continuum Bold", 20))
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setMinimumHeight(28)
        title_row.addWidget(title)

        self.stats_label = QLabel("Not connected")
        self.stats_label.setObjectName("workshop_card_badge")
        title_row.addWidget(self.stats_label)
        title_row.addStretch()
        header_text.addLayout(title_row)

        desc = QLabel("Browse and download community icons, covers, and borders for iiSU Launcher.")
        desc.setObjectName("workshop_card_badge")
        header_text.addWidget(desc)

        # Feature badges row
        badges_row = QHBoxLayout()
        badges_row.setSpacing(6)
        for badge_text, badge_color in [
            ("Icons", "#00DDFF"),
            ("Heroes", "#C8B1FF"),
            ("Logos", "#FF6EC7"),
            ("Variants", "#8FFFB1"),
        ]:
            badge = QLabel(badge_text)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedHeight(20)
            badge.setStyleSheet(
                f"background: rgba({QColor(badge_color).red()},{QColor(badge_color).green()},{QColor(badge_color).blue()},0.12);"
                f"color: {badge_color};"
                f"border: 1px solid rgba({QColor(badge_color).red()},{QColor(badge_color).green()},{QColor(badge_color).blue()},0.3);"
                f"border-radius: 10px;"
                f"padding: 0 10px;"
                f"font-size: 10px;"
                f"font-weight: bold;"
            )
            badges_row.addWidget(badge)
        badges_row.addStretch()
        header_text.addLayout(badges_row)

        header_outer.addLayout(header_text, 1)

        # Action buttons (right side, stacked vertically)
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(6)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("btn_secondary")
        self.refresh_btn.clicked.connect(self._refresh_db)
        self.refresh_btn.setEnabled(False)
        btn_layout.addWidget(self.refresh_btn)

        self.upload_btn = QPushButton("Upload")
        self.upload_btn.setObjectName("btn_primary")
        self.upload_btn.clicked.connect(self._show_upload_dialog)
        self.upload_btn.setEnabled(False)
        btn_layout.addWidget(self.upload_btn)

        header_outer.addLayout(btn_layout)

        layout.addWidget(header_card)

        # ── Compact connection card (single row) ─────────────────────
        self.connect_card = QFrame()
        self.connect_card.setObjectName("header_card")
        connect_layout = QHBoxLayout(self.connect_card)
        connect_layout.setContentsMargins(10, 8, 10, 8)

        connect_label = QLabel("Server:")
        connect_layout.addWidget(connect_label)

        self.server_input = QLineEdit(self.server_url)
        self.server_input.setPlaceholderText("https://assets.iisu.community")
        connect_layout.addWidget(self.server_input, 1)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("btn_primary")
        self.connect_btn.clicked.connect(self._connect_to_db)
        connect_layout.addWidget(self.connect_btn)

        self.connect_status = QLabel("")
        connect_layout.addWidget(self.connect_status)

        self.connect_progress = QProgressBar()
        self.connect_progress.setRange(0, 0)  # Indeterminate
        self.connect_progress.setVisible(False)
        self.connect_progress.setMaximumWidth(120)
        connect_layout.addWidget(self.connect_progress)

        layout.addWidget(self.connect_card)

        # ── Filter bar (platform dropdown + source + search) ─────────
        self.filter_bar = QFrame()
        self.filter_bar.setObjectName("header_card")
        self.filter_bar.setVisible(False)
        filter_layout = QHBoxLayout(self.filter_bar)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        filter_layout.setSpacing(10)

        # Source filter (labelled)
        source_group = QVBoxLayout()
        source_group.setSpacing(2)
        source_label = QLabel("SOURCE")
        source_label.setObjectName("filter_label")
        source_group.addWidget(source_label)
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("filter_combo")
        self.source_combo.setMinimumWidth(140)
        self.source_combo.addItem("All", "all")
        self.source_combo.addItem("Official (iiSU)", "official")
        self.source_combo.addItem("Community", "community")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        source_group.addWidget(self.source_combo)
        filter_layout.addLayout(source_group)

        # Platform filter (labelled)
        platform_group = QVBoxLayout()
        platform_group.setSpacing(2)
        platform_label = QLabel("PLATFORM")
        platform_label.setObjectName("filter_label")
        platform_group.addWidget(platform_label)
        self.platform_combo = QComboBox()
        self.platform_combo.setObjectName("filter_combo")
        self.platform_combo.setMinimumWidth(180)
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        platform_group.addWidget(self.platform_combo)
        filter_layout.addLayout(platform_group)

        # Search input
        search_group = QVBoxLayout()
        search_group.setSpacing(2)
        search_label = QLabel("SEARCH")
        search_label.setObjectName("filter_label")
        search_group.addWidget(search_label)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search games...")
        self.search_input.textChanged.connect(self._filter_games)
        search_group.addWidget(self.search_input)
        filter_layout.addLayout(search_group, 1)

        self.game_count_label = QLabel("")
        self.game_count_label.setObjectName("workshop_card_badge")
        filter_layout.addWidget(self.game_count_label, 0, Qt.AlignBottom)

        layout.addWidget(self.filter_bar)

        # ── Games grid in scroll area (full width, no splitter) ──────
        self.games_scroll = QScrollArea()
        self.games_scroll.setWidgetResizable(True)
        self.games_scroll.setVisible(False)

        self.games_widget = QWidget()
        self.games_layout = FlowLayout(self.games_widget, margin=6, spacing=12)

        self.games_scroll.setWidget(self.games_widget)
        layout.addWidget(self.games_scroll, 1)

        # ── Status bar ───────────────────────────────────────────────
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("workshop_card_badge")
        layout.addWidget(self.status_label)

    def _connect_to_db(self):
        """Connect to the Workshop server."""
        server_url = self.server_input.text().strip()
        if not server_url:
            server_url = self.DEFAULT_SERVER_URL

        self.connect_status.setText("Connecting to iiSU Workshop...")
        self.connect_status.setStyleSheet("color: #FFB300;")
        self.connect_btn.setEnabled(False)
        self.connect_progress.setVisible(True)

        signals = self._signals

        def scan_thread():
            try:
                self.db = IisuAssetDBLocal(server_url)
                if not self.db.is_server_available():
                    signals.connect_error.emit("iiSU Workshop server unreachable")
                    return
                success = self.db.scan()
                signals.connected.emit(success)
            except Exception as e:
                signals.connect_error.emit(str(e))

        thread = threading.Thread(target=scan_thread)
        thread.daemon = True
        thread.start()

    def _on_connected(self, success: bool):
        """Handle successful connection."""
        self.connect_btn.setEnabled(True)
        self.connect_progress.setVisible(False)

        if success and self.db:
            stats = self.db.get_stats()

            self.connect_status.setText("Connected!")
            self.connect_status.setStyleSheet("color: #4CAF50;")

            self.stats_label.setText(
                f"{stats['platforms']} platforms • {stats['total_games']} games • "
                f"{stats['total_variants']} variants"
            )

            self.connect_card.setVisible(False)
            self.filter_bar.setVisible(True)
            self.games_scroll.setVisible(True)
            self.refresh_btn.setEnabled(True)
            self.upload_btn.setEnabled(True)

            self._populate_platforms()

            # Save config
            self._save_config()
        else:
            self.connect_status.setText("Failed to scan database")
            self.connect_status.setStyleSheet("color: #E53935;")

    def _on_connect_error(self, error: str):
        """Handle connection error."""
        self.connect_btn.setEnabled(True)
        self.connect_progress.setVisible(False)
        self.connect_status.setText(f"Error: {error}")
        self.connect_status.setStyleSheet("color: #E53935;")

    def _save_config(self):
        """Save database config."""
        try:
            cfg_path = Path(self.config_path)
            cfg = {}
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}

            if "iisu_asset_db" not in cfg:
                cfg["iisu_asset_db"] = {}

            cfg["iisu_asset_db"]["server_url"] = self.server_input.text().strip()
            cfg["iisu_asset_db"]["enabled"] = True

            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False)
            invalidate_config_cache()

        except Exception as e:
            print(f"Error saving config: {e}")

    def _refresh_db(self):
        """Refresh the database."""
        if self.db:
            self.status_label.setText("Refreshing...")
            self.refresh_btn.setEnabled(False)

            signals = self._signals

            def refresh_thread():
                success = self.db.scan(force=True)
                signals.refreshed.emit(success)

            thread = threading.Thread(target=refresh_thread)
            thread.daemon = True
            thread.start()

    def _on_refresh_complete(self, success: bool):
        """Handle refresh complete."""
        self.refresh_btn.setEnabled(True)

        if success:
            stats = self.db.get_stats()
            self.stats_label.setText(
                f"{stats['platforms']} platforms • {stats['total_games']} games • "
                f"{stats['total_variants']} variants"
            )
            self._populate_platforms()
            self.status_label.setText("Database refreshed")
        else:
            self.status_label.setText("Refresh failed")

    def _populate_platforms(self):
        """Populate the platform dropdown."""
        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()

        if not self.db:
            self.platform_combo.blockSignals(False)
            return

        # Add "All Games" option
        self.platform_combo.addItem("All Games", None)

        # Add platforms (skip empty ones)
        for platform in self.db.get_platforms():
            games = self.db.get_games(platform)
            if not games:
                continue
            self.platform_combo.addItem(f"{platform} ({len(games)})", platform)

        # Add Android Apps if present
        apps = self.db.get_apps()
        if apps:
            self.platform_combo.addItem(f"Android Apps ({len(apps)})", "android_apps")

        self.platform_combo.blockSignals(False)

        # Default to "Android" platform if available, otherwise first item
        default_index = 0
        for i in range(self.platform_combo.count()):
            data = self.platform_combo.itemData(i)
            if isinstance(data, str) and data.lower().startswith("android"):
                default_index = i
                break

        if self.platform_combo.count() > 0:
            self.platform_combo.setCurrentIndex(default_index)
            self._on_platform_changed(default_index)

    def _on_platform_changed(self, index: int):
        """Handle platform dropdown selection."""
        platform = self.platform_combo.itemData(index)
        self._display_games(platform)

    def _on_source_changed(self, index: int):
        """Handle source filter (All/Official/Community) selection."""
        platform = self.platform_combo.currentData()
        self._display_games(platform)

    def _display_games(self, platform: Optional[str]):
        """Display games for a platform."""
        # Clear layout, preview label references, and image load queue
        self._preview_labels.clear()
        self._image_load_queue.clear()
        self._active_loaders = 0
        if hasattr(self, "_shimmer_labels"):
            self._shimmer_labels.clear()
        while self.games_layout.count():
            child = self.games_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self.db:
            return

        # Get games
        if platform == "android_apps":
            # TODO: Handle apps separately
            self.status_label.setText("Android apps view coming soon")
            return
        elif platform is None:
            # All games
            games = []
            for plat in self.db.get_platforms():
                games.extend(self.db.get_games(plat))
        else:
            games = self.db.get_games(platform)

        # Filter by source (official/community)
        source = self.source_combo.currentData() if hasattr(self, 'source_combo') else "all"
        if source == "official":
            games = [g for g in games if g.is_official]
        elif source == "community":
            games = [g for g in games if not g.is_official]

        # Filter by search
        search_text = self.search_input.text().strip().lower()
        if search_text:
            games = [g for g in games if search_text in g.game_name.lower()]

        # Add game cards in batches via QTimer to avoid blocking the UI
        self._pending_games = list(games)
        self._pending_total = len(games)
        self._batch_index = 0
        self.status_label.setText(f"Loading {self._pending_total} games...")
        self.game_count_label.setText(f"{self._pending_total} games")
        self._display_next_batch()

    def _display_next_batch(self, batch_size: int = 12):
        """Add the next batch of game cards, then yield to the event loop."""
        end = min(self._batch_index + batch_size, len(self._pending_games))
        for i in range(self._batch_index, end):
            card = self._create_game_card(self._pending_games[i])
            self.games_layout.addWidget(card)
        self._batch_index = end
        if self._batch_index < len(self._pending_games):
            # Small delay lets the UI process paint events between batches
            QTimer.singleShot(16, self._display_next_batch)
        else:
            self.status_label.setText(f"Showing {self._pending_total} games")
            self.game_count_label.setText(f"{self._pending_total} games")

    def _create_game_card(self, game: ThemedGame) -> QFrame:
        """Create a glass-styled card for a game."""
        card = QFrame()
        card.setObjectName("workshop_game_card")
        card.setFixedSize(160, 220)
        card.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Preview (load from first variant's icon)
        preview = QLabel()
        preview.setObjectName("workshop_card_preview")
        preview.setFixedSize(140, 140)
        preview.setAlignment(Qt.AlignCenter)
        layout.addWidget(preview)

        # Start shimmer placeholder animation
        self._start_shimmer(preview)

        # Queue preview loading - need to scan variant folder first to get assets
        if game.variants:
            first_variant = game.variants[0]
            preview_id = str(id(preview))
            preview.setProperty("preview_id", preview_id)
            self._preview_labels[preview_id] = preview

            # Add to load queue
            self._image_load_queue.append((preview_id, first_variant))
            # Start loader if not at max
            self._start_next_image_load()

        # Name label (word-wrapped, max 3 lines)
        name_label = QLabel(game.game_name)
        name_label.setObjectName("workshop_card_name")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(42)
        name_label.setToolTip(game.game_name)
        layout.addWidget(name_label)

        # Badge row: official + variants
        badge_row = QHBoxLayout()
        badge_row.setSpacing(4)
        badge_row.setContentsMargins(0, 0, 0, 0)

        if game.is_official:
            official_badge = QLabel("✓ Official")
            official_badge.setObjectName("workshop_badge_official")
            official_badge.setAlignment(Qt.AlignCenter)
            badge_row.addWidget(official_badge)

        if game.variant_count > 1:
            badge = QLabel(f"{game.variant_count} variants")
            badge.setObjectName("workshop_card_badge")
            badge.setAlignment(Qt.AlignCenter)
            badge_row.addWidget(badge)

        if game.is_official or game.variant_count > 1:
            badge_row.addStretch()
            layout.addLayout(badge_row)

        # Click handler
        card.mousePressEvent = lambda e, g=game: self._on_game_clicked(g)

        return card

    def _start_shimmer(self, label: QLabel):
        """Set a subtle static placeholder style on a preview label.

        Uses a single shared timer to pulse ALL pending labels at once,
        avoiding the per-label QTimer overhead that hammered the CPU.
        """
        label.setText("⋯")
        label.setProperty("shimmer_timer", True)  # Marker for _on_image_loaded

        # Register this label with the shared shimmer timer
        if not hasattr(self, "_shimmer_labels"):
            self._shimmer_labels = set()
            self._shimmer_offset = 0.0
            self._shimmer_timer = QTimer(self)
            self._shimmer_timer.timeout.connect(self._tick_shimmer)
        self._shimmer_labels.add(label)
        # Start the shared timer if not already running
        if not self._shimmer_timer.isActive():
            self._shimmer_timer.start(80)  # ~12 fps, shared across all labels

    def _tick_shimmer(self):
        """Single shared timer tick that updates all shimmer labels at once."""
        if not self._shimmer_labels:
            self._shimmer_timer.stop()
            return

        self._shimmer_offset = (self._shimmer_offset + 0.06) % 1.0
        o = self._shimmer_offset
        s1 = max(0.0, o - 0.15)
        s2 = o
        s3 = min(1.0, o + 0.15)
        style = (
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 rgba(255,255,255,0.03),"
            f"stop:{s1:.2f} rgba(255,255,255,0.03),"
            f"stop:{s2:.2f} rgba(255,255,255,0.09),"
            f"stop:{s3:.2f} rgba(255,255,255,0.03),"
            f"stop:1 rgba(255,255,255,0.03));"
            f"border: 1px solid rgba(255,255,255,0.06);"
            f"border-radius: 8px;"
        )
        # Apply once — all labels share the same gradient position
        for label in list(self._shimmer_labels):
            try:
                label.setStyleSheet(style)
            except RuntimeError:
                self._shimmer_labels.discard(label)

    def _start_next_image_load(self):
        """Start loading the next image in the queue if under the limit."""
        while self._active_loaders < self._max_loaders and self._image_load_queue:
            preview_id, variant = self._image_load_queue.pop(0)

            # Check if label still exists
            if preview_id not in self._preview_labels:
                continue

            self._active_loaders += 1
            db = self.db
            signals = self._signals

            def load_preview(pid=preview_id, var=variant):
                try:
                    # Scan the variant folder to get assets (on-demand loading)
                    scanned_variant = db.get_variant_with_assets(var)
                    icon_asset = scanned_variant.get_asset(AssetType.ICON)

                    if icon_asset:
                        # Use the preview URL which is more reliable than download URL
                        preview_url = icon_asset.get_preview_url(width=256)
                        response = db.session.get(preview_url, timeout=10)

                        # If the direct URL fails, try the thumbnail URL as fallback
                        if response.status_code != 200 or 'image' not in response.headers.get('Content-Type', ''):
                            preview_url = icon_asset.get_thumbnail_url(width=256)
                            response = db.session.get(preview_url, timeout=10)

                        # Last resort: try the download URL
                        if response.status_code != 200 or 'image' not in response.headers.get('Content-Type', ''):
                            response = db.session.get(icon_asset.download_url, timeout=10)

                        if response.status_code == 200:
                            # Send raw bytes - QPixmap must be created on main thread
                            signals.image_loaded.emit(pid, response.content)
                        else:
                            signals.image_loaded.emit(pid, b'')
                    else:
                        signals.image_loaded.emit(pid, b'')
                except Exception as e:
                    signals.image_loaded.emit(pid, b'')

            thread = threading.Thread(target=load_preview)
            thread.daemon = True
            thread.start()

    def _on_image_loaded(self, preview_id: str, image_data: bytes):
        """Handle image loaded from background thread."""
        self._active_loaders = max(0, self._active_loaders - 1)

        if preview_id in self._preview_labels:
            label = self._preview_labels[preview_id]
            try:
                # Remove from shared shimmer set
                if hasattr(self, "_shimmer_labels"):
                    self._shimmer_labels.discard(label)
                label.setProperty("shimmer_timer", None)
                label.setStyleSheet("")  # Reset to QSS-driven style
                label.setText("")

                if label and not label.isHidden() and image_data:
                    image = QImage()
                    image.loadFromData(image_data)
                    pixmap = QPixmap.fromImage(image)
                    scaled = pixmap.scaled(
                        label.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    label.setPixmap(scaled)
            except RuntimeError:
                pass  # Label was deleted

        # Clean up reference
        if preview_id in self._preview_labels:
            del self._preview_labels[preview_id]

        # Start next load
        self._start_next_image_load()

    def _filter_games(self, text: str):
        """Filter games by search text."""
        platform = self.platform_combo.currentData()
        self._display_games(platform)

    def _on_game_clicked(self, game: ThemedGame):
        """Handle game card click."""
        dialog = GameDetailDialog(game, self.db, self)

        if dialog.exec() == QDialog.Accepted:
            selections = dialog.get_mixed_selections()
            if selections:
                self._download_mixed_assets(
                    selections,
                    game_name=dialog.get_game_name(),
                    platform=dialog.get_platform()
                )

    def _show_upload_dialog(self):
        """Show the upload dialog."""
        if not self.db:
            return

        platforms = self.db.get_platforms()
        dialog = UploadDialog(self.db, platforms, self)
        if dialog.exec() == QDialog.Accepted:
            # Refresh the database after successful upload
            self._refresh_db()

    def _download_mixed_assets(self, selections: Dict[AssetType, ThemedAssetVariant],
                               game_name: str, platform: str):
        """Download assets from mixed variant selections to a game folder.

        Properly renames files:
          - Icon -> icon.png
        """
        # Show game folder selection dialog
        dialog = GameFolderSelectDialog(
            self.output_dir,
            platform=platform,
            suggested_name=game_name,
            parent=self
        )

        if dialog.exec() != QDialog.Accepted:
            return

        game_folder = dialog.get_selected_path()
        if not game_folder:
            return

        # Build the download list with proper filenames
        download_list: List[Tuple[str, str, str]] = []  # (download_url, target_filename, display_name)

        for asset_type, variant in selections.items():
            if asset_type == AssetType.ICON:
                asset = variant.get_asset(AssetType.ICON)
                if asset:
                    download_list.append((asset.download_url, "icon.png", "Icon"))
            elif asset_type == AssetType.HERO:
                asset = variant.get_asset(AssetType.HERO)
                if asset:
                    download_list.append((asset.download_url, "hero.png", "Hero"))
            elif asset_type == AssetType.LOGO:
                asset = variant.get_asset(AssetType.LOGO)
                if asset:
                    download_list.append((asset.download_url, "logo.png", "Logo"))

        if not download_list:
            QMessageBox.warning(self, "Nothing to Download", "No assets found in the selected variants.")
            return

        # Check for existing files
        existing = [fn for _, fn, _ in download_list if (game_folder / fn).exists()]
        if existing:
            reply = QMessageBox.question(
                self, "Overwrite Assets?",
                f"This folder already has some assets:\n{', '.join(existing[:5])}"
                + (f"\n...and {len(existing) - 5} more" if len(existing) > 5 else "")
                + "\n\nOverwrite existing files?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # Store device push settings
        push_to_device = dialog.get_push_to_device()
        self._pending_device_push = push_to_device
        self._device_push_path = dialog.get_device_path()
        self._device_push_platform = platform
        self._device_push_game_name = game_name

        self.status_label.setText(f"Downloading assets for {game_name}...")

        signals = self._signals

        def download_all():
            try:
                total = len(download_list)
                for i, (url, filename, display) in enumerate(download_list):
                    signals.download_progress.emit(i + 1, total, display)

                    response = requests.get(url, timeout=30)
                    response.raise_for_status()

                    target_path = game_folder / filename
                    with open(target_path, 'wb') as f:
                        f.write(response.content)

                signals.download_complete.emit(str(game_folder))

            except Exception as e:
                signals.download_error.emit(str(e))

        thread = threading.Thread(target=download_all)
        thread.daemon = True
        thread.start()

    def _on_download_progress(self, current: int, total: int, filename: str):
        """Handle download progress update."""
        self.status_label.setText(f"Downloading {current}/{total}: {filename}")
        self.status_label.setStyleSheet("color: #FFB300;")

    def _on_download_complete(self, game_folder: str):
        """Handle download complete."""
        game_name = Path(game_folder).name

        # Check if we need to push to device
        if self._pending_device_push:
            self._pending_device_push = False
            self._push_to_device(game_folder)
            return

        self.status_label.setText(f"Downloaded assets to: {game_name}")
        self.status_label.setStyleSheet("color: #4CAF50;")

        QMessageBox.information(
            self, "Download Complete",
            f"Assets downloaded successfully!\n\n"
            f"Game: {game_name}\n"
            f"Location: {game_folder}"
        )

    def _push_to_device(self, game_folder: str):
        """Push downloaded assets to Android device via ADB."""
        adb_path = get_adb_path()
        if not adb_path:
            self.status_label.setText("ADB not found - assets saved locally only")
            self.status_label.setStyleSheet("color: #FFB300;")
            QMessageBox.warning(
                self, "ADB Not Found",
                f"Assets downloaded locally but could not push to device.\n"
                f"ADB is not installed.\n\n"
                f"Location: {game_folder}"
            )
            return

        # Build device target path
        device_base = self._device_push_path.rstrip("/")
        platform = self._device_push_platform
        game_name = self._device_push_game_name

        # Sanitize game name for device path
        safe_game_name = "".join(c for c in game_name if c.isalnum() or c in " -_().").strip()
        device_game_path = f"{device_base}/{platform}/{safe_game_name}"

        self.status_label.setText(f"Pushing to device: {safe_game_name}...")
        self.status_label.setStyleSheet("color: #FFB300;")

        signals = self._signals
        local_folder = Path(game_folder)

        def push_all():
            try:
                # Create directory on device first
                kwargs = get_subprocess_kwargs()
                subprocess.run(
                    [adb_path, "shell", f'mkdir -p "{device_game_path}"'],
                    timeout=30, **kwargs
                )

                # Get list of files to push
                files = [f for f in local_folder.iterdir() if f.is_file()]
                total = len(files)
                pushed = 0
                errors = 0

                for i, file_path in enumerate(files):
                    signals.device_push_progress.emit(i + 1, total, file_path.name)

                    try:
                        result = subprocess.run(
                            [adb_path, "push", str(file_path), f"{device_game_path}/{file_path.name}"],
                            timeout=60, **kwargs
                        )
                        if result.returncode == 0:
                            pushed += 1
                        else:
                            errors += 1
                            print(f"[DEBUG] Push failed for {file_path.name}: {result.stderr}")
                    except Exception as e:
                        errors += 1
                        print(f"[DEBUG] Push exception for {file_path.name}: {e}")

                signals.device_push_complete.emit(pushed, errors)

            except Exception as e:
                signals.device_push_error.emit(str(e))

        thread = threading.Thread(target=push_all)
        thread.daemon = True
        thread.start()

    def _on_device_push_progress(self, current: int, total: int, filename: str):
        """Handle device push progress update."""
        self.status_label.setText(f"Pushing to device {current}/{total}: {filename}")
        self.status_label.setStyleSheet("color: #FFB300;")

    def _on_device_push_complete(self, pushed: int, errors: int):
        """Handle device push complete."""
        if errors == 0:
            self.status_label.setText(f"Pushed {pushed} files to device")
            self.status_label.setStyleSheet("color: #4CAF50;")
            QMessageBox.information(
                self, "Push Complete",
                f"Successfully pushed {pushed} files to device!\n\n"
                f"Platform: {self._device_push_platform}\n"
                f"Game: {self._device_push_game_name}"
            )
        else:
            self.status_label.setText(f"Pushed {pushed} files, {errors} errors")
            self.status_label.setStyleSheet("color: #FFB300;")
            QMessageBox.warning(
                self, "Push Complete with Errors",
                f"Pushed {pushed} files to device.\n"
                f"{errors} files failed to push.\n\n"
                f"Platform: {self._device_push_platform}\n"
                f"Game: {self._device_push_game_name}"
            )

    def _on_device_push_error(self, error: str):
        """Handle device push error."""
        self.status_label.setText(f"Device push failed: {error}")
        self.status_label.setStyleSheet("color: #E53935;")
        QMessageBox.critical(
            self, "Push Failed",
            f"Could not push assets to device:\n{error}"
        )

    def _on_download_error(self, error: str):
        """Handle download error."""
        self.status_label.setText(f"Download failed: {error}")
        self.status_label.setStyleSheet("color: #E53935;")

        QMessageBox.critical(
            self, "Download Failed",
            f"Could not download assets:\n{error}"
        )
