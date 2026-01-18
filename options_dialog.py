"""
Options Dialog for Icon Generator
Handles configuration with categorized tabs and full settings persistence
"""
import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QFileDialog,
    QGroupBox, QDialogButtonBox, QMessageBox, QScrollArea, QWidget,
    QComboBox, QCheckBox, QListWidget, QListWidgetItem, QTabWidget
)

from source_priority_widget import SourcePriorityWidget
from api_key_manager import get_manager
from rom_parser import get_available_drives, find_iisu_directory
from device_asset_dialog import DeviceAssetDialog


class OptionsDialog(QDialog):
    """Options dialog for configuring Icon Generator settings with categorized tabs."""

    def __init__(self, parent=None, config_path="", workers=8, limit=0, source_priority_widget=None,
                 rom_directory_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(700)
        self.setMinimumHeight(650)

        # Store initial values
        self.config_path_value = config_path
        self.workers_value = workers
        self.limit_value = limit
        self.source_priority_widget_ref = source_priority_widget

        # ROM directory settings
        self.rom_directory_settings = rom_directory_settings or {
            "mode": "manual",
            "rom_path": "",
            "auto_detect": False,
            "remember_last_path": True
        }

        # Hero image settings
        self.hero_settings = {
            "enabled": True,
            "count": 1,
            "save_with_icons": True
        }

        # Fallback icon settings
        self.fallback_settings = {
            "use_platform_icon_fallback": False,
            "skip_scraping_use_platform_icon": False
        }

        # Screenshot settings
        self.screenshot_settings = {
            "enabled": False,
            "count": 3
        }

        # Device copy settings
        self.device_settings = {
            "enabled": False,
            "path": "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"
        }

        # Logo/Title settings
        self.logo_settings = {
            "scrape_logos": True,
            "fallback_to_boxart": True
        }

        # Export format settings
        self.export_settings = {
            "format": "PNG",
            "jpeg_quality": 95
        }

        # Custom border settings
        self.custom_border_settings = {
            "enabled": False,
            "path": "",
            "per_platform": {}
        }

        # Custom platforms
        self.custom_platforms = {}

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Create tab widget for categories
        self.tab_widget = QTabWidget()

        # Create tabs
        self.tab_widget.addTab(self._create_general_tab(), "General")
        self.tab_widget.addTab(self._create_sources_tab(), "Sources")
        self.tab_widget.addTab(self._create_output_tab(), "Output")
        self.tab_widget.addTab(self._create_processing_tab(), "Processing")
        self.tab_widget.addTab(self._create_platforms_tab(), "Platforms")

        layout.addWidget(self.tab_widget, 1)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._apply_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _create_general_tab(self):
        """Create the General settings tab (API Keys, ROM Directory, Config)."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)

        # API Keys Group
        api_group = QGroupBox("API Keys")
        api_layout = QFormLayout()
        api_layout.setSpacing(10)

        key_manager = get_manager()

        # SteamGridDB API Key
        self.sgdb_key = QLineEdit()
        self.sgdb_key.setPlaceholderText("Enter SteamGridDB API key")
        self.sgdb_key.setEchoMode(QLineEdit.Password)
        current_sgdb = key_manager.get_key("steamgriddb")
        if current_sgdb:
            self.sgdb_key.setText(current_sgdb)
        sgdb_row = QHBoxLayout()
        sgdb_row.addWidget(self.sgdb_key, 1)
        btn_sgdb_show = QPushButton("Show")
        btn_sgdb_show.setMaximumWidth(60)
        btn_sgdb_show.clicked.connect(lambda: self._toggle_password_visibility(self.sgdb_key))
        sgdb_row.addWidget(btn_sgdb_show)
        api_layout.addRow("SteamGridDB:", sgdb_row)

        sgdb_help = QLabel('<a href="https://www.steamgriddb.com/profile/preferences/api">Get API key</a>')
        sgdb_help.setOpenExternalLinks(True)
        sgdb_help.setStyleSheet("color: #00DDFF; font-size: 10px;")
        api_layout.addRow("", sgdb_help)

        # IGDB API Keys
        self.igdb_client_id = QLineEdit()
        self.igdb_client_id.setPlaceholderText("Enter IGDB Client ID")
        self.igdb_client_id.setEchoMode(QLineEdit.Password)
        current_igdb_id = key_manager.get_key("igdb_client_id")
        if current_igdb_id:
            self.igdb_client_id.setText(current_igdb_id)
        igdb_id_row = QHBoxLayout()
        igdb_id_row.addWidget(self.igdb_client_id, 1)
        btn_igdb_id_show = QPushButton("Show")
        btn_igdb_id_show.setMaximumWidth(60)
        btn_igdb_id_show.clicked.connect(lambda: self._toggle_password_visibility(self.igdb_client_id))
        igdb_id_row.addWidget(btn_igdb_id_show)
        api_layout.addRow("IGDB Client ID:", igdb_id_row)

        self.igdb_client_secret = QLineEdit()
        self.igdb_client_secret.setPlaceholderText("Enter IGDB Client Secret")
        self.igdb_client_secret.setEchoMode(QLineEdit.Password)
        current_igdb_secret = key_manager.get_key("igdb_client_secret")
        if current_igdb_secret:
            self.igdb_client_secret.setText(current_igdb_secret)
        igdb_secret_row = QHBoxLayout()
        igdb_secret_row.addWidget(self.igdb_client_secret, 1)
        btn_igdb_secret_show = QPushButton("Show")
        btn_igdb_secret_show.setMaximumWidth(60)
        btn_igdb_secret_show.clicked.connect(lambda: self._toggle_password_visibility(self.igdb_client_secret))
        igdb_secret_row.addWidget(btn_igdb_secret_show)
        api_layout.addRow("IGDB Secret:", igdb_secret_row)

        igdb_help = QLabel('<a href="https://api-docs.igdb.com/#account-creation">Get IGDB credentials</a>')
        igdb_help.setOpenExternalLinks(True)
        igdb_help.setStyleSheet("color: #00DDFF; font-size: 10px;")
        api_layout.addRow("", igdb_help)

        tgdb_note = QLabel("TheGamesDB: Using built-in API key")
        tgdb_note.setStyleSheet("color: #4CAF50; font-size: 11px;")
        api_layout.addRow(tgdb_note)

        api_group.setLayout(api_layout)
        scroll_layout.addWidget(api_group)

        # ROM Directory Group
        rom_group = QGroupBox("ROM Directory")
        rom_layout = QFormLayout()
        rom_layout.setSpacing(10)

        rom_path_row = QHBoxLayout()
        self.rom_path = QLineEdit(self.rom_directory_settings.get("rom_path", ""))
        self.rom_path.setPlaceholderText("Browse to select your ROM folder...")
        rom_path_row.addWidget(self.rom_path, 1)
        btn_browse_rom = QPushButton("Browse...")
        btn_browse_rom.clicked.connect(self._browse_rom_path)
        rom_path_row.addWidget(btn_browse_rom)
        rom_layout.addRow("ROM Folder:", rom_path_row)

        drives = get_available_drives()
        if drives:
            drives_text = ", ".join([d[1] for d in drives[:6]])
            if len(drives) > 6:
                drives_text += f" (+{len(drives) - 6} more)"
            drives_label = QLabel(f"<span style='color: #888; font-size: 10px;'>Drives: {drives_text}</span>")
            rom_layout.addRow("", drives_label)

        auto_detect_row = QHBoxLayout()
        btn_auto_detect = QPushButton("Search for ROM Folders")
        btn_auto_detect.clicked.connect(self._auto_detect_rom_folder)
        auto_detect_row.addWidget(btn_auto_detect)
        auto_detect_row.addStretch()
        rom_layout.addRow("", auto_detect_row)

        self.remember_rom_path = QCheckBox("Remember selected folder")
        self.remember_rom_path.setChecked(self.rom_directory_settings.get("remember_last_path", True))
        rom_layout.addRow("", self.remember_rom_path)

        rom_group.setLayout(rom_layout)
        scroll_layout.addWidget(rom_group)

        # Config File Group
        config_group = QGroupBox("Configuration File")
        config_layout = QFormLayout()
        config_layout.setSpacing(10)

        config_row = QHBoxLayout()
        self.config_path = QLineEdit(self.config_path_value)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_config)
        config_row.addWidget(self.config_path, 1)
        config_row.addWidget(btn_browse)
        config_layout.addRow("Config File:", config_row)

        config_group.setLayout(config_layout)
        scroll_layout.addWidget(config_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        return tab

    def _create_sources_tab(self):
        """Create the Sources settings tab (Priority, Hero, Screenshots, Logos)."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)

        # Source Priority Group
        source_group = QGroupBox("Artwork Source Priority")
        source_layout = QVBoxLayout()
        source_layout.setSpacing(8)

        self.source_priority = SourcePriorityWidget()
        if self.source_priority_widget_ref:
            current_order = self.source_priority_widget_ref.get_source_order()
            self.source_priority.set_source_order(current_order)

        source_layout.addWidget(QLabel("Drag to reorder priority:"))
        source_layout.addWidget(self.source_priority)

        source_group.setLayout(source_layout)
        scroll_layout.addWidget(source_group)

        # Hero Images Group
        hero_group = QGroupBox("Hero Images")
        hero_layout = QFormLayout()
        hero_layout.setSpacing(10)

        self.hero_enabled = QCheckBox("Download hero images")
        self.hero_enabled.setChecked(self.hero_settings.get("enabled", True))
        self.hero_enabled.setToolTip("Download hero/banner images from SteamGridDB")
        hero_layout.addRow("", self.hero_enabled)

        self.hero_count = QSpinBox()
        self.hero_count.setRange(1, 5)
        self.hero_count.setValue(self.hero_settings.get("count", 1))
        hero_layout.addRow("Count per game:", self.hero_count)

        self.hero_save_with_icons = QCheckBox("Save in same folder as icons")
        self.hero_save_with_icons.setChecked(self.hero_settings.get("save_with_icons", True))
        hero_layout.addRow("", self.hero_save_with_icons)

        hero_group.setLayout(hero_layout)
        scroll_layout.addWidget(hero_group)

        # Screenshots Group
        screenshot_group = QGroupBox("Screenshots")
        screenshot_layout = QFormLayout()
        screenshot_layout.setSpacing(10)

        self.screenshot_enabled = QCheckBox("Download screenshots")
        self.screenshot_enabled.setChecked(self.screenshot_settings.get("enabled", False))
        screenshot_layout.addRow("", self.screenshot_enabled)

        self.screenshot_count = QSpinBox()
        self.screenshot_count.setRange(1, 10)
        self.screenshot_count.setValue(self.screenshot_settings.get("count", 3))
        screenshot_layout.addRow("Count per game:", self.screenshot_count)

        screenshot_group.setLayout(screenshot_layout)
        scroll_layout.addWidget(screenshot_group)

        # Logo/Title Group
        logo_group = QGroupBox("Title Image (title.png)")
        logo_layout = QFormLayout()
        logo_layout.setSpacing(10)

        self.scrape_logos = QCheckBox("Scrape game logos")
        self.scrape_logos.setChecked(self.logo_settings.get("scrape_logos", True))
        logo_layout.addRow("", self.scrape_logos)

        self.logo_fallback_boxart = QCheckBox("Fall back to boxart if no logo found")
        self.logo_fallback_boxart.setChecked(self.logo_settings.get("fallback_to_boxart", True))
        logo_layout.addRow("", self.logo_fallback_boxart)

        logo_group.setLayout(logo_layout)
        scroll_layout.addWidget(logo_group)

        # Fallback Icons Group
        fallback_group = QGroupBox("Fallback Icons")
        fallback_layout = QFormLayout()
        fallback_layout.setSpacing(10)

        self.use_fallback = QCheckBox("Use platform icon when artwork not found")
        self.use_fallback.setChecked(self.fallback_settings.get("use_platform_icon_fallback", False))
        fallback_layout.addRow("", self.use_fallback)

        self.skip_scraping = QCheckBox("Skip scraping - always use platform icon")
        self.skip_scraping.setChecked(self.fallback_settings.get("skip_scraping_use_platform_icon", False))
        self.skip_scraping.toggled.connect(self._on_skip_scraping_changed)
        fallback_layout.addRow("", self.skip_scraping)

        fallback_path_row = QHBoxLayout()
        self.fallback_icons_path = QLineEdit()
        self.fallback_icons_path.setPlaceholderText("Default: fallback_icons folder")
        fallback_path_row.addWidget(self.fallback_icons_path, 1)
        btn_browse_fallback = QPushButton("Browse...")
        btn_browse_fallback.clicked.connect(self._browse_fallback_icons)
        fallback_path_row.addWidget(btn_browse_fallback)
        fallback_layout.addRow("Fallback Folder:", fallback_path_row)

        fallback_group.setLayout(fallback_layout)
        scroll_layout.addWidget(fallback_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        return tab

    def _create_output_tab(self):
        """Create the Output settings tab (Export Format, Device Copy, Borders)."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)

        # Export Format Group
        export_group = QGroupBox("Export Format")
        export_layout = QFormLayout()
        export_layout.setSpacing(10)

        self.export_format = QComboBox()
        self.export_format.addItems(["JPEG", "PNG"])
        self.export_format.setCurrentText(self.export_settings.get("format", "JPEG"))
        self.export_format.currentTextChanged.connect(self._on_export_format_changed)
        export_layout.addRow("Image Format:", self.export_format)

        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(1, 100)
        self.jpeg_quality.setValue(self.export_settings.get("jpeg_quality", 95))
        export_layout.addRow("JPEG Quality:", self.jpeg_quality)

        export_note = QLabel("<span style='color: #888; font-size: 10px;'>JPEG recommended for iiSU Launcher</span>")
        export_layout.addRow(export_note)

        export_group.setLayout(export_layout)
        scroll_layout.addWidget(export_group)

        # Device Copy Group
        device_group = QGroupBox("Copy to Device (ADB)")
        device_layout = QFormLayout()
        device_layout.setSpacing(10)

        self.copy_to_device = QCheckBox("Auto-copy to Android device after processing")
        self.copy_to_device.setChecked(self.device_settings.get("enabled", False))
        device_layout.addRow("", self.copy_to_device)

        self.device_path = QLineEdit()
        self.device_path.setText(self.device_settings.get("path", "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"))
        device_layout.addRow("Device Path:", self.device_path)

        btn_manage_device = QPushButton("Manage Device Assets...")
        btn_manage_device.clicked.connect(self._open_device_asset_dialog)
        device_layout.addRow("", btn_manage_device)

        device_group.setLayout(device_layout)
        scroll_layout.addWidget(device_group)

        # Custom Border Group
        custom_border_group = QGroupBox("Custom Borders")
        custom_border_layout = QFormLayout()
        custom_border_layout.setSpacing(10)

        self.use_custom_border = QCheckBox("Use single custom border for ALL platforms")
        self.use_custom_border.setChecked(self.custom_border_settings.get("enabled", False))
        self.use_custom_border.toggled.connect(self._on_custom_border_toggled)
        custom_border_layout.addRow("", self.use_custom_border)

        custom_border_path_row = QHBoxLayout()
        self.custom_border_path = QLineEdit()
        self.custom_border_path.setPlaceholderText("Select a custom border image...")
        self.custom_border_path.setText(self.custom_border_settings.get("path", ""))
        custom_border_path_row.addWidget(self.custom_border_path, 1)
        self.btn_browse_custom_border = QPushButton("Browse...")
        self.btn_browse_custom_border.clicked.connect(self._browse_custom_border)
        custom_border_path_row.addWidget(self.btn_browse_custom_border)
        custom_border_layout.addRow("Global Border:", custom_border_path_row)

        self.custom_border_preview = QLabel()
        self.custom_border_preview.setFixedSize(96, 96)
        self.custom_border_preview.setStyleSheet("border: 2px solid #3A4048; border-radius: 8px; background: #1E2127;")
        self.custom_border_preview.setScaledContents(True)
        self._update_custom_border_preview()
        custom_border_layout.addRow("Preview:", self.custom_border_preview)

        # Per-platform borders
        per_platform_label = QLabel("<b>Per-Platform Borders</b>")
        custom_border_layout.addRow(per_platform_label)

        per_platform_row = QHBoxLayout()
        self.border_platform_combo = QComboBox()
        self.border_platform_combo.setMinimumWidth(150)
        self.border_platform_combo.currentIndexChanged.connect(self._on_border_platform_changed)
        per_platform_row.addWidget(self.border_platform_combo)

        self.per_platform_border_path = QLineEdit()
        self.per_platform_border_path.setPlaceholderText("Default (uses built-in)")
        per_platform_row.addWidget(self.per_platform_border_path, 1)

        self.btn_browse_per_platform_border = QPushButton("Browse...")
        self.btn_browse_per_platform_border.clicked.connect(self._browse_per_platform_border)
        per_platform_row.addWidget(self.btn_browse_per_platform_border)

        self.btn_clear_per_platform_border = QPushButton("Clear")
        self.btn_clear_per_platform_border.clicked.connect(self._clear_per_platform_border)
        per_platform_row.addWidget(self.btn_clear_per_platform_border)

        custom_border_layout.addRow("Platform:", per_platform_row)

        self.per_platform_border_preview = QLabel()
        self.per_platform_border_preview.setFixedSize(64, 64)
        self.per_platform_border_preview.setStyleSheet("border: 2px solid #3A4048; border-radius: 4px; background: #1E2127;")
        self.per_platform_border_preview.setScaledContents(True)
        custom_border_layout.addRow("", self.per_platform_border_preview)

        custom_border_group.setLayout(custom_border_layout)
        scroll_layout.addWidget(custom_border_group)

        self._on_custom_border_toggled(self.use_custom_border.isChecked())
        self._load_platforms_for_border_selector()

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        return tab

    def _create_processing_tab(self):
        """Create the Processing settings tab (Workers, Limits)."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)

        # Processing Group
        processing_group = QGroupBox("Processing Settings")
        processing_layout = QFormLayout()
        processing_layout.setSpacing(10)

        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
        self.workers.setValue(self.workers_value)
        self.workers.setToolTip("Number of concurrent workers for parallel processing")
        processing_layout.addRow("Workers:", self.workers)

        self.limit = QSpinBox()
        self.limit.setRange(0, 2_000_000_000)
        self.limit.setValue(self.limit_value)
        self.limit.setToolTip("Maximum games per platform (0 = unlimited)")
        processing_layout.addRow("Per-Platform Limit:", self.limit)

        processing_note = QLabel("<span style='color: #888; font-size: 10px;'>More workers = faster processing but more memory usage</span>")
        processing_note.setWordWrap(True)
        processing_layout.addRow(processing_note)

        processing_group.setLayout(processing_layout)
        scroll_layout.addWidget(processing_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        return tab

    def _create_platforms_tab(self):
        """Create the Custom Platforms settings tab."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)

        # Custom Platforms Group
        custom_platform_group = QGroupBox("Custom Platforms")
        custom_platform_layout = QVBoxLayout()
        custom_platform_layout.setSpacing(12)

        custom_platform_desc = QLabel(
            "Add custom platforms like Steam, older consoles, or obscure systems."
        )
        custom_platform_desc.setWordWrap(True)
        custom_platform_desc.setStyleSheet("color: #888; font-size: 11px;")
        custom_platform_layout.addWidget(custom_platform_desc)

        self.custom_platforms_list = QListWidget()
        self.custom_platforms_list.setMaximumHeight(120)
        self.custom_platforms_list.itemClicked.connect(self._on_custom_platform_selected)
        custom_platform_layout.addWidget(self.custom_platforms_list)

        platform_form = QFormLayout()
        platform_form.setSpacing(8)

        self.new_platform_key = QLineEdit()
        self.new_platform_key.setPlaceholderText("e.g., STEAM, ATARI_2600")
        platform_form.addRow("Platform Key:", self.new_platform_key)

        self.new_platform_name = QLineEdit()
        self.new_platform_name.setPlaceholderText("e.g., Steam, Atari 2600")
        platform_form.addRow("Display Name:", self.new_platform_name)

        self.new_platform_publisher = QLineEdit()
        self.new_platform_publisher.setPlaceholderText("e.g., Valve, Atari")
        platform_form.addRow("Publisher:", self.new_platform_publisher)

        self.new_platform_year = QSpinBox()
        self.new_platform_year.setRange(1970, 2030)
        self.new_platform_year.setValue(2000)
        platform_form.addRow("Year:", self.new_platform_year)

        self.new_platform_type = QComboBox()
        self.new_platform_type.addItems(["console", "handheld", "pc", "arcade", "mobile", "hybrid", "other"])
        platform_form.addRow("Type:", self.new_platform_type)

        border_row = QHBoxLayout()
        self.new_platform_border = QLineEdit()
        self.new_platform_border.setPlaceholderText("Select or leave blank...")
        border_row.addWidget(self.new_platform_border, 1)
        btn_browse_platform_border = QPushButton("Browse...")
        btn_browse_platform_border.clicked.connect(self._browse_new_platform_border)
        border_row.addWidget(btn_browse_platform_border)
        platform_form.addRow("Border File:", border_row)

        icon_row = QHBoxLayout()
        self.new_platform_icon = QLineEdit()
        self.new_platform_icon.setPlaceholderText("Select or leave blank...")
        icon_row.addWidget(self.new_platform_icon, 1)
        btn_browse_platform_icon = QPushButton("Browse...")
        btn_browse_platform_icon.clicked.connect(self._browse_new_platform_icon)
        icon_row.addWidget(btn_browse_platform_icon)
        platform_form.addRow("Platform Icon:", icon_row)

        custom_platform_layout.addLayout(platform_form)

        platform_btn_row = QHBoxLayout()
        self.btn_add_platform = QPushButton("Add Platform")
        self.btn_add_platform.clicked.connect(self._add_custom_platform)
        platform_btn_row.addWidget(self.btn_add_platform)

        self.btn_remove_platform = QPushButton("Remove Selected")
        self.btn_remove_platform.clicked.connect(self._remove_custom_platform)
        platform_btn_row.addWidget(self.btn_remove_platform)

        platform_btn_row.addStretch()
        custom_platform_layout.addLayout(platform_btn_row)

        custom_platform_group.setLayout(custom_platform_layout)
        scroll_layout.addWidget(custom_platform_group)

        self._load_custom_platforms_list()

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        return tab

    # --- Helper Methods ---

    def _browse_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Config File", str(Path.home()), "YAML (*.yaml *.yml)"
        )
        if path:
            self.config_path.setText(path)

    def _toggle_password_visibility(self, line_edit: QLineEdit):
        if line_edit.echoMode() == QLineEdit.Password:
            line_edit.setEchoMode(QLineEdit.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.Password)

    def _browse_rom_path(self):
        current_path = self.rom_path.text()
        start_dir = current_path if current_path and Path(current_path).exists() else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select ROM Directory", start_dir, QFileDialog.ShowDirsOnly)
        if path:
            self.rom_path.setText(path)

    def _auto_detect_rom_folder(self):
        QMessageBox.information(self, "Searching", "Searching for ROM folders...")
        found_path = find_iisu_directory()
        if found_path:
            self.rom_path.setText(str(found_path))
            QMessageBox.information(self, "Found", f"Found ROM directory at:\n{found_path}")
        else:
            QMessageBox.information(self, "Not Found", "No ROM directories found. Use Browse to select manually.")

    def _on_skip_scraping_changed(self, checked: bool):
        if checked:
            self.use_fallback.setChecked(False)
            self.use_fallback.setEnabled(False)
        else:
            self.use_fallback.setEnabled(True)

    def _browse_fallback_icons(self):
        current_path = self.fallback_icons_path.text()
        start_dir = current_path if current_path and Path(current_path).exists() else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select Fallback Icons Directory", start_dir, QFileDialog.ShowDirsOnly)
        if path:
            self.fallback_icons_path.setText(path)

    def _on_export_format_changed(self, format_text: str):
        is_jpeg = format_text.upper() in ("JPEG", "JPG")
        self.jpeg_quality.setEnabled(is_jpeg)

    def _open_device_asset_dialog(self):
        config_path = Path(self.config_path_value) if self.config_path_value else Path(".")
        output_dir = str(config_path.parent / "output") if config_path.exists() else "./output"
        dialog = DeviceAssetDialog(parent=self, output_dir=output_dir, device_path=self.device_path.text().strip())
        dialog.exec()

    def _on_custom_border_toggled(self, checked: bool):
        self.custom_border_path.setEnabled(checked)
        self.btn_browse_custom_border.setEnabled(checked)

    def _browse_custom_border(self):
        current_path = self.custom_border_path.text()
        start_dir = current_path if current_path and Path(current_path).exists() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Select Custom Border Image", start_dir, "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)")
        if path:
            self.custom_border_path.setText(path)
            self._update_custom_border_preview()

    def _update_custom_border_preview(self):
        path = self.custom_border_path.text()
        if path and Path(path).exists():
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.custom_border_preview.setPixmap(pixmap)
                return
        self.custom_border_preview.clear()

    def _load_platforms_for_border_selector(self):
        import yaml
        self.border_platform_combo.clear()
        config_path = Path(self.config_path_value) if self.config_path_value else None
        if config_path and config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                platforms = cfg.get("platforms", {})
                for platform_key in sorted(platforms.keys()):
                    self.border_platform_combo.addItem(platform_key, platform_key)
            except Exception:
                pass
        for platform_key in sorted(self.custom_platforms.keys()):
            if self.border_platform_combo.findData(platform_key) == -1:
                self.border_platform_combo.addItem(f"{platform_key} (Custom)", platform_key)

    def _on_border_platform_changed(self, index: int):
        if index < 0:
            return
        platform_key = self.border_platform_combo.currentData()
        if not platform_key:
            return
        per_platform = self.custom_border_settings.get("per_platform", {})
        border_path = per_platform.get(platform_key, "")
        self.per_platform_border_path.setText(border_path)
        self._update_per_platform_border_preview()

    def _browse_per_platform_border(self):
        current_path = self.per_platform_border_path.text()
        start_dir = current_path if current_path and Path(current_path).exists() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Select Custom Border for Platform", start_dir, "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)")
        if path:
            self.per_platform_border_path.setText(path)
            platform_key = self.border_platform_combo.currentData()
            if platform_key:
                if "per_platform" not in self.custom_border_settings:
                    self.custom_border_settings["per_platform"] = {}
                self.custom_border_settings["per_platform"][platform_key] = path
            self._update_per_platform_border_preview()

    def _clear_per_platform_border(self):
        platform_key = self.border_platform_combo.currentData()
        if platform_key:
            per_platform = self.custom_border_settings.get("per_platform", {})
            if platform_key in per_platform:
                del per_platform[platform_key]
            self.per_platform_border_path.clear()
            self._update_per_platform_border_preview()

    def _update_per_platform_border_preview(self):
        path = self.per_platform_border_path.text()
        if path and Path(path).exists():
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.per_platform_border_preview.setPixmap(pixmap)
                return
        self.per_platform_border_preview.clear()

    def _load_custom_platforms_list(self):
        self.custom_platforms_list.clear()
        for platform_key, config in self.custom_platforms.items():
            display_name = config.get("display_name", platform_key)
            publisher = config.get("publisher", "")
            year = config.get("year", "")
            item_text = f"{platform_key} - {display_name}"
            if publisher:
                item_text += f" ({publisher}"
                if year:
                    item_text += f", {year}"
                item_text += ")"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, platform_key)
            self.custom_platforms_list.addItem(item)

    def _on_custom_platform_selected(self, item):
        platform_key = item.data(Qt.UserRole)
        if platform_key and platform_key in self.custom_platforms:
            config = self.custom_platforms[platform_key]
            self.new_platform_key.setText(platform_key)
            self.new_platform_name.setText(config.get("display_name", ""))
            self.new_platform_publisher.setText(config.get("publisher", ""))
            self.new_platform_year.setValue(config.get("year", 2000))
            type_idx = self.new_platform_type.findText(config.get("type", "console"))
            if type_idx >= 0:
                self.new_platform_type.setCurrentIndex(type_idx)
            self.new_platform_border.setText(config.get("border_file", ""))
            self.new_platform_icon.setText(config.get("icon_file", ""))

    def _browse_new_platform_border(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Border Image", str(Path.home()), "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)")
        if path:
            self.new_platform_border.setText(path)

    def _browse_new_platform_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Platform Icon", str(Path.home()), "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)")
        if path:
            self.new_platform_icon.setText(path)

    def _add_custom_platform(self):
        platform_key = self.new_platform_key.text().strip().upper().replace(" ", "_")
        if not platform_key:
            QMessageBox.warning(self, "Error", "Platform key is required.")
            return
        display_name = self.new_platform_name.text().strip() or platform_key
        self.custom_platforms[platform_key] = {
            "display_name": display_name,
            "publisher": self.new_platform_publisher.text().strip(),
            "year": self.new_platform_year.value(),
            "type": self.new_platform_type.currentText(),
            "border_file": self.new_platform_border.text().strip(),
            "icon_file": self.new_platform_icon.text().strip(),
            "custom": True
        }
        self._load_custom_platforms_list()
        self._load_platforms_for_border_selector()
        self.new_platform_key.clear()
        self.new_platform_name.clear()
        self.new_platform_publisher.clear()
        self.new_platform_year.setValue(2000)
        self.new_platform_type.setCurrentIndex(0)
        self.new_platform_border.clear()
        self.new_platform_icon.clear()
        QMessageBox.information(self, "Success", f"Platform '{platform_key}' added.")

    def _remove_custom_platform(self):
        current_item = self.custom_platforms_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Error", "Select a platform to remove.")
            return
        platform_key = current_item.data(Qt.UserRole)
        if platform_key and platform_key in self.custom_platforms:
            reply = QMessageBox.question(self, "Confirm", f"Remove platform '{platform_key}'?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                del self.custom_platforms[platform_key]
                self._load_custom_platforms_list()
                self._load_platforms_for_border_selector()

    def _apply_and_accept(self):
        """Save API keys and accept dialog."""
        key_manager = get_manager()
        key_manager.set_key("steamgriddb", self.sgdb_key.text().strip())
        key_manager.set_key("igdb_client_id", self.igdb_client_id.text().strip())
        key_manager.set_key("igdb_client_secret", self.igdb_client_secret.text().strip())
        self.accept()

    # --- Getter Methods ---

    def get_config_path(self):
        return self.config_path.text()

    def get_workers(self):
        return self.workers.value()

    def get_limit(self):
        return self.limit.value()

    def get_source_order(self):
        return self.source_priority.get_source_order()

    def get_rom_directory_settings(self):
        rom_path = self.rom_path.text().strip()
        return {
            "mode": "manual" if not rom_path else "remembered",
            "rom_path": rom_path,
            "auto_detect": False,
            "remember_last_path": self.remember_rom_path.isChecked()
        }

    def get_hero_settings(self):
        return {
            "enabled": self.hero_enabled.isChecked(),
            "count": self.hero_count.value(),
            "save_with_icons": self.hero_save_with_icons.isChecked()
        }

    def get_fallback_settings(self):
        return {
            "use_platform_icon_fallback": self.use_fallback.isChecked(),
            "skip_scraping_use_platform_icon": self.skip_scraping.isChecked(),
            "fallback_icons_path": self.fallback_icons_path.text().strip()
        }

    def get_screenshot_settings(self):
        return {
            "enabled": self.screenshot_enabled.isChecked(),
            "count": self.screenshot_count.value()
        }

    def get_device_settings(self):
        return {
            "enabled": self.copy_to_device.isChecked(),
            "path": self.device_path.text().strip()
        }

    def get_logo_settings(self):
        return {
            "scrape_logos": self.scrape_logos.isChecked(),
            "fallback_to_boxart": self.logo_fallback_boxart.isChecked()
        }

    def get_export_settings(self):
        return {
            "format": self.export_format.currentText(),
            "jpeg_quality": self.jpeg_quality.value()
        }

    def get_custom_border_settings(self):
        per_platform = dict(self.custom_border_settings.get("per_platform", {}))
        return {
            "enabled": self.use_custom_border.isChecked(),
            "path": self.custom_border_path.text().strip(),
            "per_platform": per_platform
        }

    def get_custom_platforms(self):
        return dict(self.custom_platforms)

    # --- Setter Methods ---

    def set_fallback_settings(self, settings: dict):
        self.fallback_settings = settings
        self.use_fallback.setChecked(settings.get("use_platform_icon_fallback", False))
        self.skip_scraping.setChecked(settings.get("skip_scraping_use_platform_icon", False))
        self.fallback_icons_path.setText(settings.get("fallback_icons_path", ""))

    def set_screenshot_settings(self, settings: dict):
        self.screenshot_settings = settings
        self.screenshot_enabled.setChecked(settings.get("enabled", False))
        self.screenshot_count.setValue(settings.get("count", 3))

    def set_device_settings(self, settings: dict):
        self.device_settings = settings
        self.copy_to_device.setChecked(settings.get("enabled", False))
        self.device_path.setText(settings.get("path", "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"))

    def set_logo_settings(self, settings: dict):
        self.logo_settings = settings
        self.scrape_logos.setChecked(settings.get("scrape_logos", True))
        self.logo_fallback_boxart.setChecked(settings.get("fallback_to_boxart", True))

    def set_export_settings(self, settings: dict):
        self.export_settings = settings
        self.export_format.setCurrentText(settings.get("format", "JPEG"))
        self.jpeg_quality.setValue(settings.get("jpeg_quality", 95))
        self._on_export_format_changed(self.export_format.currentText())

    def set_custom_border_settings(self, settings: dict):
        self.custom_border_settings = settings
        self.use_custom_border.setChecked(settings.get("enabled", False))
        self.custom_border_path.setText(settings.get("path", ""))
        self._update_custom_border_preview()
        self._on_custom_border_toggled(self.use_custom_border.isChecked())
        if hasattr(self, 'border_platform_combo') and self.border_platform_combo.count() > 0:
            self._on_border_platform_changed(self.border_platform_combo.currentIndex())

    def set_custom_platforms(self, platforms: dict):
        self.custom_platforms = dict(platforms) if platforms else {}
        if hasattr(self, 'custom_platforms_list'):
            self._load_custom_platforms_list()
        if hasattr(self, 'border_platform_combo'):
            self._load_platforms_for_border_selector()
