"""
Game Search Dialog for Desktop
Similar to Android's GameSearchDialog - lets users search SteamGridDB and pick the correct game
before fetching artwork.
"""
import requests
from typing import List, Dict, Any, Optional, Callable
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
    QWidget, QSizePolicy
)

from api_key_manager import get_manager


class SearchWorker(QThread):
    """Worker thread for searching SteamGridDB."""
    finished = Signal(list)  # List of game results
    error = Signal(str)  # Error message

    def __init__(self, query: str, api_key: str):
        super().__init__()
        self.query = query
        self.api_key = api_key

    def run(self):
        try:
            results = search_steamgriddb_games(self.query, self.api_key)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


def search_steamgriddb_games(query: str, api_key: str, timeout: int = 15) -> List[Dict[str, Any]]:
    """
    Search SteamGridDB for games matching the query.
    Returns list of game dicts with id, name, release_date, types.
    """
    if not api_key:
        return []

    try:
        encoded_query = requests.utils.quote(query)
        url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{encoded_query}"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "iiSU-Asset-Tool/1.0"
        }

        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        if not data.get("success", False):
            return []

        results = []
        for game in data.get("data", []):
            game_id = game.get("id")
            name = game.get("name", "Unknown")
            release_date = game.get("release_date", 0)
            types = game.get("types", [])

            # Parse release year from Unix timestamp
            release_year = None
            if release_date and release_date > 0:
                try:
                    import datetime
                    dt = datetime.datetime.fromtimestamp(release_date)
                    release_year = dt.year
                except:
                    pass

            results.append({
                "id": game_id,
                "name": name,
                "release_year": release_year,
                "types": types
            })

        return results

    except Exception as e:
        print(f"SteamGridDB search error: {e}")
        return []


class GameSearchDialog(QDialog):
    """
    Dialog for searching and selecting a game from SteamGridDB.
    Similar to Android's GameSearchDialog.
    """

    def __init__(self, parent=None, initial_query: str = "", title: str = "Search Game"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)

        self.selected_game: Optional[Dict[str, Any]] = None
        self.search_worker: Optional[SearchWorker] = None
        self.api_key = get_manager().get_key("steamgriddb") or ""

        self._setup_ui()

        # Pre-fill search if provided
        if initial_query:
            self.search_input.setText(initial_query)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header_label = QLabel("Search for the correct game to get accurate artwork")
        header_label.setObjectName("label_muted")
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        # Search input row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter game name...")
        self.search_input.setMinimumHeight(36)
        self.search_input.returnPressed.connect(self._perform_search)
        search_row.addWidget(self.search_input, 1)

        self.search_btn = QPushButton("Search")
        self.search_btn.setMinimumWidth(80)
        self.search_btn.setMinimumHeight(36)
        self.search_btn.clicked.connect(self._perform_search)
        search_row.addWidget(self.search_btn)

        layout.addLayout(search_row)

        # Progress bar (hidden by default)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(4)
        layout.addWidget(self.progress)

        # Results label
        self.results_label = QLabel("Search Results:")
        self.results_label.setObjectName("label_accent")
        self.results_label.setVisible(False)
        layout.addWidget(self.results_label)

        # Results list
        self.results_list = QListWidget()
        self.results_list.setMinimumHeight(200)
        self.results_list.itemClicked.connect(self._on_item_clicked)
        self.results_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.results_list.setVisible(False)
        layout.addWidget(self.results_list, 1)

        # No results label
        self.no_results_label = QLabel("No games found. Try a different search term.")
        self.no_results_label.setObjectName("label_muted")
        self.no_results_label.setAlignment(Qt.AlignCenter)
        self.no_results_label.setVisible(False)
        layout.addWidget(self.no_results_label)

        # Spacer (when no results shown)
        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.spacer)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_btn)

        self.select_btn = QPushButton("Select Game")
        self.select_btn.setEnabled(False)
        self.select_btn.setObjectName("btn_start")  # Use accent styling
        self.select_btn.clicked.connect(self._on_select)
        button_row.addWidget(self.select_btn)

        layout.addLayout(button_row)

    def _perform_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        if not self.api_key:
            self.no_results_label.setText("SteamGridDB API key not configured. Please add it in Settings.")
            self.no_results_label.setVisible(True)
            self.results_list.setVisible(False)
            self.results_label.setVisible(False)
            return

        # Show loading state
        self.progress.setVisible(True)
        self.search_btn.setEnabled(False)
        self.results_list.setVisible(False)
        self.results_label.setVisible(False)
        self.no_results_label.setVisible(False)
        self.spacer.setVisible(True)
        self.select_btn.setEnabled(False)
        self.selected_game = None

        # Start search in background
        self.search_worker = SearchWorker(query, self.api_key)
        self.search_worker.finished.connect(self._on_search_finished)
        self.search_worker.error.connect(self._on_search_error)
        self.search_worker.start()

    def _on_search_finished(self, results: List[Dict[str, Any]]):
        self.progress.setVisible(False)
        self.search_btn.setEnabled(True)

        self.results_list.clear()

        if results:
            self.results_label.setText(f"Search Results ({len(results)}):")
            self.results_label.setVisible(True)
            self.results_list.setVisible(True)
            self.no_results_label.setVisible(False)
            self.spacer.setVisible(False)

            for game in results:
                item = QListWidgetItem()

                # Build display text
                name = game.get("name", "Unknown")
                year = game.get("release_year")
                types = game.get("types", [])

                display_text = name
                if year:
                    display_text += f"  ({year})"
                if types:
                    display_text += f"  [{', '.join(types)}]"

                item.setText(display_text)
                item.setData(Qt.UserRole, game)
                self.results_list.addItem(item)
        else:
            self.results_label.setVisible(False)
            self.results_list.setVisible(False)
            self.no_results_label.setText("No games found. Try a different search term.")
            self.no_results_label.setVisible(True)
            self.spacer.setVisible(True)

    def _on_search_error(self, error_msg: str):
        self.progress.setVisible(False)
        self.search_btn.setEnabled(True)
        self.results_label.setVisible(False)
        self.results_list.setVisible(False)
        self.no_results_label.setText(f"Search failed: {error_msg}")
        self.no_results_label.setVisible(True)
        self.spacer.setVisible(True)

    def _on_item_clicked(self, item: QListWidgetItem):
        self.selected_game = item.data(Qt.UserRole)
        self.select_btn.setEnabled(True)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        self.selected_game = item.data(Qt.UserRole)
        self._on_select()

    def _on_select(self):
        if self.selected_game:
            self.accept()

    def get_selected_game(self) -> Optional[Dict[str, Any]]:
        """Returns the selected game dict or None if cancelled."""
        return self.selected_game

    @staticmethod
    def search_and_select(parent=None, initial_query: str = "", title: str = "Search Game") -> Optional[Dict[str, Any]]:
        """
        Static method to show the dialog and return the selected game.
        Returns None if cancelled.
        """
        dialog = GameSearchDialog(parent, initial_query, title)
        if dialog.exec() == QDialog.Accepted:
            return dialog.get_selected_game()
        return None
