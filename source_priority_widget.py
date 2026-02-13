"""
Draggable list widget for artwork source prioritization
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QLabel, QPushButton
)


class SourceListWidget(QListWidget):
    """Custom QListWidget with drag-and-drop reordering."""

    orderChanged = Signal(list)  # Emits new order when changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setMinimumHeight(150)
        self.setMaximumHeight(250)

        # Connect to detect order changes
        self.model().rowsMoved.connect(self._on_rows_moved)

    def _on_rows_moved(self):
        """Emit order changed signal when items are reordered."""
        order = self.get_source_order()
        self.orderChanged.emit(order)

    def get_source_order(self):
        """Get current order of sources with enabled state."""
        sources = []
        for i in range(self.count()):
            item = self.item(i)
            sources.append({
                "id": item.data(Qt.UserRole),
                "enabled": item.checkState() == Qt.Checked
            })
        return sources

    def set_source_order(self, sources):
        """Set source order from config."""
        self.clear()
        for src in sources:
            self.add_source_item(
                src.get("id"),
                src.get("display_name", src.get("id")),
                src.get("enabled", False)
            )

    def add_source_item(self, source_id, display_name, enabled=True):
        """Add a source item with checkbox."""
        item = QListWidgetItem(display_name)
        item.setData(Qt.UserRole, source_id)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
        item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        self.addItem(item)


class SourcePriorityWidget(QWidget):
    """
    Widget for managing artwork source priority with drag-and-drop.
    Replaces the simple dropdown with a reorderable list.
    """

    orderChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QLabel("Artwork Source Priority (drag to reorder):")
        layout.addWidget(header)

        # Source list
        self.source_list = SourceListWidget()
        self.source_list.orderChanged.connect(self.orderChanged.emit)
        self.source_list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.source_list)

        # Quick action buttons
        btn_layout = QHBoxLayout()

        self.btn_enable_all = QPushButton("Enable All")
        self.btn_enable_all.clicked.connect(self._enable_all)
        btn_layout.addWidget(self.btn_enable_all)

        self.btn_disable_all = QPushButton("Disable All")
        self.btn_disable_all.clicked.connect(self._disable_all)
        btn_layout.addWidget(self.btn_disable_all)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Help text
        help_text = QLabel(
            "✓ Checked sources are tried in order from top to bottom.\n"
            "Drag items to reorder. Click 'Save Config' to persist changes."
        )
        help_text.setWordWrap(True)
        help_text.setObjectName("label_muted")
        layout.addWidget(help_text)

    def _on_item_changed(self, item):
        """Emit signal when checkbox state changes."""
        self.orderChanged.emit(self.source_list.get_source_order())

    def _enable_all(self):
        for i in range(self.source_list.count()):
            self.source_list.item(i).setCheckState(Qt.Checked)
        self.orderChanged.emit(self.source_list.get_source_order())

    def _disable_all(self):
        for i in range(self.source_list.count()):
            self.source_list.item(i).setCheckState(Qt.Unchecked)
        self.orderChanged.emit(self.source_list.get_source_order())

    def get_source_order(self):
        """Get current source order configuration."""
        return self.source_list.get_source_order()

    def set_source_order(self, sources):
        """Set source order from configuration."""
        self.source_list.set_source_order(sources)
