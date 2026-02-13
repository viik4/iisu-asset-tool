"""
Border Generator V3 for iiSU Icon Generator
Uses PSD template for pixel-perfect borders with gradient and icon replacement.
"""

import sys
from pathlib import Path
from typing import Optional
import numpy as np

from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QColor, QIcon, QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog,
    QGroupBox, QColorDialog, QComboBox, QMessageBox, QSlider, QSpinBox,
    QFrame
)
from PySide6.QtSvg import QSvgRenderer
from io import BytesIO
from psd_tools import PSDImage
from app_paths import get_templates_dir, get_borders_dir, get_platform_icons_dir
from iisu_image_utils import safe_load_image


def load_svg_as_image(svg_path: str, size: int = 512) -> Image.Image:
    """
    Load an SVG file and convert it to a PIL Image.

    Args:
        svg_path: Path to SVG file
        size: Size to render the SVG (will maintain aspect ratio)

    Returns:
        PIL Image in RGBA format
    """
    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG file: {svg_path}")

    # Get the default size and maintain aspect ratio
    default_size = renderer.defaultSize()
    aspect_ratio = default_size.width() / default_size.height()

    if aspect_ratio > 1:
        width = size
        height = int(size / aspect_ratio)
    else:
        width = int(size * aspect_ratio)
        height = size

    # Create QImage and render SVG
    qimage = QImage(width, height, QImage.Format_ARGB32)
    qimage.fill(Qt.transparent)

    from PySide6.QtGui import QPainter
    from PySide6.QtCore import QBuffer, QIODevice

    painter = QPainter(qimage)
    # Disable anti-aliasing for crisp pixel-perfect rendering
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    renderer.render(painter)
    painter.end()

    # Convert QImage to PIL Image using QBuffer
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    qimage.save(buffer, "PNG")
    buffer.close()

    # Read from buffer and convert to PIL
    pil_image = safe_load_image(bytes(buffer.data()), "RGBA")

    return pil_image


def make_icon_white(img: Image.Image) -> Image.Image:
    """
    Convert uploaded icon to white with preserved transparency.
    """
    img = img.convert("RGBA")
    data = np.array(img)

    # Extract alpha channel
    alpha = data[:, :, 3]

    # Create white version preserving alpha
    white_data = np.zeros_like(data)
    white_data[:, :, :3] = 255  # Set RGB to white
    white_data[:, :, 3] = alpha  # Preserve original alpha channel

    return Image.fromarray(white_data.astype('uint8'), 'RGBA')


def create_gradient(size: tuple, color1: QColor, color2: QColor, angle: int) -> Image.Image:
    """Create a gradient image."""
    width, height = size
    gradient = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(gradient)

    c1 = (color1.red(), color1.green(), color1.blue(), 255)
    c2 = (color2.red(), color2.green(), color2.blue(), 255)

    # Create gradient based on angle
    if angle == 0:  # Horizontal
        for x in range(width):
            t = x / width
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            draw.line([(x, 0), (x, height)], fill=(r, g, b, 255))
    elif angle == 90:  # Vertical
        for y in range(height):
            t = y / height
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
    else:  # Diagonal
        for y in range(height):
            for x in range(width):
                if angle == 45:
                    t = (x + (height - y)) / (width + height)
                elif angle == 135:
                    t = (x + y) / (width + height)
                elif angle == 225:
                    t = ((width - x) + y) / (width + height)
                else:  # 315
                    t = ((width - x) + (height - y)) / (width + height)

                t = max(0, min(1, t))
                r = int(c1[0] + (c2[0] - c1[0]) * t)
                g = int(c1[1] + (c2[1] - c1[1]) * t)
                b = int(c1[2] + (c2[2] - c1[2]) * t)
                draw.point((x, y), fill=(r, g, b, 255))

    return gradient


def create_border_from_psd(color1: QColor, color2: QColor, gradient_angle: int,
                           icon_image: Optional[Image.Image] = None,
                           psd_path: Optional[str] = None,
                           icon_scale: int = 100,
                           icon_centering: tuple = (0.5, 0.5)) -> Image.Image:
    """
    Create border using PSD template with gradient and icon replacement.

    Path: Game Template > Border Group > Gradient (edit)
    Icon: Game Template > Border Group > Icon Group > Example Icon (replace)

    Args:
        icon_scale: Scale percentage for icon (100 = full 93x93, 50 = 46x46, etc.)
        icon_centering: (cx, cy) tuple for icon positioning within bbox (0.5, 0.5 = center)
    """
    # Load PSD template (use absolute path from project root)
    if psd_path is None:
        psd_path = get_templates_dir() / "iisuTemplates.psd"
    psd = PSDImage.open(str(psd_path))

    # Find Game Template layer
    game_template = None
    for layer in psd:
        if layer.name == 'Game Template':
            game_template = layer
            break

    if not game_template:
        raise ValueError("Could not find 'Game Template' layer in PSD")

    # Find Border Group within Game Template
    border_group = None
    for layer in game_template:
        if layer.name == 'Border Group':
            border_group = layer
            break

    if not border_group:
        raise ValueError("Could not find 'Border Group' layer in PSD")

    # Composite the border group to get the mask/shape
    border_composite = border_group.composite()

    # Extract the alpha channel as the border mask
    border_mask = border_composite.split()[3] if border_composite.mode == 'RGBA' else None

    # Create custom gradient
    gradient = create_gradient(border_composite.size, color1, color2, gradient_angle)

    # Apply the border mask to the gradient
    if border_mask:
        result = Image.new("RGBA", border_composite.size, (0, 0, 0, 0))
        result.paste(gradient, (0, 0), border_mask)
    else:
        result = border_composite

    # Replace icon if provided
    if icon_image:
        # Bounding box: 43px from top/left, 888px from right/bottom (in 1024x1024 image)
        # This gives us a 93x93 pixel area: from (43, 43) to (136, 136)
        bbox_left = 43
        bbox_top = 43
        bbox_size = 93  # 1024 - 888 - 43 = 93

        # Apply scale factor (icon_scale is percentage, 100 = full bbox size)
        max_size = int(bbox_size * (icon_scale / 100))
        white_icon = make_icon_white(icon_image)

        # Resize icon with LANCZOS for better quality
        # Use thumbnail to maintain aspect ratio within max_size bounds
        white_icon.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        # Apply icon centering within bounding box (or centered on bbox if larger)
        icon_w, icon_h = white_icon.size
        cx, cy = icon_centering

        # Calculate paste position using centering parameters
        # cx, cy range from 0.0 to 1.0, where 0.5, 0.5 is center
        # For icons larger than bbox, center them on the bbox center point
        bbox_center_x = bbox_left + bbox_size // 2
        bbox_center_y = bbox_top + bbox_size // 2

        if icon_w > bbox_size or icon_h > bbox_size:
            # For larger icons, center on bbox center with offset based on centering params
            offset_range_x = (icon_w - bbox_size) // 2
            offset_range_y = (icon_h - bbox_size) // 2
            paste_x = bbox_center_x - icon_w // 2 + int((cx - 0.5) * 2 * offset_range_x)
            paste_y = bbox_center_y - icon_h // 2 + int((cy - 0.5) * 2 * offset_range_y)
        else:
            # For smaller icons, position within bbox
            paste_x = bbox_left + int((bbox_size - icon_w) * cx)
            paste_y = bbox_top + int((bbox_size - icon_h) * cy)

        result.paste(white_icon, (paste_x, paste_y), white_icon)

    return result


class BorderPreview(QLabel):
    """Preview widget for PSD-based borders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 400)
        self.setMaximumSize(512, 512)
        self.setScaledContents(True)
        self.setObjectName("preview_border_frame")

        self.color1 = QColor("#D4849C")  # Pink from example
        self.color2 = QColor("#E5B559")  # Gold from example
        self.gradient_angle = 135
        self.icon_image = None
        self.icon_scale = 100  # Icon scale percentage (100 = fill 93x93 bbox)

        # Centering for icon positioning (0.5, 0.5 = center)
        self.icon_centering = (0.5, 0.5)

        # Dragging state
        self._dragging = False
        self._last_pos = None

        # Track if PSD is available
        self._psd_available = False
        self._psd_error = None

        # Debounce timer for performance
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_update)

        self._check_psd_availability()
        # Don't schedule_update() here — defer PSD rendering to first user interaction

    def _check_psd_availability(self):
        """Quick file-exists check. Full PSD validation is deferred to first use."""
        psd_path = get_templates_dir() / "iisuTemplates.psd"
        if psd_path.exists():
            self._psd_available = True
            self._psd_error = None
        else:
            self._psd_available = False
            self._psd_error = f"PSD template not found at: {psd_path}"
            print(f"[BorderPreview] {self._psd_error}")

    def set_color1(self, color: QColor):
        self.color1 = color
        self.schedule_update()

    def set_color2(self, color: QColor):
        self.color2 = color
        self.schedule_update()

    def set_gradient_angle(self, angle: int):
        self.gradient_angle = angle
        self.schedule_update()

    def set_icon(self, image: Optional[Image.Image]):
        self.icon_image = image
        self.schedule_update()

    def set_icon_scale(self, scale: int):
        self.icon_scale = scale
        self.schedule_update()

    def schedule_update(self):
        """Debounced update to prevent lag."""
        self._update_timer.stop()
        self._update_timer.start(50)  # Reduced to 50ms for better responsiveness

    def _do_update(self):
        """Actually perform the update."""
        # Check if PSD is available first
        if not self._psd_available:
            self._show_error_preview(self._psd_error or "PSD template not available")
            return

        try:
            border = create_border_from_psd(self.color1, self.color2, self.gradient_angle, self.icon_image,
                                           icon_scale=self.icon_scale, icon_centering=self.icon_centering)

            # Resize for preview
            preview_size = 512
            border.thumbnail((preview_size, preview_size), Image.Resampling.LANCZOS)

            # Convert to QPixmap efficiently
            img_bytes = border.tobytes("raw", "RGBA")
            qimage = QImage(img_bytes, border.width, border.height, QImage.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimage)

            self.setPixmap(pixmap)

            # Clear memory
            del border
            del qimage
        except Exception as e:
            error_msg = f"Error: {e}"
            print(f"[BorderPreview] {error_msg}")
            import traceback
            traceback.print_exc()
            self._show_error_preview(error_msg)

    def _show_error_preview(self, message: str):
        """Display an error message in the preview area."""
        # Create a simple error image
        error_img = Image.new("RGBA", (512, 512), (40, 44, 52, 255))
        draw = ImageDraw.Draw(error_img)
        # Draw error text (simple, no custom font needed)
        draw.text((256, 240), "Template Error", fill=(255, 100, 100, 255), anchor="mm")
        # Wrap long messages
        if len(message) > 50:
            lines = [message[i:i+45] for i in range(0, len(message), 45)]
            y = 270
            for line in lines[:4]:  # Max 4 lines
                draw.text((256, y), line, fill=(180, 180, 180, 255), anchor="mm")
                y += 20
        else:
            draw.text((256, 270), message, fill=(180, 180, 180, 255), anchor="mm")

        img_bytes = error_img.tobytes("raw", "RGBA")
        qimage = QImage(img_bytes, 512, 512, QImage.Format_RGBA8888)
        self.setPixmap(QPixmap.fromImage(qimage))

    def export_border(self, output_path: Path):
        """Export full resolution border."""
        border = create_border_from_psd(self.color1, self.color2, self.gradient_angle, self.icon_image,
                                       icon_scale=self.icon_scale, icon_centering=self.icon_centering)
        border.save(output_path, "PNG")
        del border

    def mousePressEvent(self, event):
        """Handle mouse press for dragging icon."""
        if self.icon_image and event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging icon."""
        if self._dragging and self._last_pos:
            delta = event.pos() - self._last_pos
            self._last_pos = event.pos()

            # Convert pixel delta to centering delta
            # The icon is in a 93x93 area, adjust sensitivity
            cx, cy = self.icon_centering
            cx += delta.x() / self.width() * 0.3
            cy += delta.y() / self.height() * 0.3

            # Clamp to [0, 1]
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))

            self.icon_centering = (cx, cy)
            self.schedule_update()

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)


class BorderGeneratorTab(QWidget):
    """Border generator tab using PSD template."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._custom_icon_loaded = False  # Track if user uploaded a custom icon
        self.init_ui()

    def init_ui(self):
        from PySide6.QtWidgets import QScrollArea, QFrame, QSizePolicy

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # ── Left panel: Controls (scrollable) ──
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFixedWidth(320)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(5, 5, 10, 5)

        # ── Gradient Colors card ──
        color_card = QFrame()
        color_card.setObjectName("card")
        color_card_layout = QVBoxLayout(color_card)
        color_card_layout.setContentsMargins(10, 10, 10, 10)
        color_card_layout.setSpacing(6)

        color_title = QLabel("Gradient Colors")
        color_title.setObjectName("label_card_title")
        color_card_layout.addWidget(color_title)

        # Color 1
        color1_row = QHBoxLayout()
        color1_row.setSpacing(8)
        c1_lbl = QLabel("Color 1:")
        c1_lbl.setObjectName("label_info")
        color1_row.addWidget(c1_lbl)
        self.color1_preview = QLabel()
        self.color1_preview.setFixedSize(30, 30)
        self.color1_preview.setObjectName("color_swatch")
        self.color1_preview.setStyleSheet("background: #D4849C;")
        self.color1_preview.setCursor(Qt.PointingHandCursor)
        self.color1_preview.mousePressEvent = lambda e: self.choose_color1()
        color1_row.addWidget(self.color1_preview)
        self.color1_btn = QPushButton("Choose")
        self.color1_btn.setObjectName("btn_small")
        self.color1_btn.setMinimumHeight(24)
        self.color1_btn.clicked.connect(self.choose_color1)
        color1_row.addWidget(self.color1_btn)
        color1_row.addStretch()
        color_card_layout.addLayout(color1_row)

        # Color 2
        color2_row = QHBoxLayout()
        color2_row.setSpacing(8)
        c2_lbl = QLabel("Color 2:")
        c2_lbl.setObjectName("label_info")
        color2_row.addWidget(c2_lbl)
        self.color2_preview = QLabel()
        self.color2_preview.setFixedSize(30, 30)
        self.color2_preview.setObjectName("color_swatch")
        self.color2_preview.setStyleSheet("background: #E5B559;")
        self.color2_preview.setCursor(Qt.PointingHandCursor)
        self.color2_preview.mousePressEvent = lambda e: self.choose_color2()
        color2_row.addWidget(self.color2_preview)
        self.color2_btn = QPushButton("Choose")
        self.color2_btn.setObjectName("btn_small")
        self.color2_btn.setMinimumHeight(24)
        self.color2_btn.clicked.connect(self.choose_color2)
        color2_row.addWidget(self.color2_btn)
        color2_row.addStretch()
        color_card_layout.addLayout(color2_row)

        # Gradient angle
        angle_row = QHBoxLayout()
        angle_row.setSpacing(8)
        angle_lbl = QLabel("Angle:")
        angle_lbl.setObjectName("label_info")
        angle_row.addWidget(angle_lbl)
        self.angle_combo = QComboBox()
        self.angle_combo.addItems(["0° →", "45° ↗", "90° ↑", "135° ↖", "225° ↙", "315° ↘"])
        self.angle_combo.setCurrentIndex(3)  # 135° default
        self.angle_combo.currentIndexChanged.connect(self.update_angle)
        angle_row.addWidget(self.angle_combo, 1)
        color_card_layout.addLayout(angle_row)

        left_layout.addWidget(color_card)

        # ── Platform Icon card ──
        icon_card = QFrame()
        icon_card.setObjectName("card")
        icon_card_layout = QVBoxLayout(icon_card)
        icon_card_layout.setContentsMargins(10, 10, 10, 10)
        icon_card_layout.setSpacing(6)

        icon_title = QLabel("Platform Icon")
        icon_title.setObjectName("label_card_title")
        icon_card_layout.addWidget(icon_title)

        self.icon_path_label = QLabel("No icon selected")
        self.icon_path_label.setWordWrap(True)
        self.icon_path_label.setObjectName("label_muted")
        icon_card_layout.addWidget(self.icon_path_label)

        icon_btn_row = QHBoxLayout()
        icon_btn_row.setSpacing(6)
        self.btn_load_icon = QPushButton("Load Icon")
        self.btn_load_icon.setObjectName("btn_primary")
        self.btn_load_icon.setMinimumHeight(30)
        self.btn_load_icon.clicked.connect(self.load_icon)
        self.btn_clear_icon = QPushButton("Clear")
        self.btn_clear_icon.setObjectName("btn_clear")
        self.btn_clear_icon.setMinimumHeight(30)
        self.btn_clear_icon.clicked.connect(self.clear_icon)
        icon_btn_row.addWidget(self.btn_load_icon)
        icon_btn_row.addWidget(self.btn_clear_icon)
        icon_card_layout.addLayout(icon_btn_row)

        # Icon scale
        scale_row = QHBoxLayout()
        scale_row.setSpacing(6)
        scale_lbl = QLabel("Scale:")
        scale_lbl.setObjectName("label_info")
        scale_lbl.setMinimumWidth(40)
        scale_row.addWidget(scale_lbl)

        self.icon_scale_slider = QSlider(Qt.Horizontal)
        self.icon_scale_slider.setMinimum(10)
        self.icon_scale_slider.setMaximum(300)
        self.icon_scale_slider.setValue(100)
        self.icon_scale_slider.valueChanged.connect(self.update_icon_scale)
        scale_row.addWidget(self.icon_scale_slider, 1)

        self.icon_scale_spinbox = QSpinBox()
        self.icon_scale_spinbox.setMinimum(10)
        self.icon_scale_spinbox.setMaximum(300)
        self.icon_scale_spinbox.setValue(100)
        self.icon_scale_spinbox.setSuffix("%")
        self.icon_scale_spinbox.valueChanged.connect(self.update_icon_scale_from_spinbox)
        scale_row.addWidget(self.icon_scale_spinbox)
        icon_card_layout.addLayout(scale_row)

        icon_hint = QLabel("Icon is rendered in white over the gradient")
        icon_hint.setObjectName("label_muted")
        icon_card_layout.addWidget(icon_hint)

        left_layout.addWidget(icon_card)

        # ── Platform Presets card ──
        preset_card = QFrame()
        preset_card.setObjectName("card")
        preset_card_layout = QVBoxLayout(preset_card)
        preset_card_layout.setContentsMargins(10, 10, 10, 10)
        preset_card_layout.setSpacing(6)

        preset_title = QLabel("Platform Presets")
        preset_title.setObjectName("label_card_title")
        preset_card_layout.addWidget(preset_title)

        self.platform_preset_combo = QComboBox()
        self._setup_platform_presets()
        self.platform_preset_combo.currentIndexChanged.connect(self._apply_platform_preset)
        preset_card_layout.addWidget(self.platform_preset_combo)

        # Quick color presets
        quick_lbl = QLabel("Quick Colors:")
        quick_lbl.setObjectName("label_muted")
        preset_card_layout.addWidget(quick_lbl)

        preset_btns = QHBoxLayout()
        preset_btns.setSpacing(4)
        btn_pink_gold = QPushButton("Pink-Gold")
        btn_pink_gold.setObjectName("btn_small")
        btn_pink_gold.setMinimumHeight(26)
        btn_pink_gold.clicked.connect(lambda: self.apply_preset("#D4849C", "#E5B559"))
        btn_purple = QPushButton("Purple")
        btn_purple.setObjectName("btn_small")
        btn_purple.setMinimumHeight(26)
        btn_purple.clicked.connect(lambda: self.apply_preset("#2B1FD0", "#B71AEB"))
        preset_btns.addWidget(btn_pink_gold)
        preset_btns.addWidget(btn_purple)
        preset_card_layout.addLayout(preset_btns)

        preset_btns2 = QHBoxLayout()
        preset_btns2.setSpacing(4)
        btn_cyan = QPushButton("Cyan-Teal")
        btn_cyan.setObjectName("btn_small")
        btn_cyan.setMinimumHeight(26)
        btn_cyan.clicked.connect(lambda: self.apply_preset("#00DDFF", "#067DBA"))
        btn_green = QPushButton("Cyan-Green")
        btn_green.setObjectName("btn_small")
        btn_green.setMinimumHeight(26)
        btn_green.clicked.connect(lambda: self.apply_preset("#007C92", "#8FFFB1"))
        preset_btns2.addWidget(btn_cyan)
        preset_btns2.addWidget(btn_green)
        preset_card_layout.addLayout(preset_btns2)

        left_layout.addWidget(preset_card)

        # ── Export card ──
        export_card = QFrame()
        export_card.setObjectName("card")
        export_card_layout = QVBoxLayout(export_card)
        export_card_layout.setContentsMargins(10, 10, 10, 10)
        export_card_layout.setSpacing(6)

        self.btn_export = QPushButton("Export Border")
        self.btn_export.setObjectName("btn_export")
        self.btn_export.setMinimumHeight(40)
        self.btn_export.clicked.connect(self.export_border)
        export_card_layout.addWidget(self.btn_export)

        left_layout.addWidget(export_card)

        left_layout.addStretch()
        scroll_area.setWidget(left_panel)

        # ── Right panel: Preview ──
        right_panel = QFrame()
        right_panel.setObjectName("preview_panel")
        right_panel.setMinimumWidth(400)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)

        preview_header = QHBoxLayout()
        preview_title = QLabel("Preview")
        preview_title.setObjectName("label_card_title")
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        preview_help = QLabel("Drag icon to reposition | Scroll to zoom")
        preview_help.setObjectName("label_muted")
        preview_header.addWidget(preview_help)
        right_layout.addLayout(preview_header)

        self.preview = BorderPreview()
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setMaximumSize(16777215, 16777215)  # Remove max size constraint
        right_layout.addWidget(self.preview, 1, Qt.AlignCenter)

        # Add panels to layout
        content_layout.addWidget(scroll_area)
        content_layout.addWidget(right_panel, 1)

        layout.addLayout(content_layout)

    def choose_color1(self):
        color = QColorDialog.getColor(self.preview.color1, self, "Choose Gradient Color 1")
        if color.isValid():
            self.preview.set_color1(color)
            self.color1_preview.setStyleSheet(f"background: {color.name()};")

    def choose_color2(self):
        color = QColorDialog.getColor(self.preview.color2, self, "Choose Gradient Color 2")
        if color.isValid():
            self.preview.set_color2(color)
            self.color2_preview.setStyleSheet(f"background: {color.name()};")

    def update_angle(self, index):
        angles = [0, 45, 90, 135, 225, 315]
        self.preview.set_gradient_angle(angles[index])

    def load_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Platform Icon",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.svg *.bmp *.webp);;All Files (*)"
        )

        if path:
            try:
                # Check if it's an SVG and handle accordingly
                if path.lower().endswith('.svg'):
                    icon = load_svg_as_image(path, size=93)
                else:
                    # Load raster image
                    icon = safe_load_image(path, "RGBA")

                self.preview.set_icon(icon)
                self.icon_path_label.setText(Path(path).name)
                self._custom_icon_loaded = True  # Mark that user uploaded custom icon
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load icon: {e}")

    def clear_icon(self):
        self.preview.set_icon(None)
        self.icon_path_label.setText("No icon selected")
        self._custom_icon_loaded = False  # Reset custom icon flag

    def update_icon_scale(self, value: int):
        """Update icon scale from slider."""
        self.icon_scale_spinbox.blockSignals(True)
        self.icon_scale_spinbox.setValue(value)
        self.icon_scale_spinbox.blockSignals(False)
        self.preview.set_icon_scale(value)

    def update_icon_scale_from_spinbox(self, value: int):
        """Update icon scale from spinbox."""
        self.icon_scale_slider.blockSignals(True)
        self.icon_scale_slider.setValue(value)
        self.icon_scale_slider.blockSignals(False)
        self.preview.set_icon_scale(value)

    def apply_preset(self, color1: str, color2: str):
        c1 = QColor(color1)
        c2 = QColor(color2)
        self.preview.set_color1(c1)
        self.preview.set_color2(c2)
        self.color1_preview.setStyleSheet(f"background: {color1};")
        self.color2_preview.setStyleSheet(f"background: {color2};")

    def export_border(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Border",
            str(get_borders_dir() / "border.png"),
            "PNG Image (*.png)"
        )

        if path:
            try:
                if not path.endswith('.png'):
                    path += '.png'
                self.preview.export_border(Path(path))
                QMessageBox.information(self, "Export Success", f"Border saved to:\n{path}")
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to export border: {e}")

    def _setup_platform_presets(self):
        """Setup platform preset dropdown with colors from existing borders."""
        # Platform presets: (display_name, icon_filename, color1, color2)
        # Colors extracted from border images (top-left and bottom-right corners)
        self.platform_presets = [
            ("Select Platform...", None, None, None),
            ("Android", "Android.png", "#30dd81", "#a4dad5"),
            ("Arcade", "Arcade.png", "#ff9f00", "#ff0000"),
            ("Dreamcast", "Dreamcast.png", "#ff8400", "#db5823"),
            ("eShop", "eshop.png", "#f47c20", "#d68494"),
            ("Game Boy", "Game_Boy.png", "#88c99d", "#b3b1b4"),
            ("Game Boy Advance", "Game_Boy_Advance.png", "#6550ce", "#95a6c9"),
            ("Game Boy Color", "Game_Boy_Color.png", "#ffcc00", "#97c633"),
            ("Game Gear", "GAME_GEAR.png", "#ee4164", "#80daaa"),
            ("GameCube", "GAMECUBE.png", "#8863ff", "#8d96dc"),
            ("Genesis", "GENESIS.png", "#0060a8", "#c23c5d"),
            ("N64", "N64.png", "#2fb752", "#d64762"),
            ("Neo Geo Pocket Color", "Neo_Geo_Pocket_Color.png", "#f25656", "#d5a96c"),
            ("NES", "NES.png", "#e27a8c", "#cdbf39"),
            ("Nintendo 3DS", "NINTENDO_3DS.png", "#ffb400", "#db81a6"),
            ("Nintendo DS", "NINTENDO_DS.png", "#ff72a1", "#9ad7dc"),
            ("PlayStation", "PS1.png", "#a6b4b8", "#b29edc"),
            ("PlayStation 2", "PS2.png", "#4642ea", "#b05cff"),
            ("PlayStation 3", "PS3.png", "#0059ff", "#0019c2"),
            ("PlayStation 4", "PS4.png", "#0290d4", "#02497d"),
            ("PS Vita", "PS_VITA.png", "#964aff", "#5aa4d5"),
            ("PSP", "PSP.png", "#ff41e2", "#8357dc"),
            ("Saturn", "SATURN.png", "#5e6ba0", "#ca7072"),
            ("SNES", "SNES.png", "#f32b4c", "#928cc9"),
            ("Switch", "Switch.png", "#ff0000", "#db7176"),
            ("Wii", "Wii.png", "#14b5eb", "#b6d8dc"),
            ("Wii U", "Wii_U.png", "#03a9f4", "#c1daa7"),
            ("Xbox", "Xbox.png", "#007a00", "#001b00"),
            ("Xbox 360", "Xbox_360.png", "#bdf001", "#57c201"),
        ]

        for preset in self.platform_presets:
            self.platform_preset_combo.addItem(preset[0])

    def _apply_platform_preset(self, index: int):
        """Apply selected platform preset (icon and colors)."""
        if index <= 0:  # "Select Platform..." option
            return

        preset = self.platform_presets[index]
        _, icon_filename, color1, color2 = preset

        # Only load the platform icon if no custom icon was uploaded
        # This preserves user's custom icon when changing presets
        if not self._custom_icon_loaded and icon_filename:
            icon_path = get_platform_icons_dir() / icon_filename
            if icon_path.exists():
                try:
                    icon = safe_load_image(icon_path, "RGBA")
                    self.preview.set_icon(icon)
                    self.icon_path_label.setText(icon_filename)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to load icon: {e}")

        # Apply gradient colors
        if color1 and color2:
            self.apply_preset(color1, color2)
