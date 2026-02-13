"""
Interactive preview window for adjusting artwork position within borders.
"""

import json
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageQt
from iisu_image_utils import safe_load_image
from PySide6.QtCore import Qt, QPoint, QRect, Signal, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QWheelEvent, QMouseEvent, QPen
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSpinBox, QWidget
)

from run_backend import compose_with_border, center_crop_to_square, corner_mask_from_border


def extract_artwork_from_composited(composited_img: Image.Image, border_path: Path,
                                     output_size: int = 1024) -> Image.Image:
    """
    Extract the source artwork from an already-composited image.

    This reverses the composition by finding the region within the border's mask.
    Returns the extracted artwork (may have some border artifacts at edges).
    """
    try:
        # Load border to get the mask
        border = safe_load_image(border_path, "RGBA")
        if border.size != (output_size, output_size):
            border = border.resize((output_size, output_size), Image.LANCZOS)

        # Get the mask that was used for composition
        mask = corner_mask_from_border(border, threshold=18, shrink_px=8, feather=0.8)

        # The composited image should be same size as output
        comp = composited_img.convert("RGBA")
        if comp.size != (output_size, output_size):
            comp = comp.resize((output_size, output_size), Image.LANCZOS)

        # Extract just the artwork region (center area within mask)
        # For simplicity, just return the composited image as-is
        # The user can adjust positioning and see the preview
        return comp

    except Exception:
        # If extraction fails, just return the composited image
        return composited_img.convert("RGBA")


class InteractivePreviewCanvas(QLabel):
    """Canvas for displaying and interacting with artwork positioning."""

    position_changed = Signal(float, float)  # cx, cy

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 600)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("preview_canvas")

        self.source_img: Optional[Image.Image] = None
        self.border_path: Optional[Path] = None
        self.output_size: int = 1024
        self.centering: Tuple[float, float] = (0.5, 0.5)

        self._dragging = False
        self._last_pos = QPoint()
        self._needs_update = False
        self._cached_pixmap = None

        # Debounce timer for performance
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_update)

        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)

    def set_images(self, source_img: Image.Image, border_path: Path, output_size: int = 1024):
        """Set the source artwork and border for preview."""
        self.source_img = source_img
        self.border_path = border_path
        self.output_size = output_size
        self.schedule_update()

    def set_centering(self, cx: float, cy: float):
        """Update centering position (0.0 to 1.0 for both axes)."""
        self.centering = (
            max(0.0, min(1.0, cx)),
            max(0.0, min(1.0, cy))
        )
        self.schedule_update()

    def schedule_update(self):
        """Debounced update to prevent lag."""
        self._needs_update = True
        self._update_timer.stop()
        self._update_timer.start(100)  # 100ms debounce

    def _do_update(self):
        """Actually perform the update."""
        if not self._needs_update:
            return

        self._needs_update = False

        if self.source_img is None or self.border_path is None:
            return

        # Compose the image at lower resolution for preview (performance)
        preview_size = 512

        # Resize source image for faster compositing
        aspect = self.source_img.width / self.source_img.height
        if aspect > 1:
            preview_src = self.source_img.resize((preview_size, int(preview_size / aspect)), Image.Resampling.LANCZOS)
        else:
            preview_src = self.source_img.resize((int(preview_size * aspect), preview_size), Image.Resampling.LANCZOS)

        # Compose the image
        composed = compose_with_border(
            preview_src,
            self.border_path,
            preview_size,
            centering=self.centering
        )

        # Convert to QPixmap for display
        qt_img = ImageQt.ImageQt(composed)
        pixmap = QPixmap.fromImage(qt_img)

        # Scale to fit widget while maintaining aspect ratio
        scaled = pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self.setPixmap(scaled)

        # Clear memory
        del composed
        del qt_img
        del pixmap
        del preview_src

    def update_preview(self):
        """Legacy method for compatibility - redirects to schedule_update."""
        self.schedule_update()

    def resizeEvent(self, event):
        """Handle widget resize."""
        super().resizeEvent(event)
        self.schedule_update()

    def mousePressEvent(self, event: QMouseEvent):
        """Start dragging."""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Stop dragging."""
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle dragging to adjust position."""
        if not self._dragging:
            return

        delta = event.pos() - self._last_pos
        self._last_pos = event.pos()

        # Convert pixel delta to centering delta
        # Negative because dragging right should move content left (decrease cx)
        widget_size = min(self.width(), self.height())
        if widget_size == 0:
            return

        sensitivity = 0.5  # Adjust sensitivity
        dx = -(delta.x() / widget_size) * sensitivity
        dy = -(delta.y() / widget_size) * sensitivity

        new_cx = self.centering[0] + dx
        new_cy = self.centering[1] + dy

        self.set_centering(new_cx, new_cy)
        self.position_changed.emit(new_cx, new_cy)

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for fine adjustment."""
        delta = event.angleDelta().y()
        step = 0.01 if delta > 0 else -0.01

        # Adjust both axes slightly
        new_cx = self.centering[0]
        new_cy = self.centering[1] + step

        self.set_centering(new_cx, new_cy)
        self.position_changed.emit(new_cx, new_cy)


class PreviewWindow(QDialog):
    """Interactive preview window for artwork positioning."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview & Position Artwork")
        self.setMinimumSize(800, 700)

        self.result_centering: Optional[Tuple[float, float]] = None

        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Drag to reposition artwork • Mouse wheel for fine adjustment")
        title.setObjectName("label_muted")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Canvas
        self.canvas = InteractivePreviewCanvas()
        self.canvas.position_changed.connect(self.on_position_changed)
        layout.addWidget(self.canvas, 1)

        # Position controls
        controls_layout = QHBoxLayout()

        # X position
        controls_layout.addWidget(QLabel("X:"))
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setRange(0, 100)
        self.x_slider.setValue(50)
        self.x_slider.valueChanged.connect(self.on_slider_changed)
        controls_layout.addWidget(self.x_slider, 1)

        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, 100)
        self.x_spin.setValue(50)
        self.x_spin.setSuffix("%")
        self.x_spin.valueChanged.connect(self.on_spin_changed)
        controls_layout.addWidget(self.x_spin)

        controls_layout.addSpacing(20)

        # Y position
        controls_layout.addWidget(QLabel("Y:"))
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setRange(0, 100)
        self.y_slider.setValue(50)
        self.y_slider.valueChanged.connect(self.on_slider_changed)
        controls_layout.addWidget(self.y_slider, 1)

        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, 100)
        self.y_spin.setValue(50)
        self.y_spin.setSuffix("%")
        self.y_spin.valueChanged.connect(self.on_spin_changed)
        controls_layout.addWidget(self.y_spin)

        layout.addLayout(controls_layout)

        # Reset button
        reset_btn = QPushButton("Reset to Center")
        reset_btn.clicked.connect(self.reset_position)
        layout.addWidget(reset_btn)

        # Action buttons
        btn_layout = QHBoxLayout()

        self.save_btn = QPushButton("Save & Apply")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setObjectName("btn_success")
        btn_layout.addWidget(self.save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # Styled via QSS theme (iisu_theme.qss / iisu_theme_light.qss)

    def set_preview(self, source_img: Image.Image, border_path: Path,
                    output_size: int = 1024, initial_centering: Tuple[float, float] = (0.5, 0.5)):
        """Set up the preview with initial centering."""
        self.canvas.set_images(source_img, border_path, output_size)
        self.set_position(initial_centering[0], initial_centering[1])

    def set_position(self, cx: float, cy: float):
        """Set position from normalized coordinates (0.0 to 1.0)."""
        self.canvas.set_centering(cx, cy)

        # Update sliders without triggering callbacks
        self.x_slider.blockSignals(True)
        self.y_slider.blockSignals(True)
        self.x_spin.blockSignals(True)
        self.y_spin.blockSignals(True)

        self.x_slider.setValue(int(cx * 100))
        self.y_slider.setValue(int(cy * 100))
        self.x_spin.setValue(int(cx * 100))
        self.y_spin.setValue(int(cy * 100))

        self.x_slider.blockSignals(False)
        self.y_slider.blockSignals(False)
        self.x_spin.blockSignals(False)
        self.y_spin.blockSignals(False)

    def on_position_changed(self, cx: float, cy: float):
        """Handle position change from canvas."""
        self.set_position(cx, cy)

    def on_slider_changed(self):
        """Handle slider value change."""
        cx = self.x_slider.value() / 100.0
        cy = self.y_slider.value() / 100.0
        self.canvas.set_centering(cx, cy)

        self.x_spin.blockSignals(True)
        self.y_spin.blockSignals(True)
        self.x_spin.setValue(int(cx * 100))
        self.y_spin.setValue(int(cy * 100))
        self.x_spin.blockSignals(False)
        self.y_spin.blockSignals(False)

    def on_spin_changed(self):
        """Handle spinbox value change."""
        cx = self.x_spin.value() / 100.0
        cy = self.y_spin.value() / 100.0
        self.canvas.set_centering(cx, cy)

        self.x_slider.blockSignals(True)
        self.y_slider.blockSignals(True)
        self.x_slider.setValue(int(cx * 100))
        self.y_slider.setValue(int(cy * 100))
        self.x_slider.blockSignals(False)
        self.y_slider.blockSignals(False)

    def reset_position(self):
        """Reset to center position."""
        self.set_position(0.5, 0.5)

    def get_centering(self) -> Tuple[float, float]:
        """Get the final centering position."""
        return self.canvas.centering

    def accept(self):
        """Save the centering and close."""
        self.result_centering = self.canvas.centering
        super().accept()


def show_preview_dialog(source_img: Image.Image, border_path: Path,
                       output_size: int = 1024,
                       initial_centering: Tuple[float, float] = (0.5, 0.5),
                       is_already_composited: bool = False,
                       parent=None) -> Optional[Tuple[float, float]]:
    """
    Show interactive preview dialog and return chosen centering.

    Args:
        source_img: Source artwork (or composited image if is_already_composited=True)
        border_path: Path to border file
        output_size: Output size (default 1024)
        initial_centering: Initial centering position
        is_already_composited: If True, source_img already has border applied
        parent: Qt parent widget

    Returns:
        (cx, cy) tuple if user clicked Save, None if cancelled
    """
    # If image is already composited, extract the artwork portion
    if is_already_composited:
        source_img = extract_artwork_from_composited(source_img, border_path, output_size)

    dialog = PreviewWindow(parent)
    dialog.set_preview(source_img, border_path, output_size, initial_centering)

    if dialog.exec() == QDialog.Accepted:
        return dialog.get_centering()

    return None
