"""
Interactive artwork picker dialog.
Displays artwork options from all sources for manual selection.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QComboBox, QButtonGroup, QRadioButton,
    QGridLayout, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from io import BytesIO
from PIL import Image, ImageOps
from iisu_image_utils import safe_load_image


class ArtworkOption(QFrame):
    """Widget displaying a single artwork option with radio button."""

    crop_requested = Signal(int)  # Emits index when crop button is clicked

    def __init__(self, image_data: bytes, source: str, index: int, parent=None, asset_type: str = "icon"):
        super().__init__(parent)
        self.image_data = image_data
        self.source = source
        self.index = index
        self.asset_type = asset_type  # 'icon', 'hero', 'logo', 'screenshot'
        self.image_width = 0
        self.image_height = 0
        self.is_square = True

        self.setFrameShape(QFrame.Box)
        self.setLineWidth(2)
        # ArtworkOption styling is handled via QSS theme files

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # Preview image - adjust size based on asset type
        self.image_label = QLabel()
        if asset_type == "hero":
            # Hero images are wide (3.1:1 aspect ratio typical)
            self.image_label.setFixedSize(310, 100)
        elif asset_type == "logo":
            # Logos can be various sizes, use moderate square
            self.image_label.setFixedSize(200, 200)
        else:
            # Icons and screenshots use square preview
            self.image_label.setFixedSize(256, 256)
        self.image_label.setScaledContents(True)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setObjectName("card")

        # Load image
        try:
            pil_img = safe_load_image(image_data)
            self.image_width, self.image_height = pil_img.size
            self.is_square = self.image_width == self.image_height

            # For logos, preserve alpha channel; for others convert to RGB
            if asset_type == "logo":
                # Keep RGBA for logos (they often have transparency)
                if pil_img.mode not in ('RGB', 'RGBA'):
                    pil_img = pil_img.convert('RGBA')
            else:
                # Convert to RGB for icons, heroes, screenshots
                if pil_img.mode != 'RGB':
                    # Handle RGBA -> RGB by compositing over white background
                    if pil_img.mode == 'RGBA':
                        background = Image.new('RGB', pil_img.size, (255, 255, 255))
                        background.paste(pil_img, mask=pil_img.split()[3])
                        pil_img = background
                    else:
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

        layout.addWidget(self.image_label, alignment=Qt.AlignCenter)

        # Dimensions label
        dims_text = f"{self.image_width}x{self.image_height}"
        if not self.is_square:
            aspect = self.image_width / self.image_height if self.image_height > 0 else 1
            dims_text += f" ({aspect:.2f}:1)"
        dims_label = QLabel(dims_text)
        dims_label.setAlignment(Qt.AlignCenter)
        if not self.is_square:
            dims_label.setObjectName("label_warning")
        else:
            dims_label.setObjectName("label_muted")
        layout.addWidget(dims_label)

        # Source label (shortened)
        short_source = source
        if len(source) > 30:
            short_source = source[:27] + "..."
        source_label = QLabel(short_source)
        source_label.setAlignment(Qt.AlignCenter)
        source_label.setToolTip(source)
        source_label.setObjectName("label_accent")
        layout.addWidget(source_label)

        # Button row
        button_row = QHBoxLayout()
        button_row.setSpacing(4)

        # Radio button (uses global QSS styling)
        self.radio = QRadioButton(f"#{index + 1}")
        button_row.addWidget(self.radio)

        button_row.addStretch()

        # Crop button:
        # - Show for icons when non-square
        # - Show for heroes (crop to 1920x620)
        # - Never show for logos (transparent images shouldn't be cropped)
        # - Show for screenshots when non-square
        show_crop = False
        if asset_type == "logo":
            show_crop = False  # Never show crop for logos
        elif asset_type == "hero":
            # Show crop for heroes that aren't the ideal aspect ratio
            ideal_hero_aspect = 1920 / 620  # ~3.1
            current_aspect = self.image_width / self.image_height if self.image_height > 0 else 1
            # Allow some tolerance
            show_crop = abs(current_aspect - ideal_hero_aspect) > 0.2
        else:
            # Icons and screenshots: show crop if not square
            show_crop = not self.is_square

        if show_crop:
            self.crop_btn = QPushButton("Crop")
            if asset_type == "hero":
                self.crop_btn.setToolTip("Crop to 1920x620 hero dimensions")
            else:
                self.crop_btn.setToolTip("Crop this image to a square")
            self.crop_btn.setObjectName("btn_warning")
            self.crop_btn.clicked.connect(lambda: self.crop_requested.emit(self.index))
            button_row.addWidget(self.crop_btn)
        else:
            self.crop_btn = None

        layout.addLayout(button_row)

    def update_image_data(self, new_data: bytes):
        """Update the image data after cropping."""
        self.image_data = new_data

        # Reload image
        try:
            pil_img = safe_load_image(new_data)
            self.image_width, self.image_height = pil_img.size
            self.is_square = self.image_width == self.image_height

            # For logos, preserve alpha channel; for others convert to RGB
            if self.asset_type == "logo":
                if pil_img.mode not in ('RGB', 'RGBA'):
                    pil_img = pil_img.convert('RGBA')
            else:
                if pil_img.mode != 'RGB':
                    if pil_img.mode == 'RGBA':
                        background = Image.new('RGB', pil_img.size, (255, 255, 255))
                        background.paste(pil_img, mask=pil_img.split()[3])
                        pil_img = background
                    else:
                        pil_img = pil_img.convert('RGB')

            # Save to bytes for Qt
            img_bytes = BytesIO()
            pil_img.save(img_bytes, format='PNG')
            img_bytes.seek(0)

            pixmap = QPixmap()
            pixmap.loadFromData(img_bytes.read())
            self.image_label.setPixmap(pixmap)

            # Hide crop button if now square
            if self.crop_btn and self.is_square:
                self.crop_btn.hide()

        except Exception as e:
            print(f"Error updating image: {e}")

    def mousePressEvent(self, event):
        """Allow clicking anywhere on the widget to select it."""
        if event.button() == Qt.LeftButton:
            self.radio.setChecked(True)
        super().mousePressEvent(event)


class ArtworkPickerDialog(QDialog):
    """
    Interactive dialog for selecting artwork from multiple sources.
    Supports icons, heroes, logos, and screenshots.
    """

    # Signal emitted when filter changes (bool: True = square only, False = all)
    filter_changed = Signal(bool)

    # Asset type display names
    ASSET_TYPE_NAMES = {
        "icon": "Icon",
        "hero": "Hero Image",
        "logo": "Logo",
        "screenshot": "Screenshot",
        None: "Artwork"  # Default
    }

    def __init__(self, title: str, platform: str, artwork_options: List[Dict[str, Any]],
                 parent=None, asset_type: str = None, show_filter: bool = False,
                 on_filter_changed=None):
        """
        Args:
            title: Game title
            platform: Platform key
            artwork_options: List of dicts with keys: 'image_data' (bytes), 'source' (str)
            asset_type: Type of asset being selected ('icon', 'hero', 'logo', 'screenshot')
            show_filter: Whether to show the square/all filter toggle (only for icons)
            on_filter_changed: Callback when filter changes (receives bool: True = square only)
        """
        super().__init__(parent)
        self.title = title
        self.platform = platform
        self.artwork_options = artwork_options
        self.asset_type = asset_type
        self.selected_index = None
        self.show_filter = show_filter and asset_type == "icon"
        self.on_filter_changed = on_filter_changed
        self.is_square_only = True  # Default to square only

        type_name = self.ASSET_TYPE_NAMES.get(asset_type, "Artwork")
        self.setWindowTitle(f"Select {type_name} - {title}")
        self.setMinimumSize(900, 700)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Header
        header = QLabel(f"<b>{self.title}</b> ({self.platform})")
        header.setObjectName("label_header")
        layout.addWidget(header)

        if len(self.artwork_options) == 1:
            info = QLabel(f"Found artwork from: <b>{self.artwork_options[0]['source']}</b>")
            info.setObjectName("label_accent")
        else:
            info = QLabel(f"Found {len(self.artwork_options)} artwork option(s). Select one:")
            info.setObjectName("label_muted")
        layout.addWidget(info)

        # Square filter toggle (only for icons)
        if self.show_filter:
            filter_toggle_layout = QHBoxLayout()

            filter_label = QLabel("Filter:")
            filter_label.setObjectName("label_muted")
            filter_toggle_layout.addWidget(filter_label)

            # Create toggle buttons for Square Only / All Results
            self.btn_square_only = QPushButton("Square Only")
            self.btn_square_only.setCheckable(True)
            self.btn_square_only.setChecked(True)
            self.btn_square_only.setObjectName("filter_chip")
            self.btn_square_only.clicked.connect(self._on_square_only_clicked)
            filter_toggle_layout.addWidget(self.btn_square_only)

            self.btn_all_results = QPushButton("All Results")
            self.btn_all_results.setCheckable(True)
            self.btn_all_results.setChecked(False)
            self.btn_all_results.setObjectName("filter_chip")
            self.btn_all_results.clicked.connect(self._on_all_results_clicked)
            filter_toggle_layout.addWidget(self.btn_all_results)

            # Info button
            info_btn = QPushButton("?")
            info_btn.setFixedSize(24, 24)
            info_btn.setToolTip("Square icons work best with iiSU borders.\nNon-square images will need to be cropped.")
            info_btn.setObjectName("filter_chip")
            filter_toggle_layout.addWidget(info_btn)

            filter_toggle_layout.addStretch()
            layout.addLayout(filter_toggle_layout)

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

        # Create artwork options in a grid
        # Adjust columns based on asset type (heroes are wider)
        self.artwork_widgets = []
        if self.asset_type == "hero":
            self.num_columns = 2  # Fewer columns for wide hero previews
        else:
            self.num_columns = 3

        for i, opt in enumerate(self.artwork_options):
            widget = ArtworkOption(
                image_data=opt['image_data'],
                source=opt['source'],
                index=i,
                parent=self.grid_widget,
                asset_type=self.asset_type
            )
            self.button_group.addButton(widget.radio, i)
            widget.crop_requested.connect(self._on_crop_requested)
            self.artwork_widgets.append(widget)

        # Apply initial layout with square filter if enabled
        self._apply_initial_layout()

        # Select first VISIBLE option by default
        self._select_first_visible()

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
        """Filter artwork options by selected source (and square filter if enabled) and re-layout grid."""
        filter_text = self.source_filter.currentText() if self.source_filter else "All Sources"

        # Remove all widgets from grid
        for widget in self.artwork_widgets:
            self.grid_layout.removeWidget(widget)
            widget.hide()

        # Re-add visible widgets in grid order
        visible_idx = 0
        for widget in self.artwork_widgets:
            # Check source filter
            source_match = (filter_text == "All Sources" or widget.source == filter_text)

            # Check square filter (only if show_filter is enabled)
            if self.show_filter and self.is_square_only:
                square_match = widget.is_square
            else:
                square_match = True

            if source_match and square_match:
                row = visible_idx // self.num_columns
                col = visible_idx % self.num_columns
                self.grid_layout.addWidget(widget, row, col)
                widget.show()
                visible_idx += 1

    def _cancel_all(self):
        """Cancel interactive mode completely."""
        self.selected_index = -1  # Special value to indicate cancel all
        self.reject()

    def _on_crop_requested(self, index: int):
        """Handle crop button click."""
        if index < 0 or index >= len(self.artwork_widgets):
            return

        widget = self.artwork_widgets[index]

        # Import and show the crop dialog
        try:
            from grid_crop_dialog import GridCropDialog

            # Determine target dimensions based on asset type
            if self.asset_type == "hero":
                # Hero images use 1920x620 dimensions
                target_width = 1920
                target_height = 620
            else:
                # Icons and screenshots use square (1024x1024)
                target_width = 1024
                target_height = 1024

            # Show crop dialog with appropriate dimensions
            cropped_bytes = GridCropDialog.crop_image(
                image_bytes=widget.image_data,
                source_tag=widget.source,
                parent=self,
                target_width=target_width,
                target_height=target_height
            )

            if cropped_bytes:
                # Update the widget with cropped image
                widget.update_image_data(cropped_bytes)

                # Update the artwork_options list too
                self.artwork_options[index]['image_data'] = cropped_bytes

                # Select the cropped option
                widget.radio.setChecked(True)

        except ImportError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Crop Error",
                f"Could not load crop dialog module:\n{e}"
            )
        except Exception as e:
            import traceback
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Crop Error",
                f"Error during crop operation:\n{e}\n\n{traceback.format_exc()}"
            )

    def accept(self):
        """Store selected index and close. For heroes, offer crop options first."""
        checked_id = self.button_group.checkedId()
        if checked_id < 0:
            super().accept()
            return

        self.selected_index = checked_id

        # For heroes, show crop options before accepting
        if self.asset_type == "hero":
            widget = self.artwork_widgets[checked_id]
            self._show_hero_crop_options(widget, checked_id)
        else:
            super().accept()

    def _show_hero_crop_options(self, widget, index: int):
        """Show crop position options after selecting a hero image."""
        img_w = widget.image_width
        img_h = widget.image_height

        dialog = QDialog(self)
        dialog.setWindowTitle("Hero Crop Position")
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        header = QLabel(f"<b>Selected image:</b> {img_w}×{img_h}")
        header.setObjectName("label_accent")
        layout.addWidget(header)

        info = QLabel("Choose crop position (crops to 1920×1080):")
        info.setObjectName("label_muted")
        layout.addWidget(info)

        # Option buttons
        btn_original = QPushButton(f"Use Original ({img_w}×{img_h})")
        btn_original.setToolTip("Keep the image exactly as-is, no cropping")
        btn_original.clicked.connect(lambda: self._apply_hero_crop_option(dialog, widget, index, None))
        layout.addWidget(btn_original)

        btn_left = QPushButton("Crop Left")
        btn_left.setToolTip("Crop to 1920×1080 from the left side of the image")
        btn_left.clicked.connect(lambda: self._apply_hero_crop_option(dialog, widget, index, (1920, 1080), 0.0))
        layout.addWidget(btn_left)

        btn_center = QPushButton("Crop Center")
        btn_center.setToolTip("Crop to 1920×1080 from the center of the image")
        btn_center.clicked.connect(lambda: self._apply_hero_crop_option(dialog, widget, index, (1920, 1080), 0.5))
        layout.addWidget(btn_center)

        btn_right = QPushButton("Crop Right")
        btn_right.setToolTip("Crop to 1920×1080 from the right side of the image")
        btn_right.clicked.connect(lambda: self._apply_hero_crop_option(dialog, widget, index, (1920, 1080), 1.0))
        layout.addWidget(btn_right)

        btn_custom = QPushButton("Custom Crop...")
        btn_custom.setToolTip("Open the interactive crop tool for manual adjustment")
        btn_custom.clicked.connect(lambda: self._apply_hero_custom_crop(dialog, widget, index))
        layout.addWidget(btn_custom)

        # Cancel — go back to picker
        btn_back = QPushButton("Go Back")
        btn_back.setObjectName("btn_warning")
        btn_back.clicked.connect(dialog.reject)
        layout.addWidget(btn_back)

        result = dialog.exec()
        # If rejected (Go Back), don't close the main picker — user can pick again

    def _apply_hero_crop_option(self, options_dialog, widget, index: int, dimensions, h_position=0.5):
        """Apply a preset crop to the selected hero and accept the picker.

        Args:
            h_position: Horizontal position (0.0=left, 0.5=center, 1.0=right)
        """
        if dimensions is None:
            # Use original — no crop needed
            options_dialog.accept()
            super(ArtworkPickerDialog, self).accept()
            return

        target_w, target_h = dimensions

        try:
            pil_img = safe_load_image(widget.image_data)
            pil_img = ImageOps.exif_transpose(pil_img).convert("RGBA")
            src_w, src_h = pil_img.size

            # Scale to cover target, then crop at specified position
            target_aspect = target_w / target_h
            src_aspect = src_w / src_h

            if src_aspect > target_aspect:
                # Source is wider — fit height, crop sides using h_position
                new_h = target_h
                new_w = int(src_w * (target_h / src_h))
            else:
                # Source is taller — fit width, crop top/bottom (centered vertically)
                new_w = target_w
                new_h = int(src_h * (target_w / src_w))

            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Crop using horizontal position for sides, center for vertical
            max_left = new_w - target_w
            left = int(max_left * h_position)
            max_top = new_h - target_h
            top = max_top // 2  # Always center vertically
            pil_img = pil_img.crop((left, top, left + target_w, top + target_h))

            # Save back to bytes
            buffer = BytesIO()
            pil_img.save(buffer, format="PNG")
            cropped_bytes = buffer.getvalue()

            # Update the widget and options
            widget.update_image_data(cropped_bytes)
            self.artwork_options[index]['image_data'] = cropped_bytes

            options_dialog.accept()
            super(ArtworkPickerDialog, self).accept()

        except Exception as e:
            QMessageBox.warning(
                self,
                "Crop Error",
                f"Failed to crop image:\n{e}"
            )

    def _apply_hero_custom_crop(self, options_dialog, widget, index: int):
        """Open the GridCropDialog for custom hero cropping, then accept."""
        try:
            from grid_crop_dialog import GridCropDialog

            cropped_bytes = GridCropDialog.crop_image(
                image_bytes=widget.image_data,
                source_tag=widget.source,
                parent=self,
                target_width=1920,
                target_height=1080
            )

            if cropped_bytes:
                widget.update_image_data(cropped_bytes)
                self.artwork_options[index]['image_data'] = cropped_bytes
                options_dialog.accept()
                super(ArtworkPickerDialog, self).accept()
            # If user cancelled the crop dialog, stay in options dialog

        except ImportError as e:
            QMessageBox.warning(self, "Crop Error", f"Could not load crop dialog:\n{e}")
        except Exception as e:
            QMessageBox.warning(self, "Crop Error", f"Error during crop:\n{e}")

    def get_selected_index(self) -> Optional[int]:
        """
        Get the selected artwork index.
        Returns:
            Index of selected artwork, None if skipped, -1 if cancelled all
        """
        return self.selected_index

    def _on_square_only_clicked(self):
        """Handle Square Only filter button click."""
        if not self.is_square_only:
            self.is_square_only = True
            self.btn_square_only.setChecked(True)
            self.btn_all_results.setChecked(False)
            self._trigger_filter_change()

    def _on_all_results_clicked(self):
        """Handle All Results filter button click."""
        if self.is_square_only:
            self.is_square_only = False
            self.btn_all_results.setChecked(True)
            self.btn_square_only.setChecked(False)
            self._trigger_filter_change()

    def _trigger_filter_change(self):
        """Trigger the filter change callback and apply the filter locally."""
        # Apply the filter to displayed items
        self._apply_square_filter()

        # Emit signal and call callback
        self.filter_changed.emit(self.is_square_only)
        if self.on_filter_changed:
            self.on_filter_changed(self.is_square_only)

    def _apply_square_filter(self):
        """Filter artwork options by square/non-square and re-layout grid."""
        # Get source filter if available
        source_filter = self.source_filter.currentText() if self.source_filter else "All Sources"

        # Remove all widgets from grid
        for widget in self.artwork_widgets:
            self.grid_layout.removeWidget(widget)
            widget.hide()

        # Re-add visible widgets in grid order
        visible_idx = 0
        for widget in self.artwork_widgets:
            # Check source filter
            source_match = (source_filter == "All Sources" or widget.source == source_filter)

            # Check square filter
            if self.is_square_only:
                square_match = widget.is_square
            else:
                square_match = True  # Show all when "All Results" is selected

            if source_match and square_match:
                row = visible_idx // self.num_columns
                col = visible_idx % self.num_columns
                self.grid_layout.addWidget(widget, row, col)
                widget.show()
                visible_idx += 1

        # Update info label if we have one
        if visible_idx == 0 and self.is_square_only:
            # No square images found - could show a message here
            pass

    def _apply_initial_layout(self):
        """Apply initial layout with square filter if enabled."""
        visible_idx = 0
        for widget in self.artwork_widgets:
            # Check square filter (only if show_filter is enabled and is_square_only)
            if self.show_filter and self.is_square_only:
                if not widget.is_square:
                    widget.hide()
                    continue

            row = visible_idx // self.num_columns
            col = visible_idx % self.num_columns
            self.grid_layout.addWidget(widget, row, col)
            widget.show()
            visible_idx += 1

    def _select_first_visible(self):
        """Select the first visible artwork option."""
        for widget in self.artwork_widgets:
            if widget.isVisible():
                widget.radio.setChecked(True)
                return
        # If no visible widgets, select first one anyway
        if self.artwork_widgets:
            self.artwork_widgets[0].radio.setChecked(True)

    def update_artwork_options(self, new_options: List[Dict[str, Any]]):
        """Update the artwork options with new results (e.g., after filter change)."""
        self.artwork_options = new_options

        # Clear existing widgets
        for widget in self.artwork_widgets:
            self.button_group.removeButton(widget.radio)
            self.grid_layout.removeWidget(widget)
            widget.deleteLater()
        self.artwork_widgets.clear()

        # Recreate widgets with new options
        for i, opt in enumerate(self.artwork_options):
            widget = ArtworkOption(
                image_data=opt['image_data'],
                source=opt['source'],
                index=i,
                parent=self.grid_widget,
                asset_type=self.asset_type
            )
            self.button_group.addButton(widget.radio, i)
            widget.crop_requested.connect(self._on_crop_requested)
            self.artwork_widgets.append(widget)

        # Apply layout with filter
        self._apply_initial_layout()

        # Select first VISIBLE option by default
        self._select_first_visible()

        # Update info label if source filter exists
        if self.source_filter:
            self.source_filter.clear()
            self.source_filter.addItem("All Sources")
            sources = sorted(set(opt['source'] for opt in self.artwork_options))
            self.source_filter.addItems(sources)
