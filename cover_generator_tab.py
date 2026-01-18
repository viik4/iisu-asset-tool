"""
Cover Generator for iiSU Icon Generator
Uses PSD template's Cover Group to create game covers with custom artwork, gradients, and icons.
"""

from pathlib import Path
from typing import Optional
import numpy as np
from collections import deque

from PIL import Image, ImageDraw, ImageChops, ImageFilter
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog,
    QGroupBox, QColorDialog, QMessageBox,
    QSlider, QSpinBox, QComboBox
)
from psd_tools import PSDImage
from app_paths import get_templates_dir, get_src_dir, get_platform_icons_dir


# Global caches to avoid repeated file loading and processing
_psd_cache = {}
_border_cache = {}
_grid_cache = {}


def get_cached_psd(psd_path: Path):
    """Get cached PSD data or load and cache it."""
    global _psd_cache
    path_str = str(psd_path)
    if path_str not in _psd_cache:
        psd = PSDImage.open(path_str)
        _psd_cache[path_str] = psd
    return _psd_cache[path_str]


def get_cached_border(psd_path: Path, size: int = 1024):
    """Get cached border composite at specified size."""
    global _border_cache
    cache_key = (str(psd_path), size)
    if cache_key not in _border_cache:
        psd = get_cached_psd(psd_path)
        # Find Group Template and Border Group
        for layer in psd:
            if layer.name == 'Group Template':
                for sublayer in layer:
                    if sublayer.name == 'Border Group':
                        border = sublayer.composite()
                        if border.size != (1024, 1024):
                            border = border.crop((0, 0, 1024, 1024))
                        if size != 1024:
                            border = border.resize((size, size), Image.LANCZOS)
                        _border_cache[cache_key] = border
                        break
                break
    return _border_cache.get(cache_key)


def get_cached_grid(size: int = 1024):
    """Get cached dot grid at specified size."""
    global _grid_cache
    if size not in _grid_cache:
        grid_path = get_src_dir() / "grid.png"
        if grid_path.exists():
            grid = Image.open(grid_path).convert("RGBA")
            if grid.size != (size, size):
                grid = grid.resize((size, size), Image.LANCZOS)
            _grid_cache[size] = grid
    return _grid_cache.get(size)


def fill_center_hole(alpha: Image.Image) -> Image.Image:
    """Fill the center hole of a border mask using flood fill."""
    a = alpha.convert("L")
    w, h = a.size
    px = a.load()
    cx, cy = w // 2, h // 2
    if px[cx, cy] != 0:
        return a
    q = deque([(cx, cy)])
    visited = {(cx, cy)}
    while q:
        x, y = q.popleft()
        px[x, y] = 255
        for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                if px[nx, ny] == 0:
                    visited.add((nx, ny))
                    q.append((nx, ny))
    return a


def corner_mask_from_border(border_rgba: Image.Image, threshold: int = 18, shrink_px: int = 8, feather: float = 0.8) -> Image.Image:
    """Create a corner mask from a border to crop content to rounded corners."""
    border_alpha = border_rgba.split()[-1].convert("L")
    hard = border_alpha.point(lambda p: 255 if p >= threshold else 0, mode="L")
    hard = fill_center_hole(hard)
    if shrink_px > 0:
        hard = hard.filter(ImageFilter.MinFilter(2 * shrink_px + 1))
    if feather and feather > 0:
        hard = hard.filter(ImageFilter.GaussianBlur(radius=feather))
    return hard


def make_icon_white(img: Image.Image) -> Image.Image:
    """Convert uploaded icon to white with preserved transparency."""
    img = img.convert("RGBA")
    data = np.array(img)

    # Extract alpha channel
    alpha = data[:, :, 3]

    # Create white version preserving alpha
    white_data = np.zeros_like(data)
    white_data[:, :, :3] = 255  # Set RGB to white
    white_data[:, :, 3] = alpha  # Preserve original alpha channel

    return Image.fromarray(white_data.astype('uint8'), 'RGBA')


def create_gradient(size: tuple, color1: QColor, color2: QColor, angle: int = 135) -> Image.Image:
    """Create a gradient image for cover overlay using vectorized numpy operations."""
    width, height = size

    c1 = np.array([color1.red(), color1.green(), color1.blue()], dtype=np.float32)
    c2 = np.array([color2.red(), color2.green(), color2.blue()], dtype=np.float32)

    # Create coordinate grids using vectorized operations
    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    # Calculate interpolation factor t for diagonal gradient
    t = (xx + yy) / (width + height)
    t = np.clip(t, 0, 1)

    # Vectorized color interpolation
    gradient_data = np.zeros((height, width, 4), dtype=np.uint8)
    for i in range(3):  # RGB channels
        gradient_data[:, :, i] = (c1[i] + (c2[i] - c1[i]) * t).astype(np.uint8)
    gradient_data[:, :, 3] = 255  # Full alpha

    return Image.fromarray(gradient_data, 'RGBA')


def apply_vivid_light_blend(base: Image.Image, blend: Image.Image) -> Image.Image:
    """Apply Vivid Light blend mode (used by PSD gradient layer)."""
    base = base.convert("RGB")
    blend = blend.convert("RGB")

    base_data = np.array(base, dtype=np.float32) / 255.0
    blend_data = np.array(blend, dtype=np.float32) / 255.0

    result = np.zeros_like(base_data)

    # Vivid Light blend mode:
    # If blend > 0.5: Color Dodge -> base / (2 * (1 - blend))
    # If blend <= 0.5: Color Burn -> 1 - ((1 - base) / (2 * blend))

    mask_dodge = blend_data > 0.5
    mask_burn = blend_data <= 0.5

    # Color Dodge
    dodge_blend = 2.0 * (blend_data - 0.5)
    result[mask_dodge] = np.minimum(base_data[mask_dodge] / np.maximum(1.0 - dodge_blend[mask_dodge], 0.001), 1.0)

    # Color Burn
    burn_blend = 2.0 * blend_data
    result[mask_burn] = np.maximum(1.0 - ((1.0 - base_data[mask_burn]) / np.maximum(burn_blend[mask_burn], 0.001)), 0.0)

    result = np.clip(result * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(result, 'RGB')


def create_cover_from_template(
    artwork_image: Optional[Image.Image] = None,
    gradient_color1: QColor = QColor("#D4849C"),
    gradient_color2: QColor = QColor("#E5B559"),
    icon_image: Optional[Image.Image] = None,
    psd_path: Optional[Path] = None,
    centering: tuple = (0.5, 0.5),
    scale: float = 1.0,
    preview_size: int = 1024,
    icon_scale: int = 100
) -> Image.Image:
    """
    Generate a cover image from the PSD template's Cover Group.

    Args:
        artwork_image: Custom artwork to replace the game image
        gradient_color1: First gradient color
        gradient_color2: Second gradient color
        icon_image: Platform icon to replace the example icon
        psd_path: Path to PSD template (defaults to templates/iisuTemplates.psd)
        centering: Tuple (x, y) for artwork centering (0-1 range)
        scale: Zoom scale for artwork
        preview_size: Output size (use smaller for faster preview, 1024 for export)

    Returns:
        PIL Image of the generated cover (preview_size x preview_size RGBA)
    """
    # Load PSD template (cached)
    if psd_path is None:
        psd_path = get_templates_dir() / "iisuTemplates.psd"
    psd = get_cached_psd(psd_path)

    # Scale factor for preview mode
    scale_factor = preview_size / 1024.0
    target_size = preview_size

    # Find Group Template
    group_template = None
    for layer in psd:
        if layer.name == 'Group Template':
            group_template = layer
            break

    if not group_template:
        raise ValueError("Could not find 'Group Template' in PSD")

    # Find Cover Group
    cover_group = None
    for layer in group_template:
        if layer.name == 'Cover Group':
            cover_group = layer
            break

    if not cover_group:
        raise ValueError("Could not find 'Cover Group' in Group Template")

    # Start with the base composite of the cover group
    # We'll rebuild it layer by layer with replacements
    result = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))

    # Process each layer in Cover Group
    for layer in cover_group:
        if layer.name == 'Image Group':
            # Handle artwork replacement - replicate PSD layer structure exactly
            # Order (bottom to top): Genshin Impact -> Adjustment (-100 sat) -> Color (white) -> Gradient (Vivid Light)
            if artwork_image:
                # Layer 1: Artwork (replaces "Genshin Impact" smartobject)
                art_copy = artwork_image.copy().convert("RGBA")

                # Resize artwork to cover the canvas with scale factor
                art_w, art_h = art_copy.size

                # Scale to cover the canvas
                if art_w / art_h > 1:  # Wider than tall
                    new_h = target_size
                    new_w = int(art_w * (target_size / art_h))
                else:  # Taller than wide
                    new_w = target_size
                    new_h = int(art_h * (target_size / art_w))

                # Apply scale factor (zoom)
                new_w = int(new_w * scale)
                new_h = int(new_h * scale)

                # Use faster resize for preview, LANCZOS for export
                resample = Image.BILINEAR if target_size < 1024 else Image.LANCZOS
                art_copy = art_copy.resize((new_w, new_h), resample)

                # Crop to target_size using centering parameters
                cx, cy = centering
                left = int((new_w - target_size) * cx)
                top = int((new_h - target_size) * cy)
                # Clamp to valid range
                left = max(0, min(left, new_w - target_size))
                top = max(0, min(top, new_h - target_size))
                art_copy = art_copy.crop((left, top, left + target_size, top + target_size))

                result.paste(art_copy, (0, 0), art_copy)

                # Store the artwork alpha for clipping masks
                artwork_alpha = art_copy.split()[3]

                # Layer 2: Adjustment (clipping mask on artwork, -100 saturation)
                # Desaturate the artwork completely (convert to grayscale while preserving alpha)
                from PIL import ImageEnhance
                result_rgb = result.convert("RGB")
                enhancer = ImageEnhance.Color(result_rgb)
                result_rgb = enhancer.enhance(0.0)  # 0.0 = full desaturation (-100 saturation)
                result = result_rgb.convert("RGBA")
                result.putalpha(artwork_alpha)  # Clipped to artwork shape

                # Layer 3: Color (Don't edit) - White color fill at 80% fill
                # Clipping mask: only visible where Adjustment layer (artwork) is visible
                # Using 80% fill means the white is at 80% opacity
                white_layer = Image.new("RGBA", (target_size, target_size), (255, 255, 255, 204))  # 80% fill = 204 alpha
                # Clip to artwork shape
                white_layer.putalpha(ImageChops.multiply(white_layer.split()[3], artwork_alpha))
                result = Image.alpha_composite(result, white_layer)

                # Layer 4: Gradient (edit) - VIVID LIGHT blend mode at 10% fill
                # Create gradient and apply Vivid Light blend
                gradient = create_gradient((target_size, target_size), gradient_color1, gradient_color2)

                # Apply Vivid Light blend to get the blended result
                result_rgb = apply_vivid_light_blend(result, gradient)

                # Convert back to RGBA with artwork alpha as clipping mask
                result_blended = result_rgb.convert("RGBA")
                result_blended.putalpha(artwork_alpha)

                # Apply 10% fill by blending 10% of the gradient effect with the original
                # Note: Increasing this value makes the gradient more visible
                result = Image.blend(result, result_blended, 0.20)  # Increased to 20% for better visibility
            # If no artwork, skip the Image Group entirely

        elif layer.name == 'Dot Grid':
            # Dot Grid at 5% opacity using cached grid
            dot_grid = get_cached_grid(target_size)
            if dot_grid:
                # Apply 5% opacity (create a copy to avoid modifying cache)
                dot_grid = dot_grid.copy()
                dot_grid_array = np.array(dot_grid, dtype=np.float32)
                dot_grid_array[:, :, 3] *= 0.05  # 5% opacity
                dot_grid = Image.fromarray(dot_grid_array.astype(np.uint8), 'RGBA')
                result = Image.alpha_composite(result, dot_grid)

        elif layer.name == 'Icon Group':
            # Handle icon replacement
            if icon_image:
                # The icon bbox is (225, 350, 799, 674) at 1024 - scale it
                bbox_x1 = int(225 * scale_factor)
                bbox_y1 = int(350 * scale_factor)
                bbox_x2 = int(799 * scale_factor)
                bbox_y2 = int(674 * scale_factor)
                bbox_w = bbox_x2 - bbox_x1
                bbox_h = bbox_y2 - bbox_y1

                icon_copy = icon_image.copy().convert("RGBA")

                # Make icon white
                white_icon = make_icon_white(icon_copy)

                # Resize icon to fit the bbox while maintaining aspect ratio
                # Apply icon_scale percentage (100 = fit bbox, smaller = smaller icon)
                icon_w, icon_h = white_icon.size
                scale_w = bbox_w / icon_w
                scale_h = bbox_h / icon_h
                fit_scale = min(scale_w, scale_h)  # Fit within bbox
                # Apply user's icon_scale percentage
                final_scale = fit_scale * (icon_scale / 100.0)
                new_icon_w = int(icon_w * final_scale)
                new_icon_h = int(icon_h * final_scale)
                white_icon = white_icon.resize((new_icon_w, new_icon_h), Image.LANCZOS)

                # Create gradient for the icon
                icon_gradient = create_gradient(white_icon.size, gradient_color1, gradient_color2)

                # Apply gradient to white icon using multiply blend
                # Create a canvas for the colored icon
                colored_icon = Image.new("RGBA", white_icon.size, (0, 0, 0, 0))
                # Blend the gradient with the white icon
                colored_icon.paste(icon_gradient, (0, 0))
                # Use the white icon's alpha as a mask
                colored_icon.putalpha(white_icon.split()[-1])

                # Center the icon in the bbox
                icon_w, icon_h = colored_icon.size
                paste_x = bbox_x1 + (bbox_w - icon_w) // 2
                paste_y = bbox_y1 + (bbox_h - icon_h) // 2

                result.paste(colored_icon, (paste_x, paste_y), colored_icon)
            else:
                # No custom icon, use template's Icon Group composite
                icon_group_composite = layer.composite()
                # Scale to target size
                if icon_group_composite.size != (target_size, target_size):
                    # Create canvas and paste the icon group at correct scaled position
                    icon_canvas = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
                    # Scale the icon group
                    if target_size != 1024:
                        icon_group_composite = icon_group_composite.resize(
                            (int(icon_group_composite.size[0] * scale_factor),
                             int(icon_group_composite.size[1] * scale_factor)),
                            Image.LANCZOS
                        )
                    # The bbox is (225, 350) at 1024, scaled
                    paste_x = int(225 * scale_factor)
                    paste_y = int(350 * scale_factor)
                    icon_canvas.paste(icon_group_composite, (paste_x, paste_y), icon_group_composite)
                    icon_group_composite = icon_canvas
                result = Image.alpha_composite(result, icon_group_composite)

    # Now add the Border Group from Group Template with custom gradient (using cache)
    border_composite = get_cached_border(psd_path, target_size)

    if border_composite:
        # Apply corner masking to the content before adding border
        # This clips the content to match the border's rounded corners
        # Scale shrink_px for preview mode
        shrink_scaled = max(1, int(8 * scale_factor))
        feather_scaled = max(0.2, 0.8 * scale_factor)
        corner_mask = corner_mask_from_border(border_composite, threshold=18, shrink_px=shrink_scaled, feather=feather_scaled)
        result.putalpha(ImageChops.multiply(result.split()[-1], corner_mask))

        # Extract the alpha channel as the border mask
        border_mask = border_composite.split()[3] if border_composite.mode == 'RGBA' else None

        # Create custom gradient for the border
        border_gradient = create_gradient((target_size, target_size), gradient_color1, gradient_color2)

        # Apply the border mask to the gradient
        if border_mask:
            border_result = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
            border_result.paste(border_gradient, (0, 0), border_mask)
        else:
            border_result = border_composite

        # Composite the border on top of the cover
        result = Image.alpha_composite(result, border_result)

    return result


class CoverPreview(QLabel):
    """Preview widget for cover generator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 400)
        self.setMaximumSize(512, 512)
        self.setScaledContents(True)
        self.setStyleSheet("border: 2px solid #3A4048; border-radius: 8px;")

        self.artwork_image = None
        self.gradient_color1 = QColor("#D4849C")
        self.gradient_color2 = QColor("#E5B559")
        self.icon_image = None
        self.icon_scale = 100  # Icon scale percentage (100 = full size)

        # Centering for artwork positioning
        self.centering = (0.5, 0.5)

        # Scale for zoom (1.0 = default, >1.0 = zoomed in, <1.0 = zoomed out)
        self.scale = 1.0

        # Dragging state
        self._dragging = False
        self._last_pos = None

        # Track if PSD is available
        self._psd_available = False
        self._psd_error = None
        self._check_psd_availability()

        # Debounce timer
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_update)

        # Don't schedule update on init - wait for user to upload artwork
        # Show a placeholder text or error
        if self._psd_available:
            self.setText("Upload artwork to generate cover preview")
        else:
            self.setText(f"Template Error:\n{self._psd_error}")
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "border: 2px solid #3A4048; border-radius: 8px; "
            "color: #666; font-size: 14px;"
        )

    def _check_psd_availability(self):
        """Check if the PSD template file exists and can be loaded."""
        psd_path = get_templates_dir() / "iisuTemplates.psd"
        if not psd_path.exists():
            self._psd_available = False
            self._psd_error = f"PSD template not found at: {psd_path}"
            print(f"[CoverPreview] {self._psd_error}")
            return

        # Try to actually load the PSD to verify it works
        try:
            test_psd = PSDImage.open(str(psd_path))
            # Verify we can find the expected layers
            found_group_template = False
            for layer in test_psd:
                if layer.name == 'Group Template':
                    found_group_template = True
                    break
            if not found_group_template:
                self._psd_available = False
                self._psd_error = "PSD loaded but 'Group Template' layer not found"
                print(f"[CoverPreview] {self._psd_error}")
                return
            self._psd_available = True
            self._psd_error = None
            print(f"[CoverPreview] PSD template loaded successfully from: {psd_path}")
        except Exception as e:
            self._psd_available = False
            self._psd_error = f"Failed to load PSD: {e}"
            print(f"[CoverPreview] {self._psd_error}")
            import traceback
            traceback.print_exc()

    def set_artwork(self, image: Image.Image):
        self.artwork_image = image
        self.schedule_update()

    def set_gradient_color1(self, color: QColor):
        self.gradient_color1 = color
        self.schedule_update()

    def set_gradient_color2(self, color: QColor):
        self.gradient_color2 = color
        self.schedule_update()

    def set_icon(self, image: Image.Image):
        self.icon_image = image
        self.schedule_update()

    def set_icon_scale(self, scale: int):
        self.icon_scale = scale
        self.schedule_update()

    def schedule_update(self, immediate=False):
        self._update_timer.stop()
        if immediate:
            self._do_update()
        else:
            self._update_timer.start(50)  # Reduced to 50ms for more responsive feedback

    def _do_update(self):
        # Only generate preview if artwork has been uploaded
        if self.artwork_image is None:
            return

        # Check if PSD is available
        if not self._psd_available:
            self._show_error_preview(self._psd_error or "PSD template not available")
            return

        try:
            # Clear placeholder text and reset style
            self.setText("")
            self.setStyleSheet("border: 2px solid #3A4048; border-radius: 8px;")

            # Use lower resolution for preview (512px instead of 1024px)
            # This provides 4x faster processing while still looking good at preview size
            cover_img = create_cover_from_template(
                artwork_image=self.artwork_image,
                gradient_color1=self.gradient_color1,
                gradient_color2=self.gradient_color2,
                icon_image=self.icon_image,
                centering=self.centering,
                scale=self.scale,
                preview_size=512,  # Half resolution for fast preview
                icon_scale=self.icon_scale
            )

            # Convert to QPixmap for display
            from PIL.ImageQt import ImageQt
            qimage = ImageQt(cover_img)
            pixmap = QPixmap.fromImage(qimage)
            self.setPixmap(pixmap)

        except Exception as e:
            error_msg = f"Error: {e}"
            print(f"[CoverPreview] {error_msg}")
            import traceback
            traceback.print_exc()
            self._show_error_preview(error_msg)

    def _show_error_preview(self, message: str):
        """Display an error message in the preview area."""
        from PySide6.QtGui import QImage
        # Create a simple error image
        error_img = Image.new("RGBA", (512, 512), (40, 44, 52, 255))
        draw = ImageDraw.Draw(error_img)
        # Draw error text
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

    def mousePressEvent(self, event):
        if self.artwork_image and event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._dragging and self._last_pos:
            delta = event.pos() - self._last_pos
            self._last_pos = event.pos()

            # Convert pixel delta to centering delta
            # Smaller sensitivity for finer control
            cx, cy = self.centering
            cx += delta.x() / self.width() * 0.5
            cy += delta.y() / self.height() * 0.5

            # Clamp to [0, 1]
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))

            self.centering = (cx, cy)
            self.schedule_update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming artwork."""
        if self.artwork_image:
            # Get the scroll delta
            delta = event.angleDelta().y()

            # Adjust scale based on wheel direction
            # Positive delta = scroll up = zoom in
            # Negative delta = scroll down = zoom out
            zoom_factor = 1.1 if delta > 0 else 0.9

            new_scale = self.scale * zoom_factor

            # Clamp scale to reasonable range (0.5x to 3x)
            new_scale = max(0.5, min(3.0, new_scale))

            if new_scale != self.scale:
                self.scale = new_scale
                self.schedule_update()

            event.accept()


class CoverGeneratorTab(QWidget):
    """Tab for generating game covers using PSD template."""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Left panel - Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(350)

        # Title
        title = QLabel("Cover Generator")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        left_layout.addWidget(title)

        # Artwork upload section
        artwork_group = QGroupBox("Game Artwork")
        artwork_layout = QVBoxLayout(artwork_group)

        upload_artwork_btn = QPushButton("Upload Artwork")
        upload_artwork_btn.clicked.connect(self._upload_artwork)
        artwork_layout.addWidget(upload_artwork_btn)

        self.artwork_info = QLabel("No artwork uploaded")
        self.artwork_info.setStyleSheet("font-size: 11px; opacity: 0.7;")
        self.artwork_info.setWordWrap(True)
        artwork_layout.addWidget(self.artwork_info)

        left_layout.addWidget(artwork_group)

        # Gradient colors section
        gradient_group = QGroupBox("Gradient Overlay")
        gradient_layout = QVBoxLayout(gradient_group)

        # Color 1
        color1_row = QHBoxLayout()
        color1_row.addWidget(QLabel("Color 1:"))
        self.color1_btn = QPushButton()
        self.color1_btn.setMaximumWidth(50)
        self.color1_btn.clicked.connect(self._pick_color1)
        self.color1_btn.setStyleSheet("background-color: #D4849C; border: 1px solid #666;")
        color1_row.addWidget(self.color1_btn)
        color1_row.addStretch()
        gradient_layout.addLayout(color1_row)

        # Color 2
        color2_row = QHBoxLayout()
        color2_row.addWidget(QLabel("Color 2:"))
        self.color2_btn = QPushButton()
        self.color2_btn.setMaximumWidth(50)
        self.color2_btn.clicked.connect(self._pick_color2)
        self.color2_btn.setStyleSheet("background-color: #E5B559; border: 1px solid #666;")
        color2_row.addWidget(self.color2_btn)
        color2_row.addStretch()
        gradient_layout.addLayout(color2_row)

        left_layout.addWidget(gradient_group)

        # Icon upload section
        icon_group = QGroupBox("Platform Icon")
        icon_layout = QVBoxLayout(icon_group)

        # Platform preset dropdown
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.platform_preset_combo = QComboBox()
        self._setup_platform_presets()
        self.platform_preset_combo.currentIndexChanged.connect(self._apply_platform_preset)
        preset_row.addWidget(self.platform_preset_combo, 1)
        icon_layout.addLayout(preset_row)

        upload_icon_btn = QPushButton("Upload Custom Icon")
        upload_icon_btn.clicked.connect(self._upload_icon)
        icon_layout.addWidget(upload_icon_btn)

        self.icon_info = QLabel("No icon uploaded")
        self.icon_info.setStyleSheet("font-size: 11px; opacity: 0.7;")
        self.icon_info.setWordWrap(True)
        icon_layout.addWidget(self.icon_info)

        # Icon scale control
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Size:"))

        self.icon_scale_slider = QSlider(Qt.Horizontal)
        self.icon_scale_slider.setMinimum(10)
        self.icon_scale_slider.setMaximum(100)
        self.icon_scale_slider.setValue(100)
        self.icon_scale_slider.setTickPosition(QSlider.TicksBelow)
        self.icon_scale_slider.setTickInterval(10)
        self.icon_scale_slider.valueChanged.connect(self._update_icon_scale)
        scale_row.addWidget(self.icon_scale_slider)

        self.icon_scale_spinbox = QSpinBox()
        self.icon_scale_spinbox.setMinimum(10)
        self.icon_scale_spinbox.setMaximum(100)
        self.icon_scale_spinbox.setValue(100)
        self.icon_scale_spinbox.setSuffix("%")
        self.icon_scale_spinbox.valueChanged.connect(self._update_icon_scale_from_spinbox)
        scale_row.addWidget(self.icon_scale_spinbox)

        icon_layout.addLayout(scale_row)

        left_layout.addWidget(icon_group)

        # Export section
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout(export_group)

        export_btn = QPushButton("Export Cover (1024x1024)")
        export_btn.setMinimumHeight(40)
        export_btn.clicked.connect(self._export_cover)
        export_layout.addWidget(export_btn)

        left_layout.addWidget(export_group)
        left_layout.addStretch()

        # Right panel - Preview (centered)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setAlignment(Qt.AlignCenter)

        preview_label = QLabel("Preview")
        preview_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        preview_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(preview_label)

        self.preview = CoverPreview()
        right_layout.addWidget(self.preview)
        right_layout.addStretch()

        # Add panels to main layout
        layout.addWidget(left_panel, 0)
        layout.addWidget(right_panel, 1)

    def _upload_artwork(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload Artwork",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)"
        )

        if not file_path:
            return

        try:
            artwork = Image.open(file_path).convert("RGBA")
            self.preview.set_artwork(artwork)

            width, height = artwork.size
            self.artwork_info.setText(f"Loaded: {Path(file_path).name}\nSize: {width}x{height}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load artwork:\n{e}")

    def _upload_icon(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload Icon",
            "",
            "Images (*.png *.jpg *.jpeg *.svg *.bmp);;All Files (*)"
        )

        if not file_path:
            return

        try:
            icon = Image.open(file_path).convert("RGBA")
            self.preview.set_icon(icon)

            width, height = icon.size
            self.icon_info.setText(f"Loaded: {Path(file_path).name}\nSize: {width}x{height}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load icon:\n{e}")

    def _pick_color1(self):
        color = QColorDialog.getColor(self.preview.gradient_color1, self, "Select Gradient Color 1")
        if color.isValid():
            self.preview.set_gradient_color1(color)
            self.color1_btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #666;")

    def _pick_color2(self):
        color = QColorDialog.getColor(self.preview.gradient_color2, self, "Select Gradient Color 2")
        if color.isValid():
            self.preview.set_gradient_color2(color)
            self.color2_btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #666;")

    def _export_cover(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Cover",
            "cover.png",
            "PNG Image (*.png);;All Files (*)"
        )

        if not file_path:
            return

        try:
            cover_img = create_cover_from_template(
                artwork_image=self.preview.artwork_image,
                gradient_color1=self.preview.gradient_color1,
                gradient_color2=self.preview.gradient_color2,
                icon_image=self.preview.icon_image,
                centering=self.preview.centering,
                scale=self.preview.scale,
                icon_scale=self.preview.icon_scale
            )

            cover_img.save(file_path, "PNG")

            QMessageBox.information(
                self,
                "Success",
                f"Cover exported successfully to:\n{file_path}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export cover:\n{e}")

    def _update_icon_scale(self, value: int):
        """Update icon scale from slider."""
        self.icon_scale_spinbox.blockSignals(True)
        self.icon_scale_spinbox.setValue(value)
        self.icon_scale_spinbox.blockSignals(False)
        self.preview.set_icon_scale(value)

    def _update_icon_scale_from_spinbox(self, value: int):
        """Update icon scale from spinbox."""
        self.icon_scale_slider.blockSignals(True)
        self.icon_scale_slider.setValue(value)
        self.icon_scale_slider.blockSignals(False)
        self.preview.set_icon_scale(value)

    def _setup_platform_presets(self):
        """Setup platform preset dropdown with colors from existing platform icons."""
        # Platform presets: (display_name, icon_filename, color1, color2)
        self.platform_presets = [
            ("Select Platform...", None, None, None),
            ("Android", "Android.png", "#69e6a4", "#c8fff8"),
            ("Arcade", "Arcade.png", "#ff9f00", "#ff0000"),
            ("Dreamcast", "Dreamcast.png", "#f89837", "#ff7d46"),
            ("eShop", "eshop.png", "#f79d5a", "#faa8b6"),
            ("Game Boy", "Game_Boy.png", "#a5d7b5", "#d6d7d7"),
            ("Game Boy Advance", "Game_Boy_Advance.png", "#8e7fdb", "#b8c9ec"),
            ("Game Boy Color", "Game_Boy_Color.png", "#ffda45", "#b4e54b"),
            ("Game Gear", "GAME_GEAR.png", "#f3718a", "#a2ffcd"),
            ("GameCube", "GAMECUBE.png", "#a186fd", "#aeb6ff"),
            ("Genesis", "GENESIS.png", "#3d83ba", "#e55b7a"),
            ("N64", "N64.png", "#62c77b", "#f26078"),
            ("Neo Geo Pocket Color", "Neo_Geo_Pocket_Color.png", "#f68484", "#f8ca88"),
            ("NES", "NES.png", "#ea9aa6", "#f1e457"),
            ("Nintendo 3DS", "NINTENDO_3DS.png", "#fdc13c", "#fe9fc2"),
            ("Nintendo DS", "NINTENDO_DS.png", "#fc91b4", "#bdfcff"),
            ("PlayStation", "PS1.png", "#bcc6cb", "#d5bfff"),
            ("PlayStation 2", "PS2.png", "#7370f0", "#c183ff"),
            ("PlayStation 3", "PS3.png", "#005dff", "#0020c8"),
            ("PlayStation 4", "PS4.png", "#0091d6", "#004a7f"),
            ("PS Vita", "PS_VITA.png", "#b079ff", "#7fc9f8"),
            ("PSP", "PSP.png", "#ff75ea", "#9f72fb"),
            ("Saturn", "SATURN.png", "#7f89b1", "#ea8b8c"),
            ("SNES", "SNES.png", "#f45e77", "#aba4e1"),
            ("Switch", "Switch.png", "#fc3e3e", "#ff9093"),
            ("Wii", "Wii.png", "#55c9f0", "#d0f6fb"),
            ("Wii U", "Wii_U.png", "#3db9f2", "#e2ffc8"),
            ("Xbox", "Xbox.png", "#007a00", "#001b00"),
            ("Xbox 360", "Xbox_360.png", "#b7f000", "#3dc100"),
        ]

        for preset in self.platform_presets:
            self.platform_preset_combo.addItem(preset[0])

    def _apply_platform_preset(self, index: int):
        """Apply selected platform preset (icon and colors)."""
        if index <= 0:  # "Select Platform..." option
            return

        preset = self.platform_presets[index]
        _, icon_filename, color1, color2 = preset

        # Load the platform icon
        if icon_filename:
            icon_path = get_platform_icons_dir() / icon_filename
            if icon_path.exists():
                try:
                    icon = Image.open(icon_path).convert("RGBA")
                    self.preview.set_icon(icon)
                    self.icon_info.setText(f"Loaded: {icon_filename}")
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to load icon: {e}")

        # Apply gradient colors
        if color1 and color2:
            c1 = QColor(color1)
            c2 = QColor(color2)
            self.preview.set_gradient_color1(c1)
            self.preview.set_gradient_color2(c2)
            self.color1_btn.setStyleSheet(f"background-color: {color1}; border: 1px solid #666;")
            self.color2_btn.setStyleSheet(f"background-color: {color2}; border: 1px solid #666;")
