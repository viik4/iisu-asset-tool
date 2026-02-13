"""
iiSU Soundbyte Browser Tab

Browse and download game music from KHInsider for use as soundbytes
(hover music) in iiSU Launcher.
"""

import os
import threading
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

import yaml
from PySide6.QtCore import Qt, Signal, QObject, QSize, QTimer, QUrl
from PySide6.QtGui import QPixmap, QImage, QDesktopServices, QIcon

# Try to import multimedia for audio preview
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QLineEdit, QProgressBar, QComboBox,
    QMessageBox, QTreeWidget, QTreeWidgetItem, QFrame, QGroupBox,
    QScrollArea, QGridLayout, QDialog, QDialogButtonBox,
    QSlider, QSpinBox, QListWidget, QListWidgetItem, QCheckBox,
    QFileDialog, QApplication, QStyle, QLayout, QSizePolicy
)
from PySide6.QtCore import QRect, QSize

from app_paths import get_config_path, get_config
from background_music import get_music_manager
from khinsider_scraper import (
    KHInsiderScraper, SoundbyteAlbum, SoundbyteTrack,
    SoundbyteSearchResult, search_soundbytes
)
import requests


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


class WorkerSignals(QObject):
    """Signals for background worker threads."""
    finished = Signal()
    error = Signal(str)
    progress = Signal(int, int)  # current, total
    result = Signal(object)
    track_downloaded = Signal(str, bytes)  # track_url, audio_data
    search_complete = Signal(object)  # SoundbyteSearchResult
    search_error = Signal(str)
    download_complete = Signal(str, object)  # file_path, track
    download_error = Signal(str)
    cover_loaded = Signal(object, object)  # card, pixmap


class TrackListItem(QListWidgetItem):
    """List item representing a track with metadata."""

    def __init__(self, track: SoundbyteTrack, parent=None):
        super().__init__(parent)
        self.track = track

        # Format display text
        duration = track.duration if track.duration else "??:??"
        text = f"{track.track_number:02d}. {track.title} [{duration}]"
        self.setText(text)

        # Add tooltip with more info
        self.setToolTip(f"Duration: {duration}\nClick to preview")


class AlbumCard(QFrame):
    """Card widget displaying an album with cover art."""

    selected = Signal(object)  # Emits the album when clicked

    def __init__(self, album: SoundbyteAlbum, parent=None):
        super().__init__(parent)
        self.album = album
        self._is_selected = False

        self.setObjectName("album_card")
        self.setFrameShape(QFrame.Box)
        self.setFixedSize(180, 220)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Cover art placeholder
        self.cover_label = QLabel()
        self.cover_label.setObjectName("album_cover")
        self.cover_label.setFixedSize(160, 160)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setText("...")
        layout.addWidget(self.cover_label)

        # Title label
        title = album.game_name
        if len(title) > 22:
            title = title[:20] + "..."
        self.title_label = QLabel(title)
        self.title_label.setObjectName("album_title")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setToolTip(album.title)
        layout.addWidget(self.title_label)

        # Badges row
        badges = QHBoxLayout()
        badges.setSpacing(4)

        if album.is_gamerip:
            gamerip_badge = self._create_badge("GAMERIP", "#4CAF50")
            badges.addWidget(gamerip_badge)

        if album.track_count > 0:
            count_badge = self._create_badge(f"{album.track_count} tracks", "#9575CD")
            badges.addWidget(count_badge)

        badges.addStretch()
        layout.addLayout(badges)

    def _create_badge(self, text: str, color: str) -> QLabel:
        """Create a small badge label."""
        badge = QLabel(text)
        badge.setAlignment(Qt.AlignCenter)
        # Kept inline: dynamic badge color varies per call (green for GAMERIP, purple for track count)
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: #000;
                border-radius: 3px;
                font-size: 9px;
                font-weight: bold;
                padding: 2px 4px;
            }}
        """)
        return badge

    def _update_style(self):
        """Update style based on selection state using Qt property."""
        self.setProperty("selected", "true" if self._is_selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_cover(self, pixmap: QPixmap):
        """Set the cover art image."""
        try:
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.cover_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.cover_label.setPixmap(scaled)
            else:
                self.cover_label.setText("No Art")
        except RuntimeError:
            pass  # Widget was deleted

    def set_selected(self, selected: bool):
        """Set selection state."""
        self._is_selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        """Handle click to select."""
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.album)
        super().mousePressEvent(event)


class TrackPreviewSignals(QObject):
    """Signals for TrackPreviewDialog."""
    tracks_loaded = Signal(object)  # album
    load_error = Signal(str)
    preview_url_ready = Signal(str, object)  # url, track
    preview_error = Signal(str)


class TrackPreviewDialog(QDialog):
    """Dialog for previewing and selecting a track to download."""

    def __init__(self, album: SoundbyteAlbum, scraper: KHInsiderScraper, parent=None):
        super().__init__(parent)
        self.album = album
        self.scraper = scraper
        self.selected_track: Optional[SoundbyteTrack] = None
        self.download_url: Optional[str] = None

        # Create signals for thread communication
        self._signals = TrackPreviewSignals()
        self._signals.tracks_loaded.connect(self._on_tracks_loaded)
        self._signals.load_error.connect(self._on_load_error)
        self._signals.preview_url_ready.connect(self._on_preview_url_ready)
        self._signals.preview_error.connect(self._on_preview_error)

        # Audio player setup
        self._player = None
        self._audio_output = None
        self._is_playing = False
        self._bg_music_original_volume = None  # For ducking background music
        if HAS_MULTIMEDIA:
            self._player = QMediaPlayer()
            self._audio_output = QAudioOutput()
            self._player.setAudioOutput(self._audio_output)
            self._audio_output.setVolume(0.7)
            self._player.playbackStateChanged.connect(self._on_playback_state_changed)

        self.setWindowTitle(f"{album.game_name} - Select Track")
        self.setMinimumSize(500, 600)
        self.setModal(True)

        self._setup_ui()
        self._load_tracks()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(self.album.title)
        header.setObjectName("label_header")
        header.setWordWrap(True)
        layout.addWidget(header)

        if self.album.is_gamerip:
            gamerip = QLabel("GAMERIP - High Quality")
            # Kept inline: green accent color (#4CAF50) has no matching QSS objectName
            gamerip.setStyleSheet("color: #4CAF50; font-size: 12px;")
            layout.addWidget(gamerip)

        # Filter section
        filter_frame = QFrame()
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(0, 0, 0, 0)

        filter_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter tracks...")
        self.search_input.textChanged.connect(self._filter_tracks)
        filter_layout.addWidget(self.search_input, 1)

        layout.addWidget(filter_frame)

        # Track list
        self.track_list = QListWidget()
        self.track_list.setObjectName("track_list")
        self.track_list.itemClicked.connect(self._on_track_selected)
        self.track_list.itemDoubleClicked.connect(self._on_track_double_clicked)
        layout.addWidget(self.track_list, 1)

        # Status
        self.status_label = QLabel("Loading tracks...")
        self.status_label.setObjectName("label_muted")
        layout.addWidget(self.status_label)

        # Selected track info
        self.selected_frame = QFrame()
        self.selected_frame.setObjectName("selected_track_panel")
        selected_layout = QVBoxLayout(self.selected_frame)

        self.selected_title = QLabel("No track selected")
        self.selected_title.setObjectName("label_accent")
        selected_layout.addWidget(self.selected_title)

        self.selected_info = QLabel("")
        self.selected_info.setObjectName("label_muted")
        selected_layout.addWidget(self.selected_info)

        # Audio preview controls
        if HAS_MULTIMEDIA:
            preview_row = QHBoxLayout()

            self.preview_btn = QPushButton("▶ Preview")
            self.preview_btn.setObjectName("btn_secondary")
            self.preview_btn.setToolTip("Play a preview of this track")
            self.preview_btn.clicked.connect(self._toggle_preview)
            self.preview_btn.setEnabled(False)
            preview_row.addWidget(self.preview_btn)

            self.volume_slider = QSlider(Qt.Horizontal)
            self.volume_slider.setMinimum(0)
            self.volume_slider.setMaximum(100)
            self.volume_slider.setValue(70)
            self.volume_slider.setFixedWidth(80)
            self.volume_slider.setToolTip("Volume")
            self.volume_slider.valueChanged.connect(self._on_volume_changed)
            preview_row.addWidget(QLabel("🔊"))
            preview_row.addWidget(self.volume_slider)

            self.preview_status = QLabel("")
            self.preview_status.setObjectName("label_muted")
            preview_row.addWidget(self.preview_status)

            preview_row.addStretch()
            selected_layout.addLayout(preview_row)
        else:
            no_preview = QLabel("Audio preview unavailable (PySide6-Multimedia not installed)")
            no_preview.setObjectName("label_muted")
            selected_layout.addWidget(no_preview)

        self.selected_frame.setVisible(False)
        layout.addWidget(self.selected_frame)

        # Buttons
        button_layout = QHBoxLayout()

        self.download_btn = QPushButton("Download Selected")
        self.download_btn.setObjectName("btn_primary")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.download_btn)

        self.open_btn = QPushButton("Open in Browser")
        self.open_btn.setObjectName("btn_secondary")
        self.open_btn.clicked.connect(self._open_in_browser)
        button_layout.addWidget(self.open_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _load_tracks(self):
        """Load album tracks in background."""
        signals = self._signals
        scraper = self.scraper
        album = self.album

        def load():
            try:
                updated_album = scraper.get_album_details(album)
                signals.tracks_loaded.emit(updated_album)
            except Exception as e:
                signals.load_error.emit(str(e))

        thread = threading.Thread(target=load)
        thread.daemon = True
        thread.start()

    def _on_tracks_loaded(self, album: SoundbyteAlbum):
        """Handle tracks loaded."""
        self.album = album
        self._populate_track_list()
        self.status_label.setText(f"{len(album.tracks)} tracks found")

    def _on_load_error(self, error: str):
        """Handle load error."""
        self.status_label.setText(f"Error: {error}")
        # Kept inline: dynamic runtime status color change (error red)
        self.status_label.setStyleSheet("color: #E53935;")

    def _populate_track_list(self):
        """Populate the track list."""
        self.track_list.clear()

        search_text = self.search_input.text().lower()

        for track in self.album.tracks:
            # Filter by search text
            if search_text and search_text not in track.title.lower():
                continue

            item = TrackListItem(track)
            self.track_list.addItem(item)

    def _filter_tracks(self):
        """Filter the track list."""
        self._populate_track_list()

    def _on_track_selected(self, item: QListWidgetItem):
        """Handle track selection."""
        if isinstance(item, TrackListItem):
            # Stop any current preview
            self._stop_preview()

            self.selected_track = item.track

            self.selected_title.setText(item.track.title)
            duration = item.track.duration or "Unknown"
            self.selected_info.setText(f"Duration: {duration} | Track #{item.track.track_number}")

            self.selected_frame.setVisible(True)
            self.download_btn.setEnabled(True)

            # Enable preview button
            if HAS_MULTIMEDIA and hasattr(self, 'preview_btn'):
                self.preview_btn.setEnabled(True)
                self.preview_status.setText("")
                self.preview_status.setStyleSheet("")  # Reset to QSS objectName styling (label_muted)

    def _on_track_double_clicked(self, item: QListWidgetItem):
        """Handle double-click to download."""
        self._on_track_selected(item)
        self.accept()

    def _open_in_browser(self):
        """Open album page in browser."""
        QDesktopServices.openUrl(QUrl(self.album.url))

    def _toggle_preview(self):
        """Toggle audio preview playback."""
        if not HAS_MULTIMEDIA or not self._player:
            return

        if self._is_playing:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview(self):
        """Start playing preview of selected track."""
        if not self.selected_track or not HAS_MULTIMEDIA:
            return

        self.preview_btn.setEnabled(False)
        self.preview_status.setText("Loading...")

        signals = self._signals
        scraper = self.scraper
        track = self.selected_track

        def get_url():
            try:
                url = scraper.get_track_download_url(track)
                if url:
                    signals.preview_url_ready.emit(url, track)
                else:
                    signals.preview_error.emit("Could not get track URL")
            except Exception as e:
                signals.preview_error.emit(str(e))

        thread = threading.Thread(target=get_url)
        thread.daemon = True
        thread.start()

    def _on_preview_url_ready(self, url: str, track: SoundbyteTrack):
        """Handle preview URL ready."""
        if not HAS_MULTIMEDIA or not self._player:
            return

        self.preview_btn.setEnabled(True)
        self.preview_status.setText("Playing...")

        # Duck background music while previewing
        bg_music = get_music_manager()
        if bg_music.is_playing():
            self._bg_music_original_volume = bg_music.get_volume()
            bg_music.set_volume(max(5, self._bg_music_original_volume // 5))

        self._player.setSource(QUrl(url))
        self._player.play()
        self._is_playing = True
        self.preview_btn.setText("⏹ Stop")

    def _on_preview_error(self, error: str):
        """Handle preview error."""
        self.preview_btn.setEnabled(True)
        self.preview_status.setText(f"Error: {error}")
        # Kept inline: dynamic runtime status color change (error red)
        self.preview_status.setStyleSheet("color: #E53935;")

    def _stop_preview(self):
        """Stop preview playback."""
        if HAS_MULTIMEDIA and self._player:
            self._player.stop()
            self._is_playing = False
            self.preview_btn.setText("▶ Preview")
            self.preview_status.setText("")

        # Restore background music volume
        if self._bg_music_original_volume is not None:
            get_music_manager().set_volume(self._bg_music_original_volume)
            self._bg_music_original_volume = None

    def _on_playback_state_changed(self, state):
        """Handle playback state change."""
        if HAS_MULTIMEDIA:
            from PySide6.QtMultimedia import QMediaPlayer
            if state == QMediaPlayer.PlaybackState.StoppedState:
                self._is_playing = False
                self.preview_btn.setText("▶ Preview")
                self.preview_status.setText("")
                # Restore background music volume when track ends naturally
                if self._bg_music_original_volume is not None:
                    get_music_manager().set_volume(self._bg_music_original_volume)
                    self._bg_music_original_volume = None

    def _on_volume_changed(self, value: int):
        """Handle volume slider change."""
        if HAS_MULTIMEDIA and self._audio_output:
            self._audio_output.setVolume(value / 100.0)

    def closeEvent(self, event):
        """Clean up when dialog closes."""
        self._stop_preview()
        super().closeEvent(event)

    def reject(self):
        """Clean up when dialog is rejected/cancelled."""
        self._stop_preview()
        super().reject()

    def get_selected_track(self) -> Optional[SoundbyteTrack]:
        """Get the selected track."""
        return self.selected_track


class GameFolderSelectDialog(QDialog):
    """Dialog to select a game folder to save the soundbyte to."""

    def __init__(self, output_dir: Path, suggested_name: str = "", parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self.selected_path: Optional[Path] = None

        self.setWindowTitle("Select Game Folder")
        self.setMinimumSize(500, 500)
        self.setModal(True)

        self._setup_ui(suggested_name)
        self._scan_library()

    def _setup_ui(self, suggested_name: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Select a game to add the soundbyte to:")
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
        self.game_tree.setHeaderLabels(["Platform / Game", "Has Music"])
        self.game_tree.setColumnWidth(0, 350)
        self.game_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.game_tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.game_tree, 1)

        # Create new folder section
        new_frame = QFrame()
        new_frame.setObjectName("card")
        new_layout = QVBoxLayout(new_frame)

        new_header = QLabel("Or create a new game folder:")
        new_header.setObjectName("label_card_title")
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

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.select_btn = QPushButton("Select")
        self.select_btn.setObjectName("btn_primary")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.select_btn)

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

                # Check if it already has music
                has_music = any(
                    (game_folder / f"music{ext}").exists()
                    for ext in [".mp3", ".ogg", ".flac", ".wav"]
                )

                game_item = QTreeWidgetItem([game_folder.name, "✓" if has_music else ""])
                game_item.setData(0, Qt.UserRole, game_folder)
                if has_music:
                    game_item.setForeground(1, Qt.green)
                platform_item.addChild(game_item)
                self._all_items.append((game_item, game_folder.name.lower()))
                game_count += 1

            if game_count > 0:
                platform_item.setText(0, f"{platform_folder.name} ({game_count})")
                self.game_tree.addTopLevelItem(platform_item)

        self.game_tree.expandAll()

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
            # Kept inline: dynamic runtime status color change (success green)
            self.selected_label.setStyleSheet("color: #4CAF50;")
            self.select_btn.setEnabled(True)

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
            # Kept inline: dynamic runtime status color change (success green)
            self.selected_label.setStyleSheet("color: #4CAF50;")
            self.select_btn.setEnabled(True)
            # Refresh the tree
            self._scan_library()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create folder:\n{e}")

    def get_selected_path(self) -> Optional[Path]:
        """Get the selected game folder path."""
        return self.selected_path


class SoundbyteTab(QWidget):
    """Tab for browsing and downloading game soundbytes."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.config_path = str(get_config_path())
        self.scraper = KHInsiderScraper()
        self._current_albums: List[SoundbyteAlbum] = []
        self._album_cards: List[AlbumCard] = []
        self._selected_game_path: Optional[Path] = None  # Pre-selected target game folder

        # Create signals for thread communication
        self._signals = WorkerSignals()
        self._signals.search_complete.connect(self._on_search_complete)
        self._signals.search_error.connect(self._on_search_error)
        self._signals.download_complete.connect(self._on_download_complete)
        self._signals.download_error.connect(self._on_download_error)
        self._signals.cover_loaded.connect(self._on_cover_loaded)

        self._load_config()
        self._setup_ui()

    def _on_cover_loaded(self, card, pixmap):
        """Handle cover loaded from background thread."""
        try:
            if card and pixmap and card in self._album_cards:
                card.set_cover(pixmap)
        except RuntimeError:
            pass  # Widget was deleted

    def _load_config(self):
        """Load soundbyte config."""
        self.max_duration = 180
        self.output_format = "mp3"
        self.preferred_tracks = ["title", "main theme", "menu", "stage 1", "overworld"]
        self.output_dir = Path("./output")

        try:
            cfg = get_config()

            sb_cfg = cfg.get("soundbytes", {})
            self.max_duration = sb_cfg.get("max_duration_seconds", 180)
            self.output_format = sb_cfg.get("output_format", "mp3")
            self.preferred_tracks = sb_cfg.get("preferred_tracks", self.preferred_tracks)

            # Load output directory from paths config
            self.output_dir = Path(cfg.get("paths", {}).get("output_dir", "./output"))
        except Exception as e:
            print(f"Error loading config: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header card
        header_card = QFrame()
        header_card.setObjectName("header_card")
        header_layout = QVBoxLayout(header_card)

        title_row = QHBoxLayout()
        title = QLabel("Soundbyte Browser")
        title.setObjectName("label_header")
        title_row.addWidget(title)
        title_row.addStretch()
        header_layout.addLayout(title_row)

        desc = QLabel("Search and download game music from KHInsider for iiSU hover sounds.")
        desc.setObjectName("label_muted")
        header_layout.addWidget(desc)

        layout.addWidget(header_card)

        # Search section
        search_card = QFrame()
        search_card.setObjectName("card")
        search_layout = QVBoxLayout(search_card)

        search_header = QLabel("Search for Soundtracks")
        search_header.setObjectName("label_card_title")
        search_layout.addWidget(search_header)

        # Search row
        search_row = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search for Soundtracks")
        self.search_input.setMinimumHeight(40)
        self.search_input.returnPressed.connect(self._search)
        search_row.addWidget(self.search_input, 1)

        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("btn_primary")
        self.search_btn.setMinimumHeight(40)
        self.search_btn.setMinimumWidth(100)
        self.search_btn.clicked.connect(self._search)
        search_row.addWidget(self.search_btn)

        search_layout.addLayout(search_row)

        # Target game selection row
        game_row = QHBoxLayout()

        game_row.addWidget(QLabel("Save to:"))
        self.selected_game_label = QLabel("No game selected")
        self.selected_game_label.setObjectName("label_muted")
        self.selected_game_label.setToolTip("Click 'Select Game' to choose where the soundbyte will be saved")
        game_row.addWidget(self.selected_game_label, 1)

        self.select_game_btn = QPushButton("Select Game...")
        self.select_game_btn.setObjectName("btn_secondary")
        self.select_game_btn.setToolTip("Choose which game folder to save the soundbyte to")
        self.select_game_btn.clicked.connect(self._select_target_game)
        game_row.addWidget(self.select_game_btn)

        self.clear_game_btn = QPushButton("×")
        self.clear_game_btn.setFixedWidth(30)
        self.clear_game_btn.setToolTip("Clear game selection")
        self.clear_game_btn.clicked.connect(self._clear_target_game)
        self.clear_game_btn.setVisible(False)
        game_row.addWidget(self.clear_game_btn)

        search_layout.addLayout(game_row)

        layout.addWidget(search_card)

        # Results section
        results_card = QFrame()
        results_card.setObjectName("card")
        results_layout = QVBoxLayout(results_card)

        results_header = QHBoxLayout()
        self.results_label = QLabel("Search for a game to see soundtracks")
        self.results_label.setObjectName("label_card_title")
        results_header.addWidget(self.results_label)
        results_header.addStretch()
        results_layout.addLayout(results_header)

        # Albums grid in scroll area with flow layout
        self.albums_scroll = QScrollArea()
        self.albums_scroll.setWidgetResizable(True)
        self.albums_scroll.setMinimumHeight(300)

        self.albums_widget = QWidget()
        self.albums_grid = FlowLayout(self.albums_widget, margin=6, spacing=12)

        self.albums_scroll.setWidget(self.albums_widget)
        results_layout.addWidget(self.albums_scroll, 1)

        layout.addWidget(results_card, 1)

        # Status bar
        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("label_muted")
        status_row.addWidget(self.status_label)

        status_row.addStretch()

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        status_row.addWidget(self.progress_bar)

        layout.addLayout(status_row)

    def _search(self):
        """Perform search."""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Search", "Please enter a game name")
            return

        self.search_btn.setEnabled(False)
        self.status_label.setText(f"Searching for '{query}'...")
        self.results_label.setText("Searching...")

        # Clear current results
        self._clear_albums()

        signals = self._signals

        def search_thread():
            try:
                result = self.scraper.search_game(query)
                signals.search_complete.emit(result)
            except Exception as e:
                signals.search_error.emit(str(e))

        thread = threading.Thread(target=search_thread)
        thread.daemon = True
        thread.start()

    def _on_search_complete(self, result: SoundbyteSearchResult):
        """Handle search complete."""
        self.search_btn.setEnabled(True)

        if result.error:
            self.status_label.setText(f"Error: {result.error}")
            # Kept inline: dynamic runtime status color change (error red)
            self.status_label.setStyleSheet("color: #E53935;")
            self.results_label.setText("Search failed")
            return

        self._current_albums = result.albums

        if not result.albums:
            self.status_label.setText("No results found")
            # Kept inline: dynamic runtime status color change (warning yellow)
            self.status_label.setStyleSheet("color: #FFB300;")
            self.results_label.setText("No soundtracks found")
            return

        self.status_label.setText(f"Found {len(result.albums)} album(s)")
        # Kept inline: dynamic runtime status color change (success green)
        self.status_label.setStyleSheet("color: #4CAF50;")
        self.results_label.setText(f"Found {len(result.albums)} Soundtrack(s)")

        # Display albums
        self._display_albums(result.albums)

    def _on_search_error(self, error: str):
        """Handle search error."""
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Error: {error}")
        # Kept inline: dynamic runtime status color change (error red)
        self.status_label.setStyleSheet("color: #E53935;")
        self.results_label.setText("Search failed")

    def _clear_albums(self):
        """Clear the albums grid."""
        for card in self._album_cards:
            card.deleteLater()
        self._album_cards.clear()

        while self.albums_grid.count():
            item = self.albums_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _display_albums(self, albums: List[SoundbyteAlbum]):
        """Display albums in the grid."""
        self._clear_albums()

        for i, album in enumerate(albums):
            card = AlbumCard(album)
            card.selected.connect(self._on_album_selected)
            self._album_cards.append(card)
            self.albums_grid.addWidget(card)

        # Load all covers in parallel for speed
        self._load_all_covers_parallel()

    def _load_all_covers_parallel(self):
        """Load all album covers in parallel for speed."""
        from concurrent.futures import ThreadPoolExecutor

        signals = self._signals
        scraper = self.scraper

        def load_cover(card: AlbumCard):
            """Load a single cover."""
            album = card.album
            try:
                # Get album details (uses cache if available)
                detailed = scraper.get_album_details(album)

                if detailed.cover_url:
                    response = requests.get(detailed.cover_url, timeout=5)
                    if response.status_code == 200:
                        image = QImage()
                        image.loadFromData(response.content)
                        pixmap = QPixmap.fromImage(image)
                        # Update UI from main thread via signal
                        signals.cover_loaded.emit(card, pixmap)

                # Update album with track count
                album.track_count = detailed.track_count
                album.tracks = detailed.tracks

            except Exception as e:
                pass  # Silently fail for covers

        def load_all():
            # Use thread pool for parallel loading
            with ThreadPoolExecutor(max_workers=6) as executor:
                executor.map(load_cover, self._album_cards)

        thread = threading.Thread(target=load_all)
        thread.daemon = True
        thread.start()

    def _load_album_cover(self, album: SoundbyteAlbum, card: AlbumCard):
        """Load album cover in background (single album version)."""
        signals = self._signals
        scraper = self.scraper

        def load():
            try:
                # First get album details to get cover URL
                detailed = scraper.get_album_details(album)

                if detailed.cover_url:
                    response = requests.get(detailed.cover_url, timeout=5)
                    if response.status_code == 200:
                        image = QImage()
                        image.loadFromData(response.content)
                        pixmap = QPixmap.fromImage(image)
                        signals.cover_loaded.emit(card, pixmap)

                # Update album with track count
                album.track_count = detailed.track_count
                album.tracks = detailed.tracks

            except Exception as e:
                print(f"Error loading cover: {e}")

        thread = threading.Thread(target=load)
        thread.daemon = True
        thread.start()

    def _on_album_selected(self, album: SoundbyteAlbum):
        """Handle album selection."""
        # Update selection state
        for card in self._album_cards:
            card.set_selected(card.album == album)

        # Show track selection dialog
        dialog = TrackPreviewDialog(album, self.scraper, self)

        if dialog.exec() == QDialog.Accepted:
            track = dialog.get_selected_track()
            if track:
                self._download_track(album, track)

    def _download_track(self, album: SoundbyteAlbum, track: SoundbyteTrack):
        """Download a track as soundbyte to a game folder."""
        # Use pre-selected game if available, otherwise show dialog
        if self._selected_game_path:
            game_folder = self._selected_game_path
        else:
            # Show game folder selection dialog
            dialog = GameFolderSelectDialog(
                self.output_dir,
                suggested_name=album.game_name,
                parent=self
            )

            if dialog.exec() != QDialog.Accepted:
                return

            game_folder = dialog.get_selected_path()
            if not game_folder:
                return

        # Determine file extension from URL or default to mp3
        file_ext = ".mp3"
        if track.url:
            if ".flac" in track.url.lower():
                file_ext = ".flac"
            elif ".ogg" in track.url.lower():
                file_ext = ".ogg"
            elif ".wav" in track.url.lower():
                file_ext = ".wav"

        # Save as music.mp3 (or appropriate extension)
        file_path = str(game_folder / f"music{file_ext}")

        # Check if file already exists
        if Path(file_path).exists():
            reply = QMessageBox.question(
                self, "File Exists",
                f"This game already has a soundbyte:\n{file_path}\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.status_label.setText(f"Downloading: {track.title}...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate

        signals = self._signals
        scraper = self.scraper

        def download():
            try:
                # Get actual download URL
                download_url = scraper.get_track_download_url(track)

                if not download_url:
                    signals.download_error.emit("Could not get download URL")
                    return

                # Download the file
                response = requests.get(download_url, timeout=60, stream=True)
                response.raise_for_status()

                # Save to file
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                signals.download_complete.emit(file_path, track)

            except Exception as e:
                signals.download_error.emit(str(e))

        thread = threading.Thread(target=download)
        thread.daemon = True
        thread.start()

    def _on_download_complete(self, file_path: str, track: SoundbyteTrack):
        """Handle download complete."""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Downloaded: {track.title}")
        # Kept inline: dynamic runtime status color change (success green)
        self.status_label.setStyleSheet("color: #4CAF50;")

        # Get the game folder name from the path
        game_folder = Path(file_path).parent.name

        QMessageBox.information(
            self, "Download Complete",
            f"Soundbyte saved!\n\n"
            f"Game: {game_folder}\n"
            f"Track: {track.title}\n"
            f"Duration: {track.duration or 'Unknown'}\n\n"
            f"Location: {file_path}"
        )

    def _on_download_error(self, error: str):
        """Handle download error."""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Download failed: {error}")
        # Kept inline: dynamic runtime status color change (error red)
        self.status_label.setStyleSheet("color: #E53935;")

        QMessageBox.critical(
            self, "Download Failed",
            f"Could not download track:\n{error}"
        )

    def _select_target_game(self):
        """Show dialog to select target game folder."""
        dialog = GameFolderSelectDialog(
            self.output_dir,
            suggested_name=self.search_input.text().strip(),
            parent=self
        )

        if dialog.exec() == QDialog.Accepted:
            game_folder = dialog.get_selected_path()
            if game_folder:
                self._selected_game_path = game_folder
                self.selected_game_label.setText(f"{game_folder.parent.name}/{game_folder.name}")
                # Kept inline: dynamic runtime status color change (success green)
                self.selected_game_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.clear_game_btn.setVisible(True)

    def _clear_target_game(self):
        """Clear the selected target game."""
        self._selected_game_path = None
        self.selected_game_label.setText("No game selected")
        self.selected_game_label.setStyleSheet("")  # Reset to QSS objectName styling (label_muted)
        self.clear_game_btn.setVisible(False)

    def search_for_game(self, game_name: str, platform: Optional[str] = None):
        """
        Public method to search for a specific game.
        Called from other tabs when generating assets.
        """
        self.search_input.setText(game_name)

        if platform:
            # Find matching platform in combo
            for i in range(self.platform_combo.count()):
                if self.platform_combo.itemData(i) == platform.lower():
                    self.platform_combo.setCurrentIndex(i)
                    break

        self._search()
