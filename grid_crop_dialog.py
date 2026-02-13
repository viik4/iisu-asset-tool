"""
Grid Crop Dialog for iiSU Asset Tool
Allows cropping non-square artwork to a square format with visual preview.
Similar controls to custom_image_tab.py.
"""

from pathlib import Path
from typing import Optional, Tuple
from io import BytesIO

from PIL import Image, ImageOps, ImageQt, ImageChops
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QBrush, QColor, QCursor
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QSlider, QDoubleSpinBox, QDialogButtonBox, QFrame,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QSizePolicy
)


class CropPreviewView(QGraphicsView):
    """Interactive preview view for cropping with pan and zoom controls."""

    position_changed = Signal(float, float)  # delta_x, delta_y (normalized 0-1)
    zoom_changed = Signal(float)  # zoom delta

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # Setup view properties
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor(30, 33, 39))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)

        # Image item
        self.image_item: Optional[QGraphicsPixmapItem] = None

        # Drag state
        self.dragging = False
        self.last_pos = QPointF()

        # Arrow key step
        self.arrow_key_step = 0.01

    def set_image(self, pixmap: QPixmap):
        """Set the image to display."""
        self.scene.clear()
        self.image_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.image_item)
        self.fitInView(self.image_item, Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        """Start dragging."""
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.last_pos = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle drag movement."""
        if self.dragging:
            delta = event.position() - self.last_pos
            self.last_pos = event.position()

            # Normalize delta by viewport size
            viewport_size = min(self.viewport().width(), self.viewport().height())
            if viewport_size > 0:
                norm_dx = delta.x() / viewport_size
                norm_dy = delta.y() / viewport_size
                self.position_changed.emit(-norm_dx, -norm_dy)

            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End dragging."""
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """Handle zoom with scroll wheel."""
        delta = event.angleDelta().y()
        zoom_step = 0.05 if delta > 0 else -0.05
        self.zoom_changed.emit(zoom_step)
        event.accept()

    def keyPressEvent(self, event):
        """Handle arrow keys for fine positioning."""
        delta_x = 0.0
        delta_y = 0.0

        if event.key() == Qt.Key_Left:
            delta_x = self.arrow_key_step
        elif event.key() == Qt.Key_Right:
            delta_x = -self.arrow_key_step
        elif event.key() == Qt.Key_Up:
            delta_y = self.arrow_key_step
        elif event.key() == Qt.Key_Down:
            delta_y = -self.arrow_key_step
        else:
            super().keyPressEvent(event)
            return

        self.position_changed.emit(delta_x, delta_y)
        event.accept()

    def enterEvent(self, event):
        """Show open hand cursor when entering the view."""
        self.setCursor(Qt.OpenHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Reset cursor when leaving the view."""
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)


class GridCropDialog(QDialog):
    """
    Dialog for cropping artwork to specified dimensions.
    Supports square (icons) and wide (heroes) aspect ratios.
    """

    def __init__(self, image_bytes: bytes, source_tag: str = "", parent=None,
                 target_width: int = 1024, target_height: int = 1024):
        super().__init__(parent)

        # Target dimensions
        self.target_width = target_width
        self.target_height = target_height
        self.is_square = target_width == target_height
        self.target_aspect = target_width / target_height

        # Set window title based on target
        if self.is_square:
            self.setWindowTitle("Crop Artwork to Square")
        else:
            self.setWindowTitle(f"Crop Artwork to {target_width}x{target_height}")

        self.setMinimumSize(800, 600)

        # Load the image
        self.original_image = Image.open(BytesIO(image_bytes)).convert("RGBA")
        self.image_width, self.image_height = self.original_image.size

        # Source info
        self.source_tag = source_tag

        # Transform state - initialize zoom to cover mode (fill the frame)
        # This ensures cropped images don't have black borders by default
        zoom_w = self.target_width / self.image_width
        zoom_h = self.target_height / self.image_height
        self.zoom = max(zoom_w, zoom_h)  # Cover mode - fills the frame
        self.offset_x = 0.5  # Center by default
        self.offset_y = 0.5

        # Preview size - maintain target aspect ratio
        max_preview_dim = 450
        if self.target_aspect > 1:
            # Wide (hero)
            self.preview_width = max_preview_dim
            self.preview_height = int(max_preview_dim / self.target_aspect)
        else:
            # Tall or square
            self.preview_height = max_preview_dim
            self.preview_width = int(max_preview_dim * self.target_aspect)

        # Debounce timer
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._do_update_preview)
        self.debounce_ms = 30

        # Result storage
        self.cropped_bytes: Optional[bytes] = None

        self._setup_ui()
        self._do_update_preview()

    def _setup_ui(self):
        """Setup the dialog UI."""
        layout = QHBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Left panel - Preview
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)

        # Header with source info
        header_layout = QHBoxLayout()
        header = QLabel("Preview")
        header.setObjectName("label_header")
        header_layout.addWidget(header)
        header_layout.addStretch()
        left_panel.addLayout(header_layout)

        # Image dimensions info
        aspect_ratio = self.image_width / self.image_height if self.image_height > 0 else 1
        dims_label = QLabel(
            f"Original: {self.image_width}x{self.image_height} "
            f"(Aspect: {aspect_ratio:.2f}:1)"
        )
        dims_label.setObjectName("label_muted")
        left_panel.addWidget(dims_label)

        if self.source_tag:
            source_label = QLabel(f"Source: {self.source_tag}")
            source_label.setObjectName("label_accent")
            left_panel.addWidget(source_label)

        # Target dimensions info
        target_label = QLabel(
            f"Target: {self.target_width}x{self.target_height}"
        )
        target_label.setObjectName("label_muted")
        left_panel.addWidget(target_label)

        # Preview container with border indicating crop area
        preview_container = QFrame()
        preview_container.setFixedSize(self.preview_width + 4, self.preview_height + 4)
        preview_container.setObjectName("preview_card")
        preview_container_layout = QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)

        self.preview_view = CropPreviewView()
        self.preview_view.setFixedSize(self.preview_width, self.preview_height)
        self.preview_view.position_changed.connect(self._on_position_changed)
        self.preview_view.zoom_changed.connect(self._on_zoom_changed)
        preview_container_layout.addWidget(self.preview_view)

        left_panel.addWidget(preview_container, 0, Qt.AlignCenter)

        # Help text
        if self.is_square:
            help_msg = "Drag to pan | Scroll to zoom | Arrow keys for fine adjust\nThe blue border shows the final square crop area."
        else:
            help_msg = f"Drag to pan | Scroll to zoom | Arrow keys for fine adjust\nThe blue border shows the {self.target_width}x{self.target_height} crop area."
        help_text = QLabel(help_msg)
        help_text.setObjectName("label_muted")
        help_text.setAlignment(Qt.AlignCenter)
        left_panel.addWidget(help_text)

        left_panel.addStretch()

        layout.addLayout(left_panel, 1)

        # Right panel - Controls
        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)

        # Zoom control
        zoom_group = QGroupBox("Zoom")
        zoom_layout = QVBoxLayout(zoom_group)
        zoom_layout.setSpacing(8)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(8)

        # Calculate max zoom needed - at least 1000% or enough for cover mode + some extra
        max_zoom_pct = max(1000, int(self.zoom * 100) + 200)

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setMinimum(10)  # 10% = 0.1
        self.zoom_slider.setMaximum(max_zoom_pct)
        self.zoom_slider.setValue(int(self.zoom * 100))  # Use calculated cover zoom
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        zoom_row.addWidget(self.zoom_slider, 1)

        self.zoom_spinbox = QDoubleSpinBox()
        self.zoom_spinbox.setRange(10, max_zoom_pct)
        self.zoom_spinbox.setValue(self.zoom * 100)  # Use calculated cover zoom
        self.zoom_spinbox.setSuffix("%")
        self.zoom_spinbox.setDecimals(0)
        self.zoom_spinbox.setSingleStep(5)
        self.zoom_spinbox.setMinimumWidth(80)
        self.zoom_spinbox.valueChanged.connect(self._on_zoom_spinbox_changed)
        zoom_row.addWidget(self.zoom_spinbox)

        zoom_layout.addLayout(zoom_row)

        # Fit buttons
        fit_row = QHBoxLayout()
        fit_row.setSpacing(4)

        btn_fit_width = QPushButton("Fit Width")
        btn_fit_width.clicked.connect(self._fit_width)
        fit_row.addWidget(btn_fit_width)

        btn_fit_height = QPushButton("Fit Height")
        btn_fit_height.clicked.connect(self._fit_height)
        fit_row.addWidget(btn_fit_height)

        btn_fit_cover = QPushButton("Fill (Cover)")
        btn_fit_cover.clicked.connect(self._fit_cover)
        fit_row.addWidget(btn_fit_cover)

        zoom_layout.addLayout(fit_row)

        right_panel.addWidget(zoom_group)

        # Position control
        position_group = QGroupBox("Position")
        position_layout = QVBoxLayout(position_group)
        position_layout.setSpacing(8)

        # Horizontal position
        h_row = QHBoxLayout()
        h_row.setSpacing(8)
        h_row.addWidget(QLabel("H:"))
        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.setMinimum(0)
        self.h_slider.setMaximum(100)
        self.h_slider.setValue(50)
        self.h_slider.valueChanged.connect(self._on_h_slider_changed)
        h_row.addWidget(self.h_slider, 1)
        self.h_label = QLabel("50%")
        self.h_label.setMinimumWidth(40)
        h_row.addWidget(self.h_label)
        position_layout.addLayout(h_row)

        # Vertical position
        v_row = QHBoxLayout()
        v_row.setSpacing(8)
        v_row.addWidget(QLabel("V:"))
        self.v_slider = QSlider(Qt.Horizontal)
        self.v_slider.setMinimum(0)
        self.v_slider.setMaximum(100)
        self.v_slider.setValue(50)
        self.v_slider.valueChanged.connect(self._on_v_slider_changed)
        v_row.addWidget(self.v_slider, 1)
        self.v_label = QLabel("50%")
        self.v_label.setMinimumWidth(40)
        v_row.addWidget(self.v_label)
        position_layout.addLayout(v_row)

        # Reset button
        btn_reset = QPushButton("Reset Position")
        btn_reset.clicked.connect(self._reset_position)
        position_layout.addWidget(btn_reset)

        right_panel.addWidget(position_group)

        # Quick presets
        presets_group = QGroupBox("Quick Presets")
        presets_layout = QVBoxLayout(presets_group)
        presets_layout.setSpacing(4)

        presets_row1 = QHBoxLayout()
        btn_center = QPushButton("Center")
        btn_center.clicked.connect(lambda: self._set_position(0.5, 0.5))
        presets_row1.addWidget(btn_center)
        btn_top = QPushButton("Top")
        btn_top.clicked.connect(lambda: self._set_position(0.5, 0.0))
        presets_row1.addWidget(btn_top)
        btn_bottom = QPushButton("Bottom")
        btn_bottom.clicked.connect(lambda: self._set_position(0.5, 1.0))
        presets_row1.addWidget(btn_bottom)
        presets_layout.addLayout(presets_row1)

        presets_row2 = QHBoxLayout()
        btn_left = QPushButton("Left")
        btn_left.clicked.connect(lambda: self._set_position(0.0, 0.5))
        presets_row2.addWidget(btn_left)
        btn_right = QPushButton("Right")
        btn_right.clicked.connect(lambda: self._set_position(1.0, 0.5))
        presets_row2.addWidget(btn_right)
        presets_layout.addLayout(presets_row2)

        right_panel.addWidget(presets_group)

        right_panel.addStretch()

        # Dialog buttons
        button_box = QDialogButtonBox()
        self.btn_apply = button_box.addButton("Apply Crop", QDialogButtonBox.AcceptRole)
        self.btn_cancel = button_box.addButton("Cancel", QDialogButtonBox.RejectRole)
        button_box.accepted.connect(self._apply_crop)
        button_box.rejected.connect(self.reject)

        right_panel.addWidget(button_box)

        layout.addLayout(right_panel)

        # Initial fit to cover
        self._fit_cover()

    def _on_zoom_slider_changed(self, value: int):
        """Handle zoom slider change."""
        self.zoom = value / 100.0
        self.zoom_spinbox.blockSignals(True)
        self.zoom_spinbox.setValue(value)
        self.zoom_spinbox.blockSignals(False)
        self._schedule_update()

    def _on_zoom_spinbox_changed(self, value: float):
        """Handle zoom spinbox change."""
        self.zoom = value / 100.0
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(value))
        self.zoom_slider.blockSignals(False)
        self._schedule_update()

    def _on_zoom_changed(self, delta: float):
        """Handle zoom change from scroll wheel."""
        new_zoom = self.zoom + delta
        new_zoom = max(0.1, min(5.0, new_zoom))
        self.zoom = new_zoom

        # Update UI
        self.zoom_slider.blockSignals(True)
        self.zoom_spinbox.blockSignals(True)
        self.zoom_slider.setValue(int(new_zoom * 100))
        self.zoom_spinbox.setValue(new_zoom * 100)
        self.zoom_slider.blockSignals(False)
        self.zoom_spinbox.blockSignals(False)

        self._schedule_update()

    def _on_h_slider_changed(self, value: int):
        """Handle horizontal slider change."""
        self.offset_x = value / 100.0
        self.h_label.setText(f"{value}%")
        self._schedule_update()

    def _on_v_slider_changed(self, value: int):
        """Handle vertical slider change."""
        self.offset_y = value / 100.0
        self.v_label.setText(f"{value}%")
        self._schedule_update()

    def _on_position_changed(self, delta_x: float, delta_y: float):
        """Handle position change from drag."""
        # Invert for viewport-style panning when zoomed in
        if self.zoom > 1.0:
            delta_x = -delta_x
            delta_y = -delta_y

        new_x = max(0.0, min(1.0, self.offset_x + delta_x))
        new_y = max(0.0, min(1.0, self.offset_y + delta_y))

        self.offset_x = new_x
        self.offset_y = new_y

        # Update sliders
        self.h_slider.blockSignals(True)
        self.v_slider.blockSignals(True)
        self.h_slider.setValue(int(new_x * 100))
        self.v_slider.setValue(int(new_y * 100))
        self.h_slider.blockSignals(False)
        self.v_slider.blockSignals(False)
        self.h_label.setText(f"{int(new_x * 100)}%")
        self.v_label.setText(f"{int(new_y * 100)}%")

        self._do_update_preview()

    def _set_position(self, x: float, y: float):
        """Set position to specific values."""
        self.offset_x = x
        self.offset_y = y

        self.h_slider.blockSignals(True)
        self.v_slider.blockSignals(True)
        self.h_slider.setValue(int(x * 100))
        self.v_slider.setValue(int(y * 100))
        self.h_slider.blockSignals(False)
        self.v_slider.blockSignals(False)
        self.h_label.setText(f"{int(x * 100)}%")
        self.v_label.setText(f"{int(y * 100)}%")

        self._schedule_update()

    def _reset_position(self):
        """Reset position to center."""
        self._set_position(0.5, 0.5)

    def _fit_width(self):
        """Zoom to fit the image width to target width."""
        self.zoom = self.target_width / self.image_width

        self.zoom_slider.blockSignals(True)
        self.zoom_spinbox.blockSignals(True)
        self.zoom_slider.setValue(int(self.zoom * 100))
        self.zoom_spinbox.setValue(self.zoom * 100)
        self.zoom_slider.blockSignals(False)
        self.zoom_spinbox.blockSignals(False)

        self._set_position(0.5, 0.5)

    def _fit_height(self):
        """Zoom to fit the image height to target height."""
        self.zoom = self.target_height / self.image_height

        self.zoom_slider.blockSignals(True)
        self.zoom_spinbox.blockSignals(True)
        self.zoom_slider.setValue(int(self.zoom * 100))
        self.zoom_spinbox.setValue(self.zoom * 100)
        self.zoom_slider.blockSignals(False)
        self.zoom_spinbox.blockSignals(False)

        self._set_position(0.5, 0.5)

    def _fit_cover(self):
        """Zoom to fill the entire target area (cover mode)."""
        # Cover mode: zoom so both dimensions fill the target
        zoom_w = self.target_width / self.image_width
        zoom_h = self.target_height / self.image_height
        self.zoom = max(zoom_w, zoom_h)

        self.zoom_slider.blockSignals(True)
        self.zoom_spinbox.blockSignals(True)
        self.zoom_slider.setValue(int(self.zoom * 100))
        self.zoom_spinbox.setValue(self.zoom * 100)
        self.zoom_slider.blockSignals(False)
        self.zoom_spinbox.blockSignals(False)

        self._set_position(0.5, 0.5)

    def _schedule_update(self):
        """Schedule a preview update with debouncing."""
        self.update_timer.stop()
        self.update_timer.start(self.debounce_ms)

    def _do_update_preview(self):
        """Actually update the preview."""
        try:
            # Apply zoom to image
            new_w = int(self.image_width * self.zoom)
            new_h = int(self.image_height * self.zoom)
            if new_w < 1 or new_h < 1:
                return

            zoomed = self.original_image.resize((new_w, new_h), Image.Resampling.BILINEAR)

            # Create the crop result at preview dimensions
            result = self._create_crop(zoomed, self.preview_width, self.preview_height)

            # Convert to QPixmap
            qimage = ImageQt.ImageQt(result)
            pixmap = QPixmap.fromImage(qimage)

            self.preview_view.set_image(pixmap)

        except Exception as e:
            import traceback
            print(f"Preview update error: {e}")
            traceback.print_exc()

    def _create_crop(self, zoomed_img: Image.Image, out_width: int, out_height: int) -> Image.Image:
        """Create a cropped image from the zoomed image at specified dimensions."""
        img_w, img_h = zoomed_img.size

        # If image is smaller than output, scale it up to cover (avoid black borders)
        if img_w < out_width or img_h < out_height:
            scale = max(out_width / img_w, out_height / img_h)
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)
            zoomed_img = zoomed_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            img_w, img_h = new_w, new_h

        # Create output canvas (transparent - base image will fill it)
        canvas = Image.new("RGBA", (out_width, out_height), (0, 0, 0, 0))

        # Calculate paste position based on offset
        # offset_x=0 means left edge of image at left edge of canvas
        # offset_x=1 means right edge of image at right edge of canvas
        paste_x = -int((img_w - out_width) * self.offset_x)
        paste_y = -int((img_h - out_height) * self.offset_y)

        # Ensure zoomed image has alpha channel for proper pasting
        zoomed_rgba = zoomed_img.convert("RGBA") if zoomed_img.mode != "RGBA" else zoomed_img
        canvas.paste(zoomed_rgba, (paste_x, paste_y))

        return canvas

    def _apply_crop(self):
        """Apply the crop and close the dialog."""
        try:
            # Apply zoom at full resolution
            new_w = int(self.image_width * self.zoom)
            new_h = int(self.image_height * self.zoom)
            if new_w < 1 or new_h < 1:
                return

            zoomed = self.original_image.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Create the final crop at target dimensions
            result = self._create_crop(zoomed, self.target_width, self.target_height)

            # Convert to PNG bytes
            buffer = BytesIO()
            result.save(buffer, format="PNG")
            self.cropped_bytes = buffer.getvalue()

            self.accept()

        except Exception as e:
            print(f"Crop error: {e}")
            self.reject()

    def get_cropped_bytes(self) -> Optional[bytes]:
        """Get the cropped image bytes after dialog is accepted."""
        return self.cropped_bytes

    @staticmethod
    def crop_image(image_bytes: bytes, source_tag: str = "", parent=None,
                   target_width: int = 1024, target_height: int = 1024) -> Optional[bytes]:
        """
        Static method to show the crop dialog and return cropped bytes.

        Args:
            image_bytes: Raw image bytes to crop
            source_tag: Description of the image source
            parent: Parent widget
            target_width: Target output width (default 1024 for icons)
            target_height: Target output height (default 1024 for icons)

        Returns None if cancelled.
        """
        dialog = GridCropDialog(image_bytes, source_tag, parent, target_width, target_height)
        if dialog.exec() == QDialog.Accepted:
            return dialog.get_cropped_bytes()
        return None
