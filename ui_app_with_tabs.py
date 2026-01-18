"""
iiSU Icon Generator with integrated Border Generator
Main application with tabbed interface
"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QIcon, QFontDatabase, QDesktopServices, QPixmap, QPainter, QColor, QBrush
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from app_paths import get_app_dir, get_logo_path, get_theme_path, get_fonts_dir, get_src_dir, get_config_path, verify_required_assets


class DotPatternWidget(QWidget):
    """
    Widget that draws a dot pattern background matching iiSU design language.
    The dot pattern is drawn at 10% opacity with light gray dots.
    """

    def __init__(self, parent=None, dark_mode: bool = True):
        super().__init__(parent)
        self._dark_mode = dark_mode
        self.setAttribute(Qt.WA_StyledBackground, True)

    def set_dark_mode(self, dark_mode: bool):
        """Update the dark mode setting and repaint."""
        self._dark_mode = dark_mode
        self.update()

    def paintEvent(self, event):
        """Draw the dot pattern background."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Get colors based on theme
        if self._dark_mode:
            bg_color = QColor("#212529")
            dot_color = QColor(180, 180, 180, 25)  # Light gray at ~10% opacity
        else:
            bg_color = QColor("#F5F5F7")
            dot_color = QColor(100, 100, 100, 25)  # Gray at ~10% opacity

        # Fill background
        painter.fillRect(self.rect(), bg_color)

        # Draw dot pattern
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(dot_color))

        dot_size = 2
        spacing = 20

        # Calculate visible area and draw dots
        rect = self.rect()
        start_x = (rect.left() // spacing) * spacing
        start_y = (rect.top() // spacing) * spacing

        for x in range(start_x, rect.right() + spacing, spacing):
            for y in range(start_y, rect.bottom() + spacing, spacing):
                painter.drawEllipse(x - dot_size // 2, y - dot_size // 2, dot_size, dot_size)

        painter.end()


def create_colored_icon(icon_path: Path, color: QColor) -> QIcon:
    """Create a colored version of an icon by tinting it."""
    if not icon_path.exists():
        return QIcon()

    pixmap = QPixmap(str(icon_path))
    if pixmap.isNull():
        return QIcon()

    # Create a colored version - paint the color over the icon using composition
    colored = QPixmap(pixmap.size())
    colored.fill(Qt.transparent)

    painter = QPainter(colored)
    painter.setCompositionMode(QPainter.CompositionMode_Source)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(colored.rect(), color)
    painter.end()

    return QIcon(colored)

# Import UI components
from icon_generator_tab import IconGeneratorTab
from border_generator_tab import BorderGeneratorTab
from custom_image_tab import CustomImageTab
from cover_generator_tab import CoverGeneratorTab
from rom_browser_tab import ROMBrowserTab


class MainWindowWithTabs(QMainWindow):
    """Main window with tabbed interface for Icon Generator and Border Generator."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("iiSU Asset Tool")
        self.setMinimumSize(1200, 800)

        # Theme state (load from settings)
        self._dark_mode = self._load_theme_preference()

        # Set window icon if logo exists
        logo_path = get_logo_path()
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        # Load iiSU theme stylesheet
        self._load_theme()

        # Create central widget with dot pattern background (iiSU signature design)
        self._central_widget = DotPatternWidget(dark_mode=self._dark_mode)
        self.setCentralWidget(self._central_widget)

        layout = QVBoxLayout(self._central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header with logo and title
        header_widget = QWidget()
        header_widget.setObjectName("app_header")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(20, 15, 20, 15)

        # Logo
        if logo_path.exists():
            from PySide6.QtGui import QPixmap
            logo_label = QLabel()
            logo_pixmap = QPixmap(str(logo_path))
            scaled_logo = logo_pixmap.scaledToHeight(48, Qt.SmoothTransformation)
            logo_label.setPixmap(scaled_logo)
            header_layout.addWidget(logo_label)

        # Title
        title = QLabel("iiSU Asset Tool")
        title.setObjectName("header")
        header_layout.addWidget(title)

        header_layout.addStretch(1)

        # Icon paths
        src_dir = get_src_dir()
        info_icon_path = src_dir / "InfoIcon.png"
        gear_icon_path = src_dir / "GearIcon.png"

        # Icon color for current theme
        icon_color = QColor("#FFFFFF") if self._dark_mode else QColor("#1D1D1F")

        # Theme toggle button
        self.btn_theme = QPushButton()
        self.btn_theme.setMaximumWidth(40)
        self.btn_theme.setMinimumWidth(40)
        self.btn_theme.setMaximumHeight(40)
        self._update_theme_button()
        self.btn_theme.clicked.connect(self._toggle_theme)
        header_layout.addWidget(self.btn_theme)

        # Info button (about/credits)
        self.btn_info = QPushButton()
        self.btn_info.setMaximumWidth(40)
        self.btn_info.setMinimumWidth(40)
        self.btn_info.setMaximumHeight(40)
        self.btn_info.setToolTip("About & Credits")
        if info_icon_path.exists():
            self.btn_info.setIcon(create_colored_icon(info_icon_path, icon_color))
            self.btn_info.setIconSize(QSize(20, 20))
        else:
            self.btn_info.setText("ℹ")
        self.btn_info.clicked.connect(self._show_info_dialog)
        header_layout.addWidget(self.btn_info)

        # Settings button
        self.btn_options = QPushButton()
        self.btn_options.setMaximumWidth(40)
        self.btn_options.setMinimumWidth(40)
        self.btn_options.setMaximumHeight(40)
        self.btn_options.setToolTip("Settings")
        if gear_icon_path.exists():
            self.btn_options.setIcon(create_colored_icon(gear_icon_path, icon_color))
            self.btn_options.setIconSize(QSize(20, 20))
        else:
            self.btn_options.setText("⚙")
        self.btn_options.clicked.connect(self._open_settings)
        header_layout.addWidget(self.btn_options)

        layout.addWidget(header_widget)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setMovable(False)

        # Add tabs
        self.rom_browser_tab = ROMBrowserTab()
        self.tabs.addTab(self.rom_browser_tab, "ROM Browser")
        self.tabs.addTab(IconGeneratorTab(), "Icon Scraper")
        self.tabs.addTab(CustomImageTab(), "Custom Icons")
        self.tabs.addTab(BorderGeneratorTab(), "Custom Borders")
        self.tabs.addTab(CoverGeneratorTab(), "Custom Covers")

        layout.addWidget(self.tabs)

    def _load_theme_preference(self) -> bool:
        """Load theme preference from config. Returns True for dark mode, False for light."""
        try:
            from pathlib import Path
            import yaml
            cfg_path = Path(get_config_path())
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                return cfg.get("ui", {}).get("dark_mode", True)
        except Exception:
            pass
        return True  # Default to dark mode

    def _save_theme_preference(self):
        """Save theme preference to config."""
        try:
            from pathlib import Path
            import yaml
            cfg_path = Path(get_config_path())
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                if "ui" not in cfg:
                    cfg["ui"] = {}
                cfg["ui"]["dark_mode"] = self._dark_mode
                with open(cfg_path, "w", encoding="utf-8") as f:
                    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"Failed to save theme preference: {e}")

    def _load_theme(self):
        """Load iiSU theme stylesheet based on current mode."""
        app_dir = get_app_dir()
        if self._dark_mode:
            theme_path = app_dir / "iisu_theme.qss"
        else:
            theme_path = app_dir / "iisu_theme_light.qss"

        if theme_path.exists():
            try:
                with open(theme_path, 'r', encoding='utf-8') as f:
                    self.setStyleSheet(f.read())
            except Exception as e:
                print(f"Failed to load theme: {e}")
                if self._dark_mode:
                    self.setStyleSheet("QWidget { background-color: #212529; color: #E9E9E9; }")
                else:
                    self.setStyleSheet("QWidget { background-color: #F5F5F7; color: #1D1D1F; }")
        else:
            print(f"Theme file not found: {theme_path}")
            if self._dark_mode:
                self.setStyleSheet("QWidget { background-color: #212529; color: #E9E9E9; }")
            else:
                self.setStyleSheet("QWidget { background-color: #F5F5F7; color: #1D1D1F; }")

    def _update_theme_button(self):
        """Update theme toggle button icon/text."""
        src_dir = get_src_dir()
        icon_color = QColor("#FFFFFF") if self._dark_mode else QColor("#1D1D1F")

        if self._dark_mode:
            # Show sun icon (to switch to light mode)
            sun_icon_path = src_dir / "sun-3337.png"
            if sun_icon_path.exists():
                self.btn_theme.setIcon(create_colored_icon(sun_icon_path, icon_color))
                self.btn_theme.setIconSize(QSize(20, 20))
                self.btn_theme.setText("")
            else:
                self.btn_theme.setText("☀")
            self.btn_theme.setToolTip("Switch to Light Mode")
        else:
            # Show moon icon (to switch to dark mode)
            moon_icon_path = src_dir / "dark-mode-6682.png"
            if moon_icon_path.exists():
                self.btn_theme.setIcon(create_colored_icon(moon_icon_path, icon_color))
                self.btn_theme.setIconSize(QSize(20, 20))
                self.btn_theme.setText("")
            else:
                self.btn_theme.setText("🌙")
            self.btn_theme.setToolTip("Switch to Dark Mode")

    def _toggle_theme(self):
        """Toggle between light and dark themes."""
        self._dark_mode = not self._dark_mode
        self._load_theme()
        self._update_theme_button()
        self._update_icon_colors()
        self._save_theme_preference()
        # Update dot pattern background
        if hasattr(self, '_central_widget'):
            self._central_widget.set_dark_mode(self._dark_mode)

    def _update_icon_colors(self):
        """Update icon colors based on current theme."""
        src_dir = get_src_dir()
        info_icon_path = src_dir / "InfoIcon.png"
        gear_icon_path = src_dir / "GearIcon.png"

        icon_color = QColor("#FFFFFF") if self._dark_mode else QColor("#1D1D1F")

        if info_icon_path.exists():
            self.btn_info.setIcon(create_colored_icon(info_icon_path, icon_color))
        if gear_icon_path.exists():
            self.btn_options.setIcon(create_colored_icon(gear_icon_path, icon_color))

    def _show_info_dialog(self):
        """Show info dialog with sources and credits."""
        from PySide6.QtWidgets import QDialog, QTextBrowser, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("About iiSU Asset Tool")
        dialog.setMinimumSize(600, 600)

        layout = QVBoxLayout(dialog)

        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setHtml("""
        <h2>iiSU Asset Tool</h2>
        <p>Create custom icons, borders, covers, and more for your game library.<br>
        Designed for use with the iiSU Launcher on Android devices.</p>

        <h3>Features</h3>
        <ul>
            <li><b>ROM Browser</b> - Scan and manage your ROM collection by platform</li>
            <li><b>Icon Scraper</b> - Automatically fetch and generate game icons with platform borders</li>
            <li><b>Cover Generator</b> - Create high-quality game covers</li>
            <li><b>Custom Icons</b> - Design custom icons with layer support:
                <ul>
                    <li>Background layer (game art)</li>
                    <li>Logo overlay layer (transparent PNG)</li>
                    <li>Independent controls for each layer (position, scale, rotation, opacity)</li>
                </ul>
            </li>
            <li><b>Device Manager</b> - Push assets directly to your Android device via ADB</li>
            <li><b>Auto-Push</b> - Automatically push generated assets to connected devices</li>
        </ul>

        <h3>Settings & Customization</h3>
        <ul>
            <li><b>Per-Platform Custom Borders</b> - Set unique borders for each platform</li>
            <li><b>Custom Platforms</b> - Add your own platforms (Steam, older consoles, etc.)</li>
            <li><b>Fallback Icons</b> - Use platform icons when artwork isn't found</li>
            <li><b>Hero Images & Screenshots</b> - Download additional artwork types</li>
            <li><b>Logo Scraping</b> - Fetch transparent game logos</li>
            <li><b>Source Priority</b> - Configure which artwork sources to prefer</li>
        </ul>

        <h3>Artwork Sources</h3>
        <ul>
            <li><a href="https://www.steamgriddb.com/" style="color: #00D4FF;">SteamGridDB</a> - Community artwork database (icons, heroes, logos)</li>
            <li><a href="https://thumbnails.libretro.com/" style="color: #00D4FF;">Libretro Thumbnails</a> - RetroArch boxart collection</li>
            <li><a href="https://www.igdb.com/" style="color: #00D4FF;">IGDB</a> - Internet Game Database (covers)</li>
            <li><a href="https://thegamesdb.net/" style="color: #00D4FF;">TheGamesDB</a> - Game information and artwork</li>
        </ul>

        <h3>Supported Platforms</h3>
        <p>Nintendo: NES, SNES, N64, GameCube, Wii, Wii U, Switch, Game Boy, GBC, GBA, DS, 3DS<br>
        Sony: PS1, PS2, PS3, PS4, PS5, PSP, PS Vita<br>
        Microsoft: Xbox, Xbox 360<br>
        Sega: Master System, Genesis, Sega CD, 32X, Saturn, Dreamcast, Game Gear<br>
        Mobile: Android<br>
        <i>Plus custom platforms you define!</i></p>

        <h3>Credits</h3>
        <p>Built for the <a href="https://iisu.network/" style="color: #00D4FF;">iiSU Network</a> community.</p>
        <p>Special thanks to the iiSU team for the design aesthetic and inspiration.</p>
        <p>Logo by <b>Caddypillar</b></p>

        <h3>License</h3>
        <p>This tool is provided as-is for creating custom game library assets.<br>
        Ensure compliance with artwork source terms of service.</p>

        <p style="color: #666; font-size: 10px; margin-top: 20px;">
        Version 1.2.1 | Desktop + Android companion app available
        </p>
        """)
        layout.addWidget(text)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.exec()

    def _open_settings(self):
        """Open the settings dialog."""
        from options_dialog import OptionsDialog
        import yaml
        from pathlib import Path

        # Get the current icon generator tab to access its settings
        icon_tab = self.tabs.widget(1)  # Icon Scraper is now the second tab (index 1)

        # Load all settings from config
        rom_settings = {}
        hero_settings = {}
        fallback_settings = {}
        screenshot_settings = {}
        device_settings = {}
        logo_settings = {}
        custom_border_settings = {}
        custom_platforms = {}
        processing_settings = {}
        export_settings = {}

        if hasattr(icon_tab, 'config_path'):
            try:
                cfg_path = Path(icon_tab.config_path)
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                    rom_settings = cfg.get("rom_directory", {})
                    hero_settings = cfg.get("hero_images", {})
                    fallback_settings = cfg.get("fallback_icons", {})
                    screenshot_settings = cfg.get("screenshots", {})
                    device_settings = cfg.get("device_copy", {})
                    logo_settings = cfg.get("logos", {})
                    custom_border_settings = cfg.get("custom_borders", {})
                    custom_platforms = cfg.get("custom_platforms", {})
                    processing_settings = cfg.get("processing", {})
                    export_settings = {
                        "format": cfg.get("export_format", "PNG"),
                        "jpeg_quality": cfg.get("jpeg_quality", 95)
                    }
            except Exception:
                pass

        if hasattr(icon_tab, 'config_path'):
            # Use saved processing settings or current values
            workers = processing_settings.get("workers", icon_tab.workers_value)
            limit = processing_settings.get("limit", icon_tab.limit_value)

            dialog = OptionsDialog(
                parent=self,
                config_path=icon_tab.config_path,
                workers=workers,
                limit=limit,
                source_priority_widget=icon_tab.source_priority,
                rom_directory_settings=rom_settings
            )

            # Set hero settings if available
            if hero_settings:
                dialog.hero_settings = hero_settings
                dialog.hero_enabled.setChecked(hero_settings.get("enabled", True))
                dialog.hero_count.setValue(hero_settings.get("count", 1))
                dialog.hero_save_with_icons.setChecked(hero_settings.get("save_with_icons", True))

            # Set fallback settings if available
            if fallback_settings:
                dialog.set_fallback_settings(fallback_settings)

            # Set screenshot settings if available
            if screenshot_settings:
                dialog.set_screenshot_settings(screenshot_settings)

            # Set device copy settings if available
            if device_settings:
                dialog.set_device_settings(device_settings)

            # Set logo settings if available
            if logo_settings:
                dialog.set_logo_settings(logo_settings)

            # Set export settings if available
            if export_settings:
                dialog.set_export_settings(export_settings)

            # Set custom border settings if available
            if custom_border_settings:
                dialog.set_custom_border_settings(custom_border_settings)

            # Set custom platforms if available
            if custom_platforms:
                dialog.set_custom_platforms(custom_platforms)

            if dialog.exec():
                # Update the icon tab's stored values
                icon_tab.config_path = dialog.get_config_path()
                icon_tab.workers_value = dialog.get_workers()
                icon_tab.limit_value = dialog.get_limit()

                # Update source priority
                source_order = dialog.get_source_order()
                icon_tab.source_priority.set_source_order(source_order)

                # Reload platforms if config changed
                icon_tab.load_platforms_from_config()

                # Get all settings from dialog
                rom_dir_settings = dialog.get_rom_directory_settings()
                hero_settings = dialog.get_hero_settings()
                fallback_settings = dialog.get_fallback_settings()
                screenshot_settings = dialog.get_screenshot_settings()
                device_settings = dialog.get_device_settings()
                logo_settings = dialog.get_logo_settings()
                export_settings = dialog.get_export_settings()
                custom_border_settings = dialog.get_custom_border_settings()
                custom_platforms = dialog.get_custom_platforms()
                processing_settings = {
                    "workers": dialog.get_workers(),
                    "limit": dialog.get_limit()
                }

                # Save ALL settings to config
                self._save_settings_to_config(
                    icon_tab.config_path,
                    rom_dir_settings,
                    hero_settings,
                    fallback_settings,
                    screenshot_settings,
                    device_settings,
                    logo_settings,
                    custom_border_settings,
                    custom_platforms,
                    processing_settings,
                    export_settings
                )

                # Store settings on icon tab for backend access
                icon_tab.fallback_settings = fallback_settings
                icon_tab.screenshot_settings = screenshot_settings
                icon_tab.device_settings = device_settings
                icon_tab.logo_settings = logo_settings
                icon_tab.custom_border_settings = custom_border_settings

                # Update ROM browser tab
                self.rom_browser_tab.set_rom_path(rom_dir_settings.get("rom_path", ""))
                self.rom_browser_tab.set_hero_settings(
                    hero_settings.get("enabled", True),
                    hero_settings.get("count", 1)
                )
                self.rom_browser_tab.fallback_settings = fallback_settings
                self.rom_browser_tab.screenshot_settings = screenshot_settings
                self.rom_browser_tab.device_settings = device_settings
                self.rom_browser_tab.logo_settings = logo_settings

    def _save_settings_to_config(self, config_path, rom_settings, hero_settings, fallback_settings=None,
                                  screenshot_settings=None, device_settings=None, logo_settings=None,
                                  custom_border_settings=None, custom_platforms=None,
                                  processing_settings=None, export_settings=None):
        """Save all settings to config file for persistence between sessions."""
        import yaml
        from pathlib import Path

        cfg_path = Path(config_path)
        if not cfg_path.exists():
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            # Core settings
            cfg["rom_directory"] = rom_settings
            cfg["hero_images"] = hero_settings

            # Optional settings
            if fallback_settings:
                cfg["fallback_icons"] = fallback_settings
            if screenshot_settings:
                cfg["screenshots"] = screenshot_settings
            if device_settings:
                cfg["device_copy"] = device_settings
            if logo_settings:
                cfg["logos"] = logo_settings
            if custom_border_settings:
                cfg["custom_borders"] = custom_border_settings

            # Processing settings (workers, limit)
            if processing_settings:
                cfg["processing"] = processing_settings

            # Export settings (format, quality)
            if export_settings:
                cfg["export_format"] = export_settings.get("format", "PNG")
                cfg["jpeg_quality"] = export_settings.get("jpeg_quality", 95)

            # Custom platforms
            if custom_platforms:
                cfg["custom_platforms"] = custom_platforms
                # Also merge custom platforms into the main platforms dict
                if "platforms" not in cfg:
                    cfg["platforms"] = {}
                for platform_key, platform_config in custom_platforms.items():
                    cfg["platforms"][platform_key] = {
                        "border_file": platform_config.get("border_file", ""),
                        "icon_file": platform_config.get("icon_file", ""),
                        "publisher": platform_config.get("publisher", ""),
                        "year": platform_config.get("year", 2000),
                        "type": platform_config.get("type", "other"),
                        "custom": True
                    }

            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

        except Exception as e:
            print(f"Failed to save settings: {e}")


def main():
    # Windows: Set App User Model ID for taskbar icon
    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("iiSU.IconGenerator.1.0")
        except:
            pass

    # Load saved API keys into environment on startup
    try:
        from api_key_manager import get_manager
        key_manager = get_manager()
        # Just accessing the keys will set environment variables if stored
        for service in ["steamgriddb", "igdb_client_id", "igdb_client_secret", "thegamesdb"]:
            key_manager.get_key(service)
    except Exception as e:
        print(f"Note: Could not load saved API keys: {e}")

    app = QApplication(sys.argv)

    # Check for missing required assets and warn user
    asset_check = verify_required_assets()
    if asset_check['missing']:
        from PySide6.QtWidgets import QMessageBox
        missing_list = "\n".join(f"  - {item}" for item in asset_check['missing'])
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Missing Assets")
        msg.setText("Some required asset files are missing.")
        msg.setInformativeText(
            f"The application may not work correctly.\n\n"
            f"App directory: {asset_check['app_dir']}\n\n"
            f"Missing:\n{missing_list}\n\n"
            f"Please ensure you extracted all files from the release archive."
        )
        msg.exec()

    # Load Continuum Bold font if available
    fonts_dir = get_fonts_dir()
    if fonts_dir.exists():
        for font_file in fonts_dir.glob("*.ttf"):
            font_id = QFontDatabase.addApplicationFont(str(font_file))
            if font_id != -1:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                print(f"Loaded font: {', '.join(font_families)}")
        for font_file in fonts_dir.glob("*.otf"):
            font_id = QFontDatabase.addApplicationFont(str(font_file))
            if font_id != -1:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                print(f"Loaded font: {', '.join(font_families)}")

    # Set application icon for taskbar
    logo_path = get_logo_path()
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    w = MainWindowWithTabs()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
