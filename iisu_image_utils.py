"""
iiSU Image Utilities

Shared image loading, caching, and safety utilities for the desktop app.
Addresses:
- File handle leaks from unclosed Image.open() calls
- Redundant disk I/O from re-loading thumbnails
- Main-thread blocking from full-resolution image decoding
"""

import threading
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class ThumbnailCache:
    """
    Thread-safe, memory-based LRU cache for QPixmap thumbnails.
    Prevents redundant disk reads when navigating game lists.
    """

    def __init__(self, max_entries: int = 300):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def _make_key(self, path: str, size: int) -> str:
        return f"{path}:{size}"

    def get(self, path: str, size: int) -> QPixmap | None:
        """Get a cached pixmap, or None if not cached."""
        key = self._make_key(path, size)
        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, path: str, pixmap: QPixmap, size: int):
        """Store a pixmap in cache, evicting oldest if over capacity."""
        key = self._make_key(path, size)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = pixmap
            else:
                self._cache[key] = pixmap
                if len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)

    def invalidate(self, path: str):
        """Remove all cached sizes for a given path."""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(f"{path}:")]
            for k in keys_to_remove:
                del self._cache[k]

    def clear(self):
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)


# Module-level singleton
_thumbnail_cache: ThumbnailCache | None = None
_cache_lock = threading.Lock()


def get_thumbnail_cache() -> ThumbnailCache:
    """Get the global thumbnail cache singleton."""
    global _thumbnail_cache
    if _thumbnail_cache is None:
        with _cache_lock:
            if _thumbnail_cache is None:
                _thumbnail_cache = ThumbnailCache(max_entries=300)
    return _thumbnail_cache


def safe_load_image(source, mode: str = "RGBA") -> Image.Image:
    """
    Safely load a PIL Image with proper resource management.

    Opens the image, converts to the requested mode, returns a .copy()
    so the underlying file handle is released immediately.

    Args:
        source: File path (str/Path), bytes, or BytesIO
        mode: PIL image mode to convert to (default "RGBA")

    Returns:
        A copy of the loaded image (file handle closed).

    Raises:
        FileNotFoundError: If source is a path that doesn't exist
        PIL.UnidentifiedImageError: If source is not a valid image
    """
    if isinstance(source, (str, Path)):
        with Image.open(str(source)) as img:
            if img.mode != mode:
                converted = img.convert(mode)
                result = converted.copy()
                converted.close()
                return result
            return img.copy()
    elif isinstance(source, bytes):
        with Image.open(BytesIO(source)) as img:
            if img.mode != mode:
                converted = img.convert(mode)
                result = converted.copy()
                converted.close()
                return result
            return img.copy()
    elif isinstance(source, BytesIO):
        with Image.open(source) as img:
            if img.mode != mode:
                converted = img.convert(mode)
                result = converted.copy()
                converted.close()
                return result
            return img.copy()
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")


def load_scaled_pixmap(path: str, max_size: int = 128, cache: ThumbnailCache | None = None) -> QPixmap:
    """
    Load a QPixmap scaled to max_size, with optional caching.

    Checks cache first. If not cached, loads from disk, scales with
    smooth transformation, and stores in cache.

    Args:
        path: File path to the image
        max_size: Maximum dimension (width or height) for the thumbnail
        cache: ThumbnailCache instance (uses global singleton if None)

    Returns:
        Scaled QPixmap (or null pixmap if file doesn't exist/is invalid)
    """
    if cache is None:
        cache = get_thumbnail_cache()

    # Check cache first
    cached = cache.get(path, max_size)
    if cached is not None:
        return cached

    # Load from disk
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap

    # Scale down if needed
    if pixmap.width() > max_size or pixmap.height() > max_size:
        pixmap = pixmap.scaled(
            max_size, max_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

    # Store in cache
    cache.put(path, pixmap, max_size)
    return pixmap
