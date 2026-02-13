"""
Custom Tab - Combined tab with sub-tabs for Custom Icons, Borders, and Covers.
Sub-tabs are loaded lazily to avoid blocking the UI with PSD parsing.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QLabel
)


class _LazySubTab(QWidget):
    """Lightweight placeholder for a sub-tab that is constructed on first click."""

    def __init__(self, factory, parent=None):
        super().__init__(parent)
        self.factory = factory
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel("Loading...")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setObjectName("label_muted")
        layout.addWidget(lbl)


class CustomTab(QWidget):
    """Combined Custom tab with sub-tabs for Icons, Borders, and Covers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create sub-tab widget
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setTabPosition(QTabWidget.North)
        self.sub_tabs.setMovable(False)
        self.sub_tabs.setDocumentMode(True)

        # Sub-tabs use objectName for theme styling (see iisu_theme.qss)
        self.sub_tabs.setObjectName("custom_sub_tabs")

        # Only construct the first sub-tab eagerly; defer the rest
        from custom_image_tab import CustomImageTab
        self.custom_icons_tab = CustomImageTab()
        self.sub_tabs.addTab(self.custom_icons_tab, "Icons")

        # Borders and Covers are lazy — constructed on first click
        self._borders_placeholder = _LazySubTab(self._make_borders_tab)
        self._covers_placeholder = _LazySubTab(self._make_covers_tab)
        self.sub_tabs.addTab(self._borders_placeholder, "Borders")
        self.sub_tabs.addTab(self._covers_placeholder, "Covers")

        self.sub_tabs.currentChanged.connect(self._on_sub_tab_changed)
        layout.addWidget(self.sub_tabs)

    def _on_sub_tab_changed(self, index: int):
        """Replace a lazy placeholder with the real widget on first click."""
        widget = self.sub_tabs.widget(index)
        if isinstance(widget, _LazySubTab):
            label = self.sub_tabs.tabText(index)
            real = widget.factory()
            self.sub_tabs.removeTab(index)
            self.sub_tabs.insertTab(index, real, label)
            self.sub_tabs.setCurrentIndex(index)
            # Store reference so other code can reach it
            if label == "Borders":
                self.borders_tab = real
            elif label == "Covers":
                self.covers_tab = real

    @staticmethod
    def _make_borders_tab():
        from border_generator_tab import BorderGeneratorTab
        return BorderGeneratorTab()

    @staticmethod
    def _make_covers_tab():
        from cover_generator_tab import CoverGeneratorTab
        return CoverGeneratorTab()
