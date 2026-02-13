"""
Custom Image Tab for iiSU Icon Generator
Upload custom images and apply platform borders with manipulation controls.
Optimized for performance with debouncing and caching.
"""

from pathlib import Path
from typing import Optional, Tuple
import math

from PIL import Image, ImageOps, ImageQt, ImageChops
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer, QThread
from PySide6.QtGui import QPixmap, QImage, QPainter, QTransform, QWheelEvent, QMouseEvent, QKeyEvent, QPen, QBrush, QColor, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QGroupBox, QComboBox, QMessageBox, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QSizePolicy, QButtonGroup, QDoubleSpinBox, QCheckBox,
    QFrame
)

from run_backend import compose_with_border, center_crop_to_square, load_yaml, corner_mask_from_border
from app_paths import get_config_path, get_borders_dir, get_config
from iisu_image_utils import safe_load_image


class TransformHandlesOverlay(QWidget):
    """
    Overlay widget that draws transform handles (bounding box with draggable corners/edges)
    on top of an image preview for interactive scaling, rotation, and positioning.
    """

    # Signals emitted during handle interactions
    scale_changed = Signal(float, float)  # scale_x, scale_y (relative change)
    rotation_changed = Signal(float)  # rotation angle in degrees
    position_changed = Signal(float, float)  # delta_x, delta_y (normalized 0-1)
    transform_started = Signal()  # Emitted when user starts dragging
    transform_finished = Signal()  # Emitted when user releases

    # Handle types
    HANDLE_NONE = 'none'
    HANDLE_TL = 'tl'  # Top-left corner
    HANDLE_TR = 'tr'  # Top-right corner
    HANDLE_BL = 'bl'  # Bottom-left corner
    HANDLE_BR = 'br'  # Bottom-right corner
    HANDLE_T = 't'    # Top edge
    HANDLE_B = 'b'    # Bottom edge
    HANDLE_L = 'l'    # Left edge
    HANDLE_R = 'r'    # Right edge
    HANDLE_ROTATE = 'rotate'  # Rotation handle
    HANDLE_MOVE = 'move'  # Inside bounds - move

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        # Handle visual properties
        self.handle_size = 16  # Size of corner/edge handles in pixels
        self.rotation_handle_distance = 35  # Distance of rotation handle from top edge
        self.rotation_handle_size = 18

        # Colors
        self.handle_color = QColor(0, 120, 215)  # Blue
        self.handle_hover_color = QColor(0, 150, 255)  # Lighter blue
        self.handle_active_color = QColor(255, 165, 0)  # Orange when dragging
        self.bounds_color = QColor(0, 120, 215, 180)
        self.rotation_line_color = QColor(0, 120, 215, 120)

        # Current state
        self.bounds = QRectF()  # Bounding box in widget coordinates
        self.rotation = 0.0  # Current rotation angle
        self.active_layer = 'background'  # 'background' or 'logo'
        self.handles_visible = True

        # Interaction state
        self.hovered_handle = self.HANDLE_NONE
        self.active_handle = self.HANDLE_NONE
        self.drag_start_pos = QPointF()
        self.drag_start_bounds = QRectF()
        self.drag_start_rotation = 0.0

        # Aspect ratio lock
        self.lock_aspect_ratio = True

    def set_bounds(self, bounds: QRectF):
        """Set the bounding box for the current layer."""
        self.bounds = bounds
        self.update()

    def set_rotation(self, rotation: float):
        """Set the rotation angle for handle placement."""
        self.rotation = rotation
        self.update()

    def set_active_layer(self, layer: str):
        """Set which layer is being transformed ('background' or 'logo')."""
        self.active_layer = layer
        self.update()

    def set_handles_visible(self, visible: bool):
        """Show or hide the transform handles."""
        self.handles_visible = visible
        self.update()

    def get_handle_positions(self) -> dict:
        """Calculate positions of all handles based on current bounds and rotation."""
        if self.bounds.isEmpty():
            return {}

        center = self.bounds.center()

        # Get corners (before rotation)
        tl = self.bounds.topLeft()
        tr = self.bounds.topRight()
        bl = self.bounds.bottomLeft()
        br = self.bounds.bottomRight()

        # Get edge centers
        t = QPointF((tl.x() + tr.x()) / 2, tl.y())
        b = QPointF((bl.x() + br.x()) / 2, bl.y())
        l = QPointF(tl.x(), (tl.y() + bl.y()) / 2)
        r = QPointF(tr.x(), (tr.y() + br.y()) / 2)

        # Rotation handle position (above top center)
        rotate_pos = QPointF(t.x(), t.y() - self.rotation_handle_distance)

        # Apply rotation transform to all positions
        positions = {
            self.HANDLE_TL: tl,
            self.HANDLE_TR: tr,
            self.HANDLE_BL: bl,
            self.HANDLE_BR: br,
            self.HANDLE_T: t,
            self.HANDLE_B: b,
            self.HANDLE_L: l,
            self.HANDLE_R: r,
            self.HANDLE_ROTATE: rotate_pos,
        }

        if self.rotation != 0:
            transform = QTransform()
            transform.translate(center.x(), center.y())
            transform.rotate(self.rotation)
            transform.translate(-center.x(), -center.y())

            for handle_type, pos in positions.items():
                positions[handle_type] = transform.map(pos)

        return positions

    def hit_test(self, pos: QPointF) -> str:
        """Determine which handle (if any) is at the given position."""
        if not self.handles_visible or self.bounds.isEmpty():
            return self.HANDLE_NONE

        positions = self.get_handle_positions()

        # Check rotation handle first (highest priority)
        if self.HANDLE_ROTATE in positions:
            rotate_pos = positions[self.HANDLE_ROTATE]
            if self._point_in_handle(pos, rotate_pos, self.rotation_handle_size):
                return self.HANDLE_ROTATE

        # Check corner handles (higher priority than edges)
        for handle_type in [self.HANDLE_TL, self.HANDLE_TR, self.HANDLE_BL, self.HANDLE_BR]:
            if handle_type in positions:
                if self._point_in_handle(pos, positions[handle_type], self.handle_size):
                    return handle_type

        # Check edge handles
        for handle_type in [self.HANDLE_T, self.HANDLE_B, self.HANDLE_L, self.HANDLE_R]:
            if handle_type in positions:
                if self._point_in_handle(pos, positions[handle_type], self.handle_size):
                    return handle_type

        # Check if inside bounds (for moving)
        if self._point_in_rotated_bounds(pos):
            return self.HANDLE_MOVE

        return self.HANDLE_NONE

    def _point_in_handle(self, point: QPointF, handle_center: QPointF, size: float) -> bool:
        """Check if a point is within a handle's clickable area."""
        half_size = size / 2 + 4  # Add padding for easier clicking
        return (abs(point.x() - handle_center.x()) <= half_size and
                abs(point.y() - handle_center.y()) <= half_size)

    def _point_in_rotated_bounds(self, point: QPointF) -> bool:
        """Check if a point is inside the rotated bounding box."""
        if self.bounds.isEmpty():
            return False

        # Transform point to un-rotated space
        center = self.bounds.center()
        transform = QTransform()
        transform.translate(center.x(), center.y())
        transform.rotate(-self.rotation)
        transform.translate(-center.x(), -center.y())

        unrotated_point = transform.map(point)
        return self.bounds.contains(unrotated_point)

    def get_cursor_for_handle(self, handle_type: str) -> QCursor:
        """Get the appropriate cursor for a handle type."""
        if handle_type == self.HANDLE_ROTATE:
            return QCursor(Qt.CrossCursor)
        elif handle_type in [self.HANDLE_TL, self.HANDLE_BR]:
            return QCursor(Qt.SizeFDiagCursor)
        elif handle_type in [self.HANDLE_TR, self.HANDLE_BL]:
            return QCursor(Qt.SizeBDiagCursor)
        elif handle_type in [self.HANDLE_T, self.HANDLE_B]:
            return QCursor(Qt.SizeVerCursor)
        elif handle_type in [self.HANDLE_L, self.HANDLE_R]:
            return QCursor(Qt.SizeHorCursor)
        elif handle_type == self.HANDLE_MOVE:
            return QCursor(Qt.SizeAllCursor)
        else:
            return QCursor(Qt.ArrowCursor)

    def paintEvent(self, event):
        """Draw the transform handles and bounding box."""
        if not self.handles_visible or self.bounds.isEmpty():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        center = self.bounds.center()

        # Apply rotation
        painter.translate(center)
        painter.rotate(self.rotation)
        painter.translate(-center)

        # Draw bounding box
        pen = QPen(self.bounds_color, 2, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.bounds)

        # Reset rotation for handles (they stay axis-aligned visually but positioned correctly)
        painter.resetTransform()

        positions = self.get_handle_positions()

        # Draw line from top center to rotation handle
        if self.HANDLE_T in positions and self.HANDLE_ROTATE in positions:
            pen = QPen(self.rotation_line_color, 2)
            painter.setPen(pen)
            painter.drawLine(positions[self.HANDLE_T], positions[self.HANDLE_ROTATE])

        # Draw handles
        for handle_type, pos in positions.items():
            if handle_type == self.HANDLE_ROTATE:
                size = self.rotation_handle_size
            else:
                size = self.handle_size

            # Determine color based on state
            if handle_type == self.active_handle:
                color = self.handle_active_color
            elif handle_type == self.hovered_handle:
                color = self.handle_hover_color
            else:
                color = self.handle_color

            painter.setPen(QPen(color.darker(120), 2))
            painter.setBrush(QBrush(color))

            if handle_type == self.HANDLE_ROTATE:
                # Draw rotation handle as circle
                painter.drawEllipse(pos, size / 2, size / 2)
            else:
                # Draw scale handles as squares
                rect = QRectF(pos.x() - size / 2, pos.y() - size / 2, size, size)
                painter.drawRect(rect)

        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        """Start a transform operation."""
        if event.button() == Qt.LeftButton:
            pos = QPointF(event.pos())
            hit = self.hit_test(pos)

            if hit != self.HANDLE_NONE:
                self.active_handle = hit
                self.drag_start_pos = pos
                self.drag_start_bounds = QRectF(self.bounds)
                self.drag_start_rotation = self.rotation
                self.transform_started.emit()
                self.update()
                event.accept()
                return

        event.ignore()  # Let parent handle it

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle dragging or hover state updates."""
        pos = QPointF(event.pos())

        if self.active_handle != self.HANDLE_NONE:
            # Currently dragging
            self._handle_drag(pos)
            event.accept()
        else:
            # Just hovering - update cursor
            hit = self.hit_test(pos)
            if hit != self.hovered_handle:
                self.hovered_handle = hit
                self.setCursor(self.get_cursor_for_handle(hit))
                self.update()
            event.ignore()  # Let parent handle for panning if not on handle

    def mouseReleaseEvent(self, event: QMouseEvent):
        """End a transform operation."""
        if event.button() == Qt.LeftButton and self.active_handle != self.HANDLE_NONE:
            self.active_handle = self.HANDLE_NONE
            self.transform_finished.emit()
            self.update()
            event.accept()
        else:
            event.ignore()

    def _handle_drag(self, current_pos: QPointF):
        """Process drag movement based on active handle type."""
        delta = current_pos - self.drag_start_pos
        center = self.drag_start_bounds.center()

        if self.active_handle == self.HANDLE_ROTATE:
            # Calculate rotation angle
            start_angle = math.atan2(
                self.drag_start_pos.y() - center.y(),
                self.drag_start_pos.x() - center.x()
            )
            current_angle = math.atan2(
                current_pos.y() - center.y(),
                current_pos.x() - center.x()
            )
            angle_delta = math.degrees(current_angle - start_angle)
            self.rotation_changed.emit(angle_delta)

        elif self.active_handle == self.HANDLE_MOVE:
            # Calculate position change as normalized delta
            widget_size = min(self.width(), self.height())
            if widget_size > 0:
                norm_dx = delta.x() / widget_size
                norm_dy = delta.y() / widget_size
                self.position_changed.emit(-norm_dx, -norm_dy)
                # Update drag start for continuous movement
                self.drag_start_pos = current_pos

        elif self.active_handle in [self.HANDLE_TL, self.HANDLE_TR, self.HANDLE_BL, self.HANDLE_BR]:
            # Corner handle - uniform or non-uniform scale
            self._handle_corner_scale(current_pos)

        elif self.active_handle in [self.HANDLE_T, self.HANDLE_B, self.HANDLE_L, self.HANDLE_R]:
            # Edge handle - single axis scale
            self._handle_edge_scale(current_pos)

    def _handle_corner_scale(self, current_pos: QPointF):
        """Handle corner drag for scaling."""
        center = self.drag_start_bounds.center()

        # Get the fixed corner (opposite to the one being dragged)
        if self.active_handle == self.HANDLE_TL:
            fixed = self.drag_start_bounds.bottomRight()
        elif self.active_handle == self.HANDLE_TR:
            fixed = self.drag_start_bounds.bottomLeft()
        elif self.active_handle == self.HANDLE_BL:
            fixed = self.drag_start_bounds.topRight()
        else:  # BR
            fixed = self.drag_start_bounds.topLeft()

        # Calculate original and new distances from fixed point
        original_dist = math.sqrt(
            (self.drag_start_pos.x() - fixed.x()) ** 2 +
            (self.drag_start_pos.y() - fixed.y()) ** 2
        )
        current_dist = math.sqrt(
            (current_pos.x() - fixed.x()) ** 2 +
            (current_pos.y() - fixed.y()) ** 2
        )

        if original_dist > 0:
            scale_factor = current_dist / original_dist
            self.scale_changed.emit(scale_factor, scale_factor)

    def _handle_edge_scale(self, current_pos: QPointF):
        """Handle edge drag for single-axis scaling."""
        center = self.drag_start_bounds.center()

        if self.active_handle in [self.HANDLE_L, self.HANDLE_R]:
            # Horizontal scaling
            original_half_width = self.drag_start_bounds.width() / 2
            if self.active_handle == self.HANDLE_R:
                new_half_width = current_pos.x() - center.x()
            else:
                new_half_width = center.x() - current_pos.x()

            if original_half_width > 0 and new_half_width > 0:
                scale_x = new_half_width / original_half_width
                if self.lock_aspect_ratio:
                    self.scale_changed.emit(scale_x, scale_x)
                else:
                    self.scale_changed.emit(scale_x, 1.0)

        else:  # T or B
            # Vertical scaling
            original_half_height = self.drag_start_bounds.height() / 2
            if self.active_handle == self.HANDLE_B:
                new_half_height = current_pos.y() - center.y()
            else:
                new_half_height = center.y() - current_pos.y()

            if original_half_height > 0 and new_half_height > 0:
                scale_y = new_half_height / original_half_height
                if self.lock_aspect_ratio:
                    self.scale_changed.emit(scale_y, scale_y)
                else:
                    self.scale_changed.emit(1.0, scale_y)


class InteractiveImageView(QGraphicsView):
    """Interactive image view with transform handles overlay for scaling, rotation, and positioning."""

    # Signals for transform handle interactions
    scale_changed = Signal(float, float)  # scale_x, scale_y (relative multiplier)
    rotation_changed = Signal(float)  # rotation delta in degrees
    position_changed = Signal(float, float)  # delta_x, delta_y (normalized 0-1)

    # Legacy signals (kept for compatibility)
    position_dragged = Signal(float, float)  # delta_x, delta_y in 0-1 range
    zoom_changed = Signal(float)  # zoom delta (positive = zoom in, negative = zoom out)
    arrow_key_pressed = Signal(float, float)  # delta_x, delta_y for fine positioning

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # Setup view properties
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(self._create_checkerboard_brush())
        self.setFrameShape(QGraphicsView.NoFrame)

        # Enable focus for keyboard events
        self.setFocusPolicy(Qt.StrongFocus)

        # Image item
        self.image_item: Optional[QGraphicsPixmapItem] = None

        # Zoom state (view zoom, not source image zoom)
        self.zoom_factor = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 5.0

        # Reference size for drag sensitivity
        self.arrow_key_step = 0.005  # Fine positioning step for arrow keys

        # Create transform handles overlay (parented to viewport for correct positioning)
        self.handles_overlay = TransformHandlesOverlay(self.viewport())
        self.handles_overlay.setGeometry(0, 0, self.viewport().width(), self.viewport().height())
        self.handles_overlay.show()
        self.handles_overlay.raise_()

        # Connect overlay signals to our signals
        self.handles_overlay.scale_changed.connect(self.scale_changed.emit)
        self.handles_overlay.rotation_changed.connect(self.rotation_changed.emit)
        self.handles_overlay.position_changed.connect(self.position_changed.emit)

        # Install event filter on viewport to intercept mouse events for handles
        self.viewport().installEventFilter(self)

    def resizeEvent(self, event):
        """Resize the handles overlay when the view is resized."""
        super().resizeEvent(event)
        self.handles_overlay.setGeometry(0, 0, self.viewport().width(), self.viewport().height())
        self.handles_overlay.raise_()

    def eventFilter(self, watched, event):
        """Filter viewport events to handle transform handles."""
        if watched == self.viewport():
            if event.type() == event.Type.MouseButtonPress:
                # Check if click is on a handle
                pos = QPointF(event.pos())
                hit = self.handles_overlay.hit_test(pos)
                if hit != TransformHandlesOverlay.HANDLE_NONE:
                    # Forward to overlay
                    self.handles_overlay.mousePressEvent(event)
                    return True  # Consume the event

            elif event.type() == event.Type.MouseMove:
                # Check if we're dragging or hovering over a handle
                pos = QPointF(event.pos())
                if self.handles_overlay.active_handle != TransformHandlesOverlay.HANDLE_NONE:
                    # Currently dragging - forward to overlay
                    self.handles_overlay.mouseMoveEvent(event)
                    return True
                else:
                    # Just hovering - update cursor but don't consume event
                    hit = self.handles_overlay.hit_test(pos)
                    if hit != self.handles_overlay.hovered_handle:
                        self.handles_overlay.hovered_handle = hit
                        self.handles_overlay.setCursor(self.handles_overlay.get_cursor_for_handle(hit))
                        self.viewport().setCursor(self.handles_overlay.get_cursor_for_handle(hit))
                        self.handles_overlay.update()

            elif event.type() == event.Type.MouseButtonRelease:
                if self.handles_overlay.active_handle != TransformHandlesOverlay.HANDLE_NONE:
                    self.handles_overlay.mouseReleaseEvent(event)
                    return True

        return super().eventFilter(watched, event)

    def set_image(self, pixmap: QPixmap):
        """Set the image to display."""
        self.scene.clear()
        self.image_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.image_item)
        self.fitInView(self.image_item, Qt.KeepAspectRatio)
        self.zoom_factor = 1.0

    def set_transform_bounds(self, bounds: QRectF):
        """Set the bounding box for transform handles."""
        self.handles_overlay.set_bounds(bounds)

    def set_transform_rotation(self, rotation: float):
        """Set the rotation for transform handles."""
        self.handles_overlay.set_rotation(rotation)

    def set_active_layer(self, layer: str):
        """Set which layer the handles should affect."""
        self.handles_overlay.set_active_layer(layer)

    def set_handles_visible(self, visible: bool):
        """Show or hide the transform handles."""
        self.handles_overlay.set_handles_visible(visible)

    def set_lock_aspect_ratio(self, locked: bool):
        """Set whether scaling should maintain aspect ratio."""
        self.handles_overlay.lock_aspect_ratio = locked

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming the source image (not the view)."""
        if self.image_item is None:
            return

        # Get the zoom delta
        delta = event.angleDelta().y()

        # Emit zoom change signal for parent to handle source image zoom
        # Positive delta = zoom in, negative = zoom out
        # Use smaller increments for smoother control
        zoom_step = 0.05 if delta > 0 else -0.05
        self.zoom_changed.emit(zoom_step)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle arrow keys for fine positioning."""
        if self.image_item is None:
            super().keyPressEvent(event)
            return

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

        self.arrow_key_pressed.emit(delta_x, delta_y)
        event.accept()

    @staticmethod
    def _create_checkerboard_brush() -> QBrush:
        """Create a checkerboard pattern brush for transparency visualization."""
        tile = 16
        pixmap = QPixmap(tile * 2, tile * 2)
        pixmap.fill(QColor(40, 40, 40))
        painter = QPainter(pixmap)
        painter.fillRect(0, 0, tile, tile, QColor(60, 60, 60))
        painter.fillRect(tile, tile, tile, tile, QColor(60, 60, 60))
        painter.end()
        return QBrush(pixmap)

    def reset_view(self):
        """Reset zoom and pan to fit the image."""
        if self.image_item:
            self.resetTransform()
            self.fitInView(self.image_item, Qt.KeepAspectRatio)
            self.zoom_factor = 1.0


class PreviewWorker(QThread):
    """Worker thread for compositing the preview image off the main thread."""
    preview_ready = Signal(QImage)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._params = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def set_params(self, params: dict):
        """Set rendering parameters before calling start().

        Keys: background_image, logo_image, rotation, zoom, offset_x, offset_y,
              logo_scale, logo_offset_x, logo_offset_y, logo_opacity,
              border_cache, border_mask_cache, preview_size
        """
        self._params = params
        self._cancelled = False

    def run(self):
        try:
            if self._cancelled or self._params is None:
                return

            p = self._params
            preview_size = p['preview_size']

            # Create transparent canvas
            result = Image.new("RGBA", (preview_size, preview_size), (0, 0, 0, 0))

            # --- Layer 1: Background ---
            if p['background_image'] is not None and not self._cancelled:
                bg = p['background_image']

                # Rotate
                if p['rotation'] != 0:
                    bg = bg.rotate(-p['rotation'], expand=True,
                                   fillcolor=(0, 0, 0, 0), resample=Image.BILINEAR)

                if self._cancelled:
                    return

                # Zoom
                if p['zoom'] != 1.0:
                    w, h = bg.size
                    bg = bg.resize((int(w * p['zoom']), int(h * p['zoom'])), Image.BILINEAR)

                if self._cancelled:
                    return

                # Scale for preview
                scale_factor = preview_size / 1024.0
                if scale_factor != 1.0:
                    bg = bg.resize((int(bg.size[0] * scale_factor),
                                    int(bg.size[1] * scale_factor)), Image.BILINEAR)

                # Position on canvas
                img_w, img_h = bg.size
                paste_x = -int((img_w - preview_size) * p['offset_x'])
                paste_y = -int((img_h - preview_size) * p['offset_y'])
                result.paste(bg, (paste_x, paste_y), bg)

            if self._cancelled:
                return

            # --- Layer 2: Logo ---
            if p['logo_image'] is not None:
                logo = p['logo_image']
                logo_w, logo_h = logo.size
                max_logo_size = int(preview_size * p['logo_scale'])
                if max_logo_size > 0 and logo_w > 0 and logo_h > 0:
                    scale_ratio = min(max_logo_size / logo_w, max_logo_size / logo_h)
                    new_w = int(logo_w * scale_ratio)
                    new_h = int(logo_h * scale_ratio)
                    if new_w > 0 and new_h > 0:
                        scaled_logo = logo.resize((new_w, new_h), Image.BILINEAR)

                        if self._cancelled:
                            return

                        # Apply opacity
                        if p['logo_opacity'] < 1.0:
                            r, g, b, a = scaled_logo.split()
                            a = a.point(lambda x: int(x * p['logo_opacity']))
                            scaled_logo = Image.merge("RGBA", (r, g, b, a))

                        # Position
                        max_x = preview_size - new_w
                        max_y = preview_size - new_h
                        lx = int(max(0, max_x) * p['logo_offset_x'])
                        ly = int(max(0, max_y) * p['logo_offset_y'])
                        result.paste(scaled_logo, (lx, ly), scaled_logo)

            if self._cancelled:
                return

            # --- Layer 3: Border ---
            border = p.get('border_cache')
            mask = p.get('border_mask_cache')
            if border is not None and mask is not None:
                result.putalpha(ImageChops.multiply(result.split()[-1], mask))
                result = Image.alpha_composite(result, border)

            if self._cancelled:
                return

            # Convert to QImage (thread-safe)
            qimage = ImageQt.ImageQt(result)
            # We must copy the QImage because the underlying PIL data
            # could be garbage-collected when this method returns
            self.preview_ready.emit(qimage.copy())

        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))


class CustomImageTab(QWidget):
    """Tab for uploading custom images and applying platform borders with layer support."""

    def __init__(self):
        super().__init__()

        # Layer state - background (game art) and logo overlay
        self.background_image: Optional[Image.Image] = None  # Background layer (game art)
        self.logo_image: Optional[Image.Image] = None  # Logo overlay layer (transparent)

        # Legacy support - original_image now refers to the composite
        self.original_image: Optional[Image.Image] = None
        self.current_platform: Optional[str] = None
        self.current_border: Optional[Path] = None

        # Background layer transformations (no longer limited by sliders)
        self.rotation: float = 0.0  # Now supports float for smooth rotation
        self.zoom: float = 1.0  # No upper/lower limits
        self.offset_x: float = 0.5  # Center by default (0-1 range)
        self.offset_y: float = 0.5

        # Logo layer transformations (no longer limited by sliders)
        self.logo_scale: float = 0.5  # Logo scale relative to canvas
        self.logo_offset_x: float = 0.5  # Logo horizontal position (0-1)
        self.logo_offset_y: float = 0.5  # Logo vertical position (0-1)
        self.logo_opacity: float = 1.0  # Logo opacity (0-1)

        # Active layer for transform handles
        self.active_layer: str = 'background'  # 'background' or 'logo'

        # Transform handle interaction state
        self.transform_start_zoom: float = 1.0
        self.transform_start_rotation: float = 0.0
        self.transform_start_logo_scale: float = 0.5

        # Performance optimization: cache the preview size version
        self.preview_cache: Optional[Image.Image] = None
        self.preview_size = 512  # Lower resolution for interactive preview

        # Cache border images and masks to avoid reloading
        self.border_cache: Optional[Image.Image] = None  # Border at preview size
        self.border_mask_cache: Optional[Image.Image] = None  # Mask at preview size
        self.border_cache_full: Optional[Image.Image] = None  # Border at 1024x1024
        self.border_mask_cache_full: Optional[Image.Image] = None  # Mask at 1024x1024

        # Config
        self.config_path = get_config_path()
        self.platforms_config = {}
        self.borders_dir = get_borders_dir()

        # Debounce timer for preview updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._start_preview_worker)
        self.debounce_ms = 150  # Worker handles heavy lifting off-thread

        # Preview worker thread
        self._preview_worker: Optional[PreviewWorker] = None

        self._load_config()
        self._setup_ui()

        # Initialize layer selection after UI is set up
        self._select_layer('background')

    def _load_config(self):
        """Load platform configuration."""
        try:
            cfg = get_config()
            self.platforms_config = cfg.get("platforms", {})
            paths = cfg.get("paths", {})
            borders_dir_str = paths.get("borders_dir", "./borders")
            self.borders_dir = (self.config_path.parent / borders_dir_str).resolve()
        except Exception:
            pass

    def _setup_ui(self):
        """Setup the user interface — streamlined single-flow layout."""
        from PySide6.QtWidgets import QScrollArea, QFrame, QSlider

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # ── Left panel: Controls ──
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFixedWidth(320)
        # Styled via QSS (QScrollArea rule)

        left_panel = QWidget()
        # Styled via QSS (QFrame/QWidget transparency rules)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(5, 5, 10, 5)

        # ===== IMAGE CARD =====
        image_card = QFrame()
        image_card.setObjectName("card")
        image_card_layout = QVBoxLayout(image_card)
        image_card_layout.setContentsMargins(10, 10, 10, 10)
        image_card_layout.setSpacing(6)

        # Upload Image button (prominent)
        self.bg_upload_btn = QPushButton("Upload Image")
        self.bg_upload_btn.setMinimumHeight(36)
        self.bg_upload_btn.clicked.connect(self._upload_background)
        self.bg_upload_btn.setObjectName("btn_primary")
        image_card_layout.addWidget(self.bg_upload_btn)

        self.bg_info = QLabel("No image loaded")
        self.bg_info.setObjectName("label_muted")
        image_card_layout.addWidget(self.bg_info)

        self.bg_clear_btn = QPushButton("Clear Image")
        self.bg_clear_btn.setMinimumHeight(24)
        self.bg_clear_btn.clicked.connect(self._clear_background)
        self.bg_clear_btn.setEnabled(False)
        self.bg_clear_btn.setObjectName("btn_clear")
        self.bg_clear_btn.setVisible(False)
        image_card_layout.addWidget(self.bg_clear_btn)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        # Styled via QSS (QFrame[frameShape="4"] rule)
        sep1.setFixedHeight(1)
        image_card_layout.addWidget(sep1)

        # Logo section (optional overlay)
        self.logo_upload_btn = QPushButton("Add Logo (Optional)")
        self.logo_upload_btn.setMinimumHeight(30)
        self.logo_upload_btn.clicked.connect(self._upload_logo)
        self.logo_upload_btn.setObjectName("btn_secondary")
        image_card_layout.addWidget(self.logo_upload_btn)

        self.logo_info = QLabel("Transparent PNG overlay")
        self.logo_info.setObjectName("label_muted")
        image_card_layout.addWidget(self.logo_info)

        # Logo controls (hidden until logo loaded)
        self.logo_controls_widget = QWidget()
        logo_ctrl_layout = QVBoxLayout(self.logo_controls_widget)
        logo_ctrl_layout.setContentsMargins(0, 4, 0, 0)
        logo_ctrl_layout.setSpacing(4)

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(6)
        opacity_lbl = QLabel("Opacity:")
        opacity_lbl.setObjectName("label_info")
        opacity_row.addWidget(opacity_lbl)
        self.logo_opacity_slider = QSlider(Qt.Horizontal)
        self.logo_opacity_slider.setMinimum(0)
        self.logo_opacity_slider.setMaximum(100)
        self.logo_opacity_slider.setValue(100)
        self.logo_opacity_slider.valueChanged.connect(self._on_logo_opacity_changed)
        opacity_row.addWidget(self.logo_opacity_slider, 1)
        self.logo_opacity_label = QLabel("100%")
        self.logo_opacity_label.setObjectName("label_value")
        self.logo_opacity_label.setMinimumWidth(35)
        opacity_row.addWidget(self.logo_opacity_label)
        logo_ctrl_layout.addLayout(opacity_row)

        self.logo_clear_btn = QPushButton("Clear Logo")
        self.logo_clear_btn.setMinimumHeight(24)
        self.logo_clear_btn.clicked.connect(self._clear_logo)
        self.logo_clear_btn.setEnabled(False)
        self.logo_clear_btn.setObjectName("btn_clear")
        logo_ctrl_layout.addWidget(self.logo_clear_btn)

        self.logo_controls_widget.setVisible(False)
        image_card_layout.addWidget(self.logo_controls_widget)

        left_layout.addWidget(image_card)

        # ===== PLATFORM BORDER =====
        border_card = QFrame()
        border_card.setObjectName("card")
        border_layout = QVBoxLayout(border_card)
        border_layout.setContentsMargins(10, 10, 10, 10)
        border_layout.setSpacing(6)

        border_header = QHBoxLayout()
        border_title = QLabel("Platform Border")
        border_title.setObjectName("label_card_title")
        border_header.addWidget(border_title)
        border_header.addStretch()

        custom_border_btn = QPushButton("+ Custom")
        custom_border_btn.setMinimumHeight(22)
        custom_border_btn.clicked.connect(self._import_custom_border)
        custom_border_btn.setObjectName("btn_small")
        border_header.addWidget(custom_border_btn)
        border_layout.addLayout(border_header)

        self.platform_combo = QComboBox()
        self.platform_combo.setMinimumHeight(32)
        self.platform_combo.addItem("Select platform...", None)

        for platform_key, platform_data in sorted(self.platforms_config.items()):
            border_file = platform_data.get("border_file")
            if border_file:
                display_name = platform_key.replace("_", " ").title()
                self.platform_combo.addItem(display_name, platform_key)

        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        border_layout.addWidget(self.platform_combo)

        self.border_info = QLabel("Select a platform to apply border")
        self.border_info.setObjectName("label_muted")
        border_layout.addWidget(self.border_info)

        left_layout.addWidget(border_card)

        # ===== TOOLBAR CARD (Transform + Export combined) =====
        toolbar_card = QFrame()
        toolbar_card.setObjectName("card")
        toolbar_layout = QVBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(10, 10, 10, 10)
        toolbar_layout.setSpacing(6)

        # Compact transform readout
        info_row = QHBoxLayout()
        info_row.setSpacing(6)

        scale_row = QHBoxLayout()
        scale_row.setSpacing(4)
        scale_lbl = QLabel("Scale:")
        scale_lbl.setObjectName("label_info")
        scale_row.addWidget(scale_lbl)
        self.scale_spinbox = QDoubleSpinBox()
        self.scale_spinbox.setRange(1, 1000)
        self.scale_spinbox.setValue(100)
        self.scale_spinbox.setSuffix("%")
        self.scale_spinbox.setDecimals(0)
        self.scale_spinbox.setSingleStep(5)
        self.scale_spinbox.setMinimumWidth(70)
        self.scale_spinbox.setMaximumHeight(26)
        self.scale_spinbox.valueChanged.connect(self._on_scale_spinbox_changed)
        scale_row.addWidget(self.scale_spinbox)
        info_row.addLayout(scale_row)

        self.rotation_value_label = QLabel("0°")
        self.rotation_value_label.setObjectName("label_value")
        info_row.addWidget(self.rotation_value_label)

        self.position_value_label = QLabel("50%, 50%")
        self.position_value_label.setObjectName("label_value")
        info_row.addWidget(self.position_value_label)

        info_row.addStretch()
        toolbar_layout.addLayout(info_row)

        # Options row
        options_row = QHBoxLayout()
        options_row.setSpacing(8)

        self.lock_aspect_cb = QCheckBox("Lock Ratio")
        self.lock_aspect_cb.setChecked(True)
        self.lock_aspect_cb.setObjectName("cb_small")
        self.lock_aspect_cb.stateChanged.connect(self._on_lock_aspect_changed)
        options_row.addWidget(self.lock_aspect_cb)

        self.reset_transform_btn = QPushButton("Reset")
        self.reset_transform_btn.setMinimumHeight(24)
        self.reset_transform_btn.clicked.connect(self._reset_current_layer)
        self.reset_transform_btn.setObjectName("btn_small")
        options_row.addWidget(self.reset_transform_btn)

        # Active layer indicator
        self.active_layer_label = QLabel("BG")
        self.active_layer_label.setObjectName("active_layer_indicator")
        self.active_layer_label.setAlignment(Qt.AlignCenter)
        self.active_layer_label.setFixedHeight(22)
        options_row.addWidget(self.active_layer_label)

        options_row.addStretch()
        toolbar_layout.addLayout(options_row)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        # Styled via QSS (QFrame[frameShape="4"] rule)
        sep2.setFixedHeight(1)
        toolbar_layout.addWidget(sep2)

        # Export
        self.export_btn = QPushButton("Export 1024x1024")
        self.export_btn.setMinimumHeight(40)
        self.export_btn.clicked.connect(self._export_image)
        self.export_btn.setEnabled(False)
        self.export_btn.setObjectName("btn_export")
        toolbar_layout.addWidget(self.export_btn)

        self.export_info = QLabel("Upload image and select platform")
        self.export_info.setObjectName("label_muted")
        self.export_info.setAlignment(Qt.AlignCenter)
        toolbar_layout.addWidget(self.export_info)

        left_layout.addWidget(toolbar_card)

        left_layout.addStretch()
        scroll_area.setWidget(left_panel)

        # ── Right panel: Preview ──
        right_panel = QFrame()
        right_panel.setObjectName("preview_panel")
        right_panel.setMinimumWidth(450)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)

        preview_header = QHBoxLayout()
        preview_label = QLabel("Preview")
        preview_label.setObjectName("label_card_title")
        preview_header.addWidget(preview_label)
        preview_header.addStretch()

        preview_help = QLabel("Drag to move · Scroll to zoom · Corners to resize")
        preview_help.setObjectName("label_muted")
        preview_header.addWidget(preview_help)
        right_layout.addLayout(preview_header)

        self.preview_view = InteractiveImageView()
        self.preview_view.setMinimumSize(350, 350)
        self.preview_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self.preview_view, 1)

        # Connect transform handle signals
        self.preview_view.scale_changed.connect(self._on_handle_scale)
        self.preview_view.rotation_changed.connect(self._on_handle_rotation)
        self.preview_view.position_changed.connect(self._on_handle_position)
        self.preview_view.handles_overlay.transform_started.connect(self._on_transform_started)
        self.preview_view.zoom_changed.connect(self._on_wheel_zoom)
        self.preview_view.arrow_key_pressed.connect(lambda dx, dy: self._on_handle_position(dx, dy))

        # Add panels to layout
        content_layout.addWidget(scroll_area)
        content_layout.addWidget(right_panel, 1)

        layout.addLayout(content_layout)
        self.setFocusPolicy(Qt.StrongFocus)

        # Compatibility stubs for layer toggle buttons (used by _select_layer)
        self.bg_layer_btn = None
        self.logo_layer_btn = None

    def _upload_background(self):
        """Open file dialog to upload background layer (game art)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload Background (Game Art)",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)"
        )

        if not file_path:
            return

        try:
            # Load image
            loaded_image = safe_load_image(file_path, "RGBA")

            # Keep the original image at full resolution — the preview and
            # export pipelines handle scaling via _apply_transformations() and
            # the offset/zoom system, so there's no need to crop to 1024×1024.
            img_w, img_h = loaded_image.size
            self.background_image = loaded_image
            self._update_composite_image()

            # Clear cache
            self.preview_cache = None

            # Update info
            size_mb = Path(file_path).stat().st_size / (1024 * 1024)
            self.bg_info.setText(
                f"Loaded: {Path(file_path).name}\n"
                f"Original: {img_w}x{img_h} ({size_mb:.2f} MB)"
            )
            self.bg_clear_btn.setEnabled(True)
            self.bg_clear_btn.setVisible(True)

            # Reset background adjustments
            self._reset_background_adjustments()

            # Auto-fit: if image is larger than 1024×1024, set initial zoom
            # so the entire image is visible within the export viewport
            if img_w > 1024 or img_h > 1024:
                fit_zoom = min(1024 / img_w, 1024 / img_h)
                self.zoom = fit_zoom
                self._update_transform_info()

            # Select background layer and update handles
            self._select_layer('background')

            # Update preview
            self._schedule_update()

            # Enable export if border is also selected
            self._check_export_ready()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load background:\n{e}")

    def _upload_logo(self):
        """Open file dialog to upload logo overlay layer."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload Logo (Transparent PNG recommended)",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)"
        )

        if not file_path:
            return

        try:
            # Load logo image - keep original size for scaling
            self.logo_image = safe_load_image(file_path, "RGBA")

            # Update composite
            self._update_composite_image()

            # Clear cache
            self.preview_cache = None

            # Update info
            img_w, img_h = self.logo_image.size
            size_mb = Path(file_path).stat().st_size / (1024 * 1024)
            self.logo_info.setText(
                f"Loaded: {Path(file_path).name}\n"
                f"Size: {img_w}x{img_h} ({size_mb:.2f} MB)"
            )
            self.logo_clear_btn.setEnabled(True)

            # Show logo controls and switch to logo layer
            if hasattr(self, 'logo_controls_widget'):
                self.logo_controls_widget.setVisible(True)
            self._select_layer('logo')

            # Update preview
            self._schedule_update()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load logo:\n{e}")

    def _clear_background(self):
        """Clear the background layer."""
        self.background_image = None
        self._update_composite_image()
        self.preview_cache = None
        self.bg_info.setText("No image loaded")
        self.bg_clear_btn.setEnabled(False)
        self.bg_clear_btn.setVisible(False)
        self._schedule_update()
        self._check_export_ready()

    def _clear_logo(self):
        """Clear the logo layer."""
        self.logo_image = None
        self._update_composite_image()
        self.preview_cache = None
        self.logo_info.setText("Transparent PNG overlay")
        self.logo_clear_btn.setEnabled(False)
        if hasattr(self, 'logo_controls_widget'):
            self.logo_controls_widget.setVisible(False)
        self._select_layer('background')
        self._schedule_update()

    def _update_composite_image(self):
        """Update the composite original_image from layers for backward compatibility."""
        # If we have a background, use it as the base
        if self.background_image is not None:
            self.original_image = self.background_image.copy()
        else:
            self.original_image = None

    def _on_platform_changed(self, index: int):
        """Handle platform selection change."""
        platform_key = self.platform_combo.itemData(index)

        if platform_key is None:
            self.current_platform = None
            self.current_border = None
            self.border_info.setText("No border selected")
            self._check_export_ready()
            return

        self.current_platform = platform_key
        platform_data = self.platforms_config.get(platform_key, {})
        border_file = platform_data.get("border_file")

        if border_file:
            self.current_border = self.borders_dir / border_file

            if self.current_border.exists():
                self.border_info.setText(f"Border: {border_file}")
                # Clear border caches when platform changes
                self.border_cache = None
                self.border_mask_cache = None
                self.border_cache_full = None
                self.border_mask_cache_full = None
                self._schedule_update()
            else:
                self.border_info.setText(f"Border file not found: {border_file}")
                self.current_border = None
        else:
            self.current_border = None
            self.border_info.setText("No border file configured")

        self._check_export_ready()

    def _import_custom_border(self):
        """Import a custom border image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Custom Border",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )

        if not file_path:
            return

        try:
            # Load and validate border image
            border_img = safe_load_image(file_path, "RGBA")

            # Check if it's 1024x1024
            if border_img.size != (1024, 1024):
                reply = QMessageBox.question(
                    self,
                    "Resize Border?",
                    f"Border is {border_img.size[0]}x{border_img.size[1]}. Resize to 1024x1024?",
                    QMessageBox.Yes | QMessageBox.No
                )

                if reply == QMessageBox.Yes:
                    border_img = border_img.resize((1024, 1024), Image.LANCZOS)
                else:
                    return

            # Save to a temporary location or use directly
            self.current_border = Path(file_path)
            self.current_platform = "custom"

            # Clear platform combo selection
            self.platform_combo.setCurrentIndex(0)

            # Clear border caches
            self.border_cache = None
            self.border_mask_cache = None
            self.border_cache_full = None
            self.border_mask_cache_full = None

            self.border_info.setText(f"Custom border: {Path(file_path).name}")
            self._schedule_update()
            self._check_export_ready()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load border:\n{e}")

    def _select_layer(self, layer: str):
        """Select which layer to transform."""
        self.active_layer = layer

        # Update active layer indicator label
        if hasattr(self, 'active_layer_label'):
            self.active_layer_label.setText("BG" if layer == 'background' else "Logo")

        # Update preview handles
        self.preview_view.set_active_layer(layer)

        # Update info display for selected layer
        self._update_transform_info()

        # Update handles bounds
        self._update_handle_bounds()

    def _on_lock_aspect_changed(self, state: int):
        """Handle lock aspect ratio checkbox change."""
        self.preview_view.set_lock_aspect_ratio(state == Qt.Checked)

    def _on_transform_started(self):
        """Called when user starts dragging a transform handle."""
        # Store starting values for relative transforms
        self.transform_start_zoom = self.zoom
        self.transform_start_rotation = self.rotation
        self.transform_start_logo_scale = self.logo_scale

    def _on_handle_scale(self, scale_x: float, scale_y: float):
        """Handle scale change from transform handles."""
        if self.active_layer == 'background':
            # Apply scale as multiplier to zoom
            new_zoom = self.transform_start_zoom * scale_x
            new_zoom = max(0.1, min(10.0, new_zoom))  # Allow wider range than before
            self.zoom = new_zoom
        else:
            # Logo layer
            new_scale = self.transform_start_logo_scale * scale_x
            new_scale = max(0.05, min(2.0, new_scale))  # Allow up to 200% for logo
            self.logo_scale = new_scale

        self.preview_cache = None
        self._update_transform_info()
        self._schedule_update()

    def _on_handle_rotation(self, angle_delta: float):
        """Handle rotation change from transform handles."""
        if self.active_layer == 'background':
            new_rotation = self.transform_start_rotation + angle_delta
            # Normalize to -180 to 180 range
            while new_rotation > 180:
                new_rotation -= 360
            while new_rotation < -180:
                new_rotation += 360
            self.rotation = new_rotation
            self.preview_cache = None
            self._update_transform_info()
            self._schedule_update()
        # Logo doesn't have rotation in this implementation

    def _on_handle_position(self, delta_x: float, delta_y: float):
        """Handle position change from transform handles or arrow keys."""
        if self.active_layer == 'background':
            # When zoom < 1.0, the image is smaller than the canvas, so we need to
            # invert the direction to make dragging feel natural (drag image directly
            # rather than panning a viewport)
            if self.zoom < 1.0:
                delta_x = -delta_x
                delta_y = -delta_y
            self.offset_x = max(0.0, min(1.0, self.offset_x + delta_x))
            self.offset_y = max(0.0, min(1.0, self.offset_y + delta_y))
        else:
            # Logo positioning is direct (not viewport-style), so no inversion needed
            # But we invert to match the drag direction expectation
            self.logo_offset_x = max(0.0, min(1.0, self.logo_offset_x - delta_x))
            self.logo_offset_y = max(0.0, min(1.0, self.logo_offset_y - delta_y))

        self._update_transform_info()
        self._schedule_update()

    def _on_wheel_zoom(self, zoom_delta: float):
        """Handle mouse wheel zoom for source image."""
        if self.active_layer == 'background':
            new_zoom = self.zoom + zoom_delta
            new_zoom = max(0.1, min(10.0, new_zoom))  # Wider range than before
            self.zoom = new_zoom
        else:
            new_scale = self.logo_scale + zoom_delta
            new_scale = max(0.05, min(2.0, new_scale))
            self.logo_scale = new_scale

        self.preview_cache = None
        self._update_transform_info()
        self._schedule_update()

    def _on_logo_opacity_changed(self, value: int):
        """Handle logo opacity slider change."""
        self.logo_opacity = value / 100.0
        self.logo_opacity_label.setText(f"{value}%")
        self.preview_cache = None
        self._schedule_update()

    def _on_scale_spinbox_changed(self, value: float):
        """Handle scale spinbox value change."""
        if self.active_layer == 'background':
            self.zoom = value / 100.0
        else:
            self.logo_scale = value / 100.0
        self.preview_cache = None
        self._update_handle_bounds()
        self._schedule_update()

    def _update_transform_info(self):
        """Update the transform info display labels and spinbox."""
        # Block signals to prevent feedback loop when updating spinbox
        self.scale_spinbox.blockSignals(True)
        if self.active_layer == 'background':
            self.scale_spinbox.setValue(self.zoom * 100)
            self.rotation_value_label.setText(f"{self.rotation:.0f}°")
            self.position_value_label.setText(f"{self.offset_x * 100:.0f}%, {self.offset_y * 100:.0f}%")
        else:
            self.scale_spinbox.setValue(self.logo_scale * 100)
            self.rotation_value_label.setText("—")  # Logo doesn't rotate
            self.position_value_label.setText(f"{self.logo_offset_x * 100:.0f}%, {self.logo_offset_y * 100:.0f}%")
        self.scale_spinbox.blockSignals(False)

    def _update_handle_bounds(self):
        """Update the transform handle bounds based on current layer state."""
        if not hasattr(self, 'preview_view'):
            return

        # Get viewport dimensions
        viewport = self.preview_view.viewport()
        view_w = viewport.width()
        view_h = viewport.height()

        if view_w <= 0 or view_h <= 0:
            return

        # Calculate the preview image area within the viewport
        # The preview is fitted to the view, so we need to find the actual image rect
        preview_size = min(view_w, view_h)  # Square preview
        margin_x = (view_w - preview_size) / 2
        margin_y = (view_h - preview_size) / 2

        if self.active_layer == 'background' and self.background_image is not None:
            # Calculate background bounds
            # The background fills the canvas, so the bounding box is the whole preview area
            # adjusted by zoom
            bounds_size = preview_size * self.zoom
            center_x = view_w / 2
            center_y = view_h / 2

            # Adjust center based on offset
            offset_shift_x = (self.offset_x - 0.5) * (bounds_size - preview_size)
            offset_shift_y = (self.offset_y - 0.5) * (bounds_size - preview_size)

            bounds = QRectF(
                center_x - bounds_size / 2 - offset_shift_x,
                center_y - bounds_size / 2 - offset_shift_y,
                bounds_size,
                bounds_size
            )

            self.preview_view.set_transform_bounds(bounds)
            self.preview_view.set_transform_rotation(self.rotation)
            self.preview_view.set_handles_visible(True)

        elif self.active_layer == 'logo' and self.logo_image is not None:
            # Calculate logo bounds
            logo_w, logo_h = self.logo_image.size
            # Scale logo to fit within logo_scale * preview_size while maintaining aspect ratio
            max_logo_dim = preview_size * self.logo_scale
            scale_ratio = min(max_logo_dim / logo_w, max_logo_dim / logo_h)
            scaled_w = logo_w * scale_ratio
            scaled_h = logo_h * scale_ratio

            # Position based on offset
            max_x = preview_size - scaled_w
            max_y = preview_size - scaled_h
            pos_x = margin_x + max_x * self.logo_offset_x
            pos_y = margin_y + max_y * self.logo_offset_y

            bounds = QRectF(pos_x, pos_y, scaled_w, scaled_h)

            self.preview_view.set_transform_bounds(bounds)
            self.preview_view.set_transform_rotation(0)  # Logo doesn't rotate
            self.preview_view.set_handles_visible(True)
        else:
            # No valid layer, hide handles
            self.preview_view.set_handles_visible(False)

    def _reset_current_layer(self):
        """Reset the currently selected layer's transform."""
        if self.active_layer == 'background':
            self._reset_background_adjustments()
        else:
            self._reset_logo_adjustments()

    def _reset_background_adjustments(self):
        """Reset background layer adjustments to defaults."""
        self.rotation = 0.0
        self.zoom = 1.0
        self.offset_x = 0.5
        self.offset_y = 0.5
        self.preview_cache = None
        self._update_transform_info()
        self._update_handle_bounds()
        self._schedule_update()

    def _reset_logo_adjustments(self):
        """Reset logo layer adjustments to defaults."""
        self.logo_scale = 0.5
        self.logo_offset_x = 0.5
        self.logo_offset_y = 0.5
        self.logo_opacity = 1.0
        self.logo_opacity_slider.setValue(100)
        self.preview_cache = None
        self._update_transform_info()
        self._update_handle_bounds()
        self._schedule_update()

    def _reset_adjustments(self):
        """Reset all adjustments to default (both layers)."""
        self._reset_background_adjustments()
        self._reset_logo_adjustments()

    def _schedule_update(self):
        """Schedule a preview update with debouncing."""
        # Restart the timer - only updates after user stops adjusting
        self.update_timer.stop()
        self.update_timer.start(self.debounce_ms)

    def _ensure_border_cache(self):
        """Load and cache border images if needed. Only runs when platform changes."""
        if self.current_border is None or not self.current_border.exists():
            return
        if self.border_cache is not None:
            return  # Already cached

        border = safe_load_image(self.current_border, "RGBA")
        border = ImageOps.exif_transpose(border)

        # Preview size cache
        if border.size != (self.preview_size, self.preview_size):
            preview_border = border.resize((self.preview_size, self.preview_size), Image.BILINEAR)
        else:
            preview_border = border.copy()
        self.border_cache = preview_border
        self.border_mask_cache = corner_mask_from_border(preview_border, threshold=18, shrink_px=8, feather=0.8)

        # Full size cache
        if border.size != (1024, 1024):
            full_border = border.resize((1024, 1024), Image.LANCZOS)
        else:
            full_border = border.copy()
        self.border_cache_full = full_border
        self.border_mask_cache_full = corner_mask_from_border(full_border, threshold=18, shrink_px=8, feather=0.8)

    def _start_preview_worker(self):
        """Start a worker thread to generate the preview."""
        if self.background_image is None and self.logo_image is None:
            return

        # Cancel any existing worker
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_worker.cancel()
            self._preview_worker.quit()
            self._preview_worker.wait(200)

        # Ensure border caches are loaded
        self._ensure_border_cache()

        # Create worker with param copies
        worker = PreviewWorker()
        worker.set_params({
            'background_image': self.background_image.copy() if self.background_image else None,
            'logo_image': self.logo_image.copy() if self.logo_image else None,
            'rotation': self.rotation,
            'zoom': self.zoom,
            'offset_x': self.offset_x,
            'offset_y': self.offset_y,
            'logo_scale': self.logo_scale,
            'logo_offset_x': self.logo_offset_x,
            'logo_offset_y': self.logo_offset_y,
            'logo_opacity': self.logo_opacity,
            'border_cache': self.border_cache,
            'border_mask_cache': self.border_mask_cache,
            'preview_size': self.preview_size,
        })
        worker.preview_ready.connect(self._on_preview_ready)
        worker.error.connect(lambda msg: print(f"Preview worker error: {msg}"))
        self._preview_worker = worker
        worker.start()

    def _on_preview_ready(self, qimage: QImage):
        """Handle preview result from worker thread (runs on main thread)."""
        pixmap = QPixmap.fromImage(qimage)
        self.preview_view.set_image(pixmap)
        self._update_handle_bounds()

    def _apply_transformations(self, img: Image.Image, use_high_quality: bool = False) -> Image.Image:
        """Apply rotation and zoom transformations to the image."""
        resample_method = Image.LANCZOS if use_high_quality else Image.BILINEAR

        # Apply rotation
        if self.rotation != 0:
            img = img.rotate(-self.rotation, expand=True, fillcolor=(0, 0, 0, 0), resample=resample_method)

        # Apply zoom by scaling
        if self.zoom != 1.0:
            w, h = img.size
            new_w = int(w * self.zoom)
            new_h = int(h * self.zoom)
            img = img.resize((new_w, new_h), resample_method)

        return img

    def _compose_preview_unconstrained(self, transformed_img: Image.Image, border_path: Path,
                                       out_size: int, centering: Tuple[float, float]) -> Image.Image:
        """
        Compose preview with border overlay WITHOUT cropping the transformed image.
        Allows image to expand beyond border boundaries.
        """
        # Create canvas at output size with transparency
        canvas = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))

        # Scale the transformed image to match preview size vs export size (1024)
        # This ensures preview and export look the same
        scale_factor = out_size / 1024.0
        if scale_factor != 1.0:
            scaled_w = int(transformed_img.size[0] * scale_factor)
            scaled_h = int(transformed_img.size[1] * scale_factor)
            transformed_img = transformed_img.resize((scaled_w, scaled_h), Image.BILINEAR)

        # Get transformed image size (after scaling for preview)
        img_w, img_h = transformed_img.size

        # Calculate position based on centering (offset_x, offset_y are 0-1 range)
        # The offset controls which part of the image is visible through the border viewport
        # centering=(0.5, 0.5) centers the image
        # centering=(0, 0) shows the left/top of the image
        # centering=(1, 1) shows the right/bottom of the image
        cx, cy = centering

        # Invert the offset for viewport panning behavior:
        # - High horizontal % (0.9) should show the RIGHT side of the image (negative paste_x to shift image left)
        # - Low horizontal % (0.1) should show the LEFT side of the image (less negative or positive paste_x)
        # Formula: paste_x = -(img_w - out_size) * cx
        # Which simplifies to: paste_x = (out_size - img_w) * (1 - cx) when thinking about viewport
        # Actually, let's use: paste_x = -(img_w - out_size) * cx = out_size - img_w - (img_w - out_size) * cx

        # Simpler: invert cx and cy for viewport-style panning
        paste_x = -int((img_w - out_size) * cx)
        paste_y = -int((img_h - out_size) * cy)

        # Paste the transformed image onto the canvas
        canvas.paste(transformed_img, (paste_x, paste_y), transformed_img)

        # Load and prepare border (use cache for performance)
        if out_size == self.preview_size:
            # Preview size - use preview cache
            if self.border_cache is None:
                border = safe_load_image(border_path, "RGBA")
                border = ImageOps.exif_transpose(border)
                if border.size != (out_size, out_size):
                    border = border.resize((out_size, out_size), Image.BILINEAR)
                self.border_cache = border
                self.border_mask_cache = corner_mask_from_border(border, threshold=18, shrink_px=8, feather=0.8)

            border = self.border_cache
            mask = self.border_mask_cache
        else:
            # Full size - use full cache
            if self.border_cache_full is None:
                border = safe_load_image(border_path, "RGBA")
                border = ImageOps.exif_transpose(border)
                if border.size != (out_size, out_size):
                    border = border.resize((out_size, out_size), Image.LANCZOS)
                self.border_cache_full = border
                self.border_mask_cache_full = corner_mask_from_border(border, threshold=18, shrink_px=8, feather=0.8)

            border = self.border_cache_full
            mask = self.border_mask_cache_full

        # Apply border mask to canvas
        canvas.putalpha(ImageChops.multiply(canvas.split()[-1], mask))

        # Composite border on top
        result = Image.alpha_composite(canvas, border)

        return result

    def _composite_logo_on_canvas(self, canvas: Image.Image, canvas_size: int,
                                    use_high_quality: bool = False) -> Image.Image:
        """Composite the logo layer onto a canvas at the specified position and scale."""
        if self.logo_image is None:
            return canvas

        resample_method = Image.LANCZOS if use_high_quality else Image.BILINEAR

        # Calculate logo size based on scale (relative to canvas)
        logo_w, logo_h = self.logo_image.size
        # Maintain aspect ratio - scale to fit within logo_scale * canvas_size
        max_logo_size = int(canvas_size * self.logo_scale)
        scale_ratio = min(max_logo_size / logo_w, max_logo_size / logo_h)
        new_logo_w = int(logo_w * scale_ratio)
        new_logo_h = int(logo_h * scale_ratio)

        # Resize logo
        scaled_logo = self.logo_image.resize((new_logo_w, new_logo_h), resample_method)

        # Apply opacity if not full
        if self.logo_opacity < 1.0:
            # Create a copy and modify alpha
            r, g, b, a = scaled_logo.split()
            a = a.point(lambda x: int(x * self.logo_opacity))
            scaled_logo = Image.merge("RGBA", (r, g, b, a))

        # Calculate position based on offset (0-1 range)
        # At 0.5, logo is centered. At 0, logo is at left/top edge. At 1, logo is at right/bottom edge.
        max_x = canvas_size - new_logo_w
        max_y = canvas_size - new_logo_h
        paste_x = int(max_x * self.logo_offset_x)
        paste_y = int(max_y * self.logo_offset_y)

        # Composite logo onto canvas
        canvas.paste(scaled_logo, (paste_x, paste_y), scaled_logo)

        return canvas

    def _do_update_preview(self):
        """Actually update the preview (called by debounce timer)."""
        # Need at least background or logo to show preview
        if self.background_image is None and self.logo_image is None:
            return

        try:
            # Use centering based on offset sliders (for background)
            centering = (self.offset_x, self.offset_y)

            # Start with a transparent canvas at preview size
            result_canvas = Image.new("RGBA", (self.preview_size, self.preview_size), (0, 0, 0, 0))

            # Layer 1: Background (with transformations)
            if self.background_image is not None:
                # Apply transformations to background
                transformed_bg = self._apply_transformations(self.background_image.copy())

                # Scale for preview
                scale_factor = self.preview_size / 1024.0
                if scale_factor != 1.0:
                    scaled_w = int(transformed_bg.size[0] * scale_factor)
                    scaled_h = int(transformed_bg.size[1] * scale_factor)
                    transformed_bg = transformed_bg.resize((scaled_w, scaled_h), Image.BILINEAR)

                # Position background on canvas
                img_w, img_h = transformed_bg.size
                cx, cy = centering
                paste_x = -int((img_w - self.preview_size) * cx)
                paste_y = -int((img_h - self.preview_size) * cy)
                result_canvas.paste(transformed_bg, (paste_x, paste_y), transformed_bg)

            # Layer 2: Logo overlay
            if self.logo_image is not None:
                result_canvas = self._composite_logo_on_canvas(result_canvas, self.preview_size)

            # Apply border if selected
            if self.current_border and self.current_border.exists():
                # Load and prepare border (use cache)
                if self.border_cache is None:
                    border = safe_load_image(self.current_border, "RGBA")
                    border = ImageOps.exif_transpose(border)
                    if border.size != (self.preview_size, self.preview_size):
                        border = border.resize((self.preview_size, self.preview_size), Image.BILINEAR)
                    self.border_cache = border
                    self.border_mask_cache = corner_mask_from_border(border, threshold=18, shrink_px=8, feather=0.8)

                border = self.border_cache
                mask = self.border_mask_cache

                # Apply border mask to canvas
                result_canvas.putalpha(ImageChops.multiply(result_canvas.split()[-1], mask))

                # Composite border on top
                result_canvas = Image.alpha_composite(result_canvas, border)

            # Convert to QPixmap for display
            qimage = ImageQt.ImageQt(result_canvas)
            pixmap = QPixmap.fromImage(qimage)

            # Update preview
            self.preview_view.set_image(pixmap)

            # Update transform handle bounds after preview is set
            self._update_handle_bounds()

        except Exception as e:
            print(f"Preview update error: {e}")
            import traceback
            traceback.print_exc()

    def _check_export_ready(self):
        """Check if export is ready and update button state."""
        # Need at least background image and a border to export
        has_content = self.background_image is not None or self.logo_image is not None
        has_border = self.current_border is not None and self.current_border.exists()
        ready = has_content and has_border

        self.export_btn.setEnabled(ready)

        if ready:
            layers_info = []
            if self.background_image is not None:
                layers_info.append("background")
            if self.logo_image is not None:
                layers_info.append("logo")
            self.export_info.setText(f"Ready to export ({' + '.join(layers_info)}) at 1024x1024")
        elif not has_content:
            self.export_info.setText("Upload a background or logo to export")
        elif self.current_border is None:
            self.export_info.setText("Select a platform to export")
        else:
            self.export_info.setText("Border file not found")

    def _export_image(self):
        """Export the final image with border at full resolution (supports layers)."""
        if not self.export_btn.isEnabled():
            return

        # Get save path
        default_name = f"{self.current_platform}_custom.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Image",
            default_name,
            "PNG Image (*.png);;All Files (*)"
        )

        if not file_path:
            return

        try:
            # Create canvas at full resolution
            canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
            centering = (self.offset_x, self.offset_y)

            # Layer 1: Background with transformations
            if self.background_image is not None:
                print(f"[Export] Processing background layer...")
                print(f"[Export] Background settings: rotation={self.rotation}°, zoom={self.zoom*100}%, offset=({self.offset_x}, {self.offset_y})")

                # Apply transformations to background with HIGH QUALITY
                transformed_bg = self._apply_transformations(self.background_image.copy(), use_high_quality=True)

                # Position on canvas
                img_w, img_h = transformed_bg.size
                cx, cy = centering
                paste_x = -int((img_w - 1024) * cx)
                paste_y = -int((img_h - 1024) * cy)
                print(f"[Export] Background size: {img_w}x{img_h}, position: ({paste_x}, {paste_y})")

                canvas.paste(transformed_bg, (paste_x, paste_y), transformed_bg)

            # Layer 2: Logo overlay
            if self.logo_image is not None:
                print(f"[Export] Processing logo layer...")
                print(f"[Export] Logo settings: scale={self.logo_scale*100}%, pos=({self.logo_offset_x*100}%, {self.logo_offset_y*100}%), opacity={self.logo_opacity*100}%")
                canvas = self._composite_logo_on_canvas(canvas, 1024, use_high_quality=True)

            # Load and prepare border at full resolution
            border = safe_load_image(self.current_border, "RGBA")
            border = ImageOps.exif_transpose(border)
            if border.size != (1024, 1024):
                border = border.resize((1024, 1024), Image.LANCZOS)

            # Apply border mask to canvas
            mask = corner_mask_from_border(border, threshold=18, shrink_px=8, feather=0.8)
            canvas.putalpha(ImageChops.multiply(canvas.split()[-1], mask))

            # Composite border on top
            result = Image.alpha_composite(canvas, border)

            # Save
            result.save(file_path, "PNG")

            # Create summary message
            summary = f"Image exported successfully at 1024x1024 to:\n{file_path}\n\n"
            summary += f"Layers:\n"
            if self.background_image is not None:
                summary += f"  • Background: rotation={self.rotation}°, zoom={int(self.zoom * 100)}%\n"
                summary += f"    Position: H={int(self.offset_x * 100)}%, V={int(self.offset_y * 100)}%\n"
            if self.logo_image is not None:
                summary += f"  • Logo: size={int(self.logo_scale * 100)}%, opacity={int(self.logo_opacity * 100)}%\n"
                summary += f"    Position: H={int(self.logo_offset_x * 100)}%, V={int(self.logo_offset_y * 100)}%\n"

            QMessageBox.information(
                self,
                "Export Complete",
                summary
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export image:\n{e}"
            )
            import traceback
            traceback.print_exc()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle arrow keys for fine position adjustments."""
        # Need at least a background to adjust position
        if self.background_image is None:
            super().keyPressEvent(event)
            return

        # Arrow key step size (0.01 = 1% adjustment)
        step = 0.01

        if event.key() == Qt.Key_Left:
            self._on_position_changed(-step, 0)
            event.accept()
        elif event.key() == Qt.Key_Right:
            self._on_position_changed(step, 0)
            event.accept()
        elif event.key() == Qt.Key_Up:
            self._on_position_changed(0, -step)
            event.accept()
        elif event.key() == Qt.Key_Down:
            self._on_position_changed(0, step)
            event.accept()
        else:
            super().keyPressEvent(event)
