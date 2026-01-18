"""
Interactive artwork picker dialog.
Displays artwork options from all sources for manual selection.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QComboBox, QButtonGroup, QRadioButton,
    QGridLayout
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from io import BytesIO
from PIL import Image


class ArtworkOption(QFrame):
    """Widget displaying a single artwork option with radio button."""

    def __init__(self, image_data: bytes, source: str, index: int, parent=None):
        super().__init__(parent)
        self.image_data = image_data
        self.source = source
        self.index = index

        self.setFrameShape(QFrame.Box)
        self.setLineWidth(2)
        self.setStyleSheet("""
            ArtworkOption {
                border: 2px solid #3A4048;
                border-radius: 8px;
                background-color: #2D3238;
                padding: 8px;
            }
            ArtworkOption:hover {
                border-color: #00DDFF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Preview image
        self.image_label = QLabel()
        self.image_label.setFixedSize(256, 256)
        self.image_label.setScaledContents(True)
        self.image_label.setAlignment(Qt.AlignCenter)

        # Load image
        try:
            pil_img = Image.open(BytesIO(image_data))
            # Convert to RGB if needed
            if pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')

            # Save to bytes for Qt
            img_bytes = BytesIO()
            pil_img.save(img_bytes, format='PNG')
            img_bytes.seek(0)

            pixmap = QPixmap()
            pixmap.loadFromData(img_bytes.read())
            self.image_label.setPixmap(pixmap)
        except Exception as e:
            self.image_label.setText(f"Error loading\nimage: {e}")

        layout.addWidget(self.image_label)

        # Source label
        source_label = QLabel(f"Source: {source}")
        source_label.setAlignment(Qt.AlignCenter)
        source_label.setStyleSheet("color: #00DDFF; font-weight: bold;")
        layout.addWidget(source_label)

        # Radio button
        self.radio = QRadioButton(f"Select #{index + 1}")
        self.radio.setStyleSheet("QRadioButton { color: #E9E9E9; }")
        layout.addWidget(self.radio, alignment=Qt.AlignCenter)

    def mousePressEvent(self, event):
        """Allow clicking anywhere on the widget to select it."""
        if event.button() == Qt.LeftButton:
            self.radio.setChecked(True)
        super().mousePressEvent(event)


class ArtworkPickerDialog(QDialog):
    """
    Interactive dialog for selecting artwork from multiple sources.
    """

    def __init__(self, title: str, platform: str, artwork_options: List[Dict[str, Any]], parent=None):
        """
        Args:
            title: Game title
            platform: Platform key
            artwork_options: List of dicts with keys: 'image_data' (bytes), 'source' (str)
        """
        super().__init__(parent)
        self.title = title
        self.platform = platform
        self.artwork_options = artwork_options
        self.selected_index = None

        self.setWindowTitle(f"Select Artwork - {title}")
        self.setMinimumSize(900, 700)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Header
        header = QLabel(f"<b>{self.title}</b> ({self.platform})")
        header.setStyleSheet("font-size: 16px; color: #E9E9E9;")
        layout.addWidget(header)

        if len(self.artwork_options) == 1:
            info = QLabel(f"Found artwork from: <b>{self.artwork_options[0]['source']}</b>")
            info.setStyleSheet("color: #00DDFF; font-size: 14px;")
        else:
            info = QLabel(f"Found {len(self.artwork_options)} artwork option(s). Select one:")
            info.setStyleSheet("color: #B0B0B0;")
        layout.addWidget(info)

        # Source filter (only show if multiple options)
        if len(self.artwork_options) > 1:
            filter_layout = QHBoxLayout()
            filter_layout.addWidget(QLabel("Filter by source:"))

            self.source_filter = QComboBox()
            self.source_filter.addItem("All Sources")

            # Get unique sources
            sources = sorted(set(opt['source'] for opt in self.artwork_options))
            self.source_filter.addItems(sources)
            self.source_filter.currentIndexChanged.connect(self._apply_filter)

            filter_layout.addWidget(self.source_filter)
            filter_layout.addStretch()

            layout.addLayout(filter_layout)
        else:
            self.source_filter = None

        # Scrollable artwork grid
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        scroll_area.setWidget(self.grid_widget)
        layout.addWidget(scroll_area, 1)

        # Button group for radio buttons
        self.button_group = QButtonGroup(self)

        # Create artwork options in a grid (3 columns)
        self.artwork_widgets = []
        self.num_columns = 3
        for i, opt in enumerate(self.artwork_options):
            widget = ArtworkOption(
                image_data=opt['image_data'],
                source=opt['source'],
                index=i,
                parent=self.grid_widget
            )
            row = i // self.num_columns
            col = i % self.num_columns
            self.grid_layout.addWidget(widget, row, col)
            self.button_group.addButton(widget.radio, i)
            self.artwork_widgets.append(widget)

        # Select first option by default
        if self.artwork_widgets:
            self.artwork_widgets[0].radio.setChecked(True)

        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        btn_skip = QPushButton("Skip This Title")
        btn_skip.setToolTip("Skip this title and continue to next")
        btn_skip.clicked.connect(self.reject)
        button_layout.addWidget(btn_skip)

        if len(self.artwork_options) == 1:
            btn_select = QPushButton("Accept & Continue")
            btn_select.setToolTip("Accept this artwork and continue to next title")
        else:
            btn_select = QPushButton("Use Selected Artwork")
            btn_select.setToolTip("Use the selected artwork option")
        btn_select.setDefault(True)
        btn_select.clicked.connect(self.accept)
        button_layout.addWidget(btn_select)

        btn_cancel = QPushButton("Cancel All")
        btn_cancel.setToolTip("Stop interactive mode completely")
        btn_cancel.clicked.connect(self._cancel_all)
        button_layout.addWidget(btn_cancel)

        layout.addLayout(button_layout)

    def _apply_filter(self):
        """Filter artwork options by selected source and re-layout grid."""
        filter_text = self.source_filter.currentText()

        # Remove all widgets from grid
        for widget in self.artwork_widgets:
            self.grid_layout.removeWidget(widget)
            widget.hide()

        # Re-add visible widgets in grid order
        visible_idx = 0
        for widget in self.artwork_widgets:
            if filter_text == "All Sources" or widget.source == filter_text:
                row = visible_idx // self.num_columns
                col = visible_idx % self.num_columns
                self.grid_layout.addWidget(widget, row, col)
                widget.show()
                visible_idx += 1

    def _cancel_all(self):
        """Cancel interactive mode completely."""
        self.selected_index = -1  # Special value to indicate cancel all
        self.reject()

    def accept(self):
        """Store selected index and close."""
        checked_id = self.button_group.checkedId()
        if checked_id >= 0:
            self.selected_index = checked_id
        super().accept()

    def get_selected_index(self) -> Optional[int]:
        """
        Get the selected artwork index.
        Returns:
            Index of selected artwork, None if skipped, -1 if cancelled all
        """
        return self.selected_index
