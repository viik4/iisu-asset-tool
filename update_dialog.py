"""
Update Dialog for iiSU Asset Tool (Desktop)
Shows update availability, changelog, and handles download with progress.
"""
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextBrowser, QDialogButtonBox, QMessageBox,
)

from updater import (
    UpdateInfo, download_update, apply_update, launch_swap_and_exit,
    format_size, check_for_updates,
)
from app_paths import get_app_dir, get_config_path


class _DownloadSignals(QObject):
    """Thread-safe signals for download progress."""
    progress = Signal(int, int)      # (downloaded_bytes, total_bytes)
    complete = Signal(str)           # path to downloaded file
    error = Signal(str)              # error message


class UpdateDialog(QDialog):
    """Dialog for showing update info and handling download."""

    def __init__(self, update_info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self._download_path = None
        self._downloading = False
        self._signals = _DownloadSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.complete.connect(self._on_complete)
        self._signals.error.connect(self._on_error)
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Update Available")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)

        # Size relative to parent
        if self.parent():
            parent_size = self.parent().size()
            self.resize(
                min(int(parent_size.width() * 0.5), 600),
                min(int(parent_size.height() * 0.65), 500),
            )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Version header ---
        version_label = QLabel(
            f"<b style='font-size: 16px; color: #00D4FF;'>v{self.update_info.latest_version}</b>"
            f"  <span style='color: #888;'>is available</span>"
        )
        layout.addWidget(version_label)

        current_label = QLabel(
            f"<span style='color: #888;'>You have v{self.update_info.current_version}</span>"
        )
        layout.addWidget(current_label)

        # --- Changelog ---
        changelog_header = QLabel("<b>What's New:</b>")
        layout.addWidget(changelog_header)

        self._changelog = QTextBrowser()
        self._changelog.setOpenExternalLinks(True)
        changelog_text = self.update_info.changelog or "No changelog provided."
        # Convert markdown-style bullet points to HTML
        html_lines = []
        for line in changelog_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                html_lines.append(f"&bull; {stripped[2:]}<br>")
            elif stripped.startswith("## "):
                html_lines.append(f"<b>{stripped[3:]}</b><br>")
            elif stripped.startswith("# "):
                html_lines.append(f"<b>{stripped[2:]}</b><br>")
            elif stripped:
                html_lines.append(f"{stripped}<br>")
            else:
                html_lines.append("<br>")
        self._changelog.setHtml("".join(html_lines))
        layout.addWidget(self._changelog, 1)

        # --- Download size ---
        if self.update_info.download_size > 0:
            size_label = QLabel(
                f"<span style='color: #888;'>Download size: "
                f"{format_size(self.update_info.download_size)}</span>"
            )
            layout.addWidget(size_label)

        # --- Progress bar (hidden initially) ---
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setMinimumHeight(22)
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("label_muted")
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        # --- Buttons ---
        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self._btn_github = QPushButton("View on GitHub")
        self._btn_github.setMinimumHeight(36)
        self._btn_github.clicked.connect(self._open_github)
        button_row.addWidget(self._btn_github)

        button_row.addStretch()

        self._btn_later = QPushButton("Later")
        self._btn_later.setMinimumHeight(36)
        self._btn_later.clicked.connect(self.reject)
        button_row.addWidget(self._btn_later)

        self._btn_update = QPushButton("Update Now")
        self._btn_update.setMinimumHeight(36)
        self._btn_update.setObjectName("btn_accent")
        self._btn_update.clicked.connect(self._start_download)
        button_row.addWidget(self._btn_update)

        # Restart button (hidden initially)
        self._btn_restart = QPushButton("Restart Now")
        self._btn_restart.setMinimumHeight(36)
        self._btn_restart.setObjectName("btn_accent")
        self._btn_restart.clicked.connect(self._restart_app)
        self._btn_restart.setVisible(False)
        button_row.addWidget(self._btn_restart)

        layout.addLayout(button_row)

    def _open_github(self):
        if self.update_info.release_url:
            QDesktopServices.openUrl(QUrl(self.update_info.release_url))

    def _start_download(self):
        if self._downloading:
            return

        if not self.update_info.download_url:
            # No downloadable asset for this platform — open GitHub instead
            QMessageBox.information(
                self, "No Direct Download",
                f"No downloadable update found for {sys.platform}.\n"
                "Opening the release page instead."
            )
            self._open_github()
            return

        self._downloading = True
        self._btn_update.setEnabled(False)
        self._btn_update.setText("Downloading...")
        self._btn_later.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_label.setVisible(True)

        signals = self._signals
        update_info = self.update_info

        def _download():
            try:
                staging = get_app_dir() / "_update_staging"
                result = download_update(
                    update_info, staging,
                    progress_callback=lambda done, total: signals.progress.emit(done, total),
                )
                if result:
                    signals.complete.emit(str(result))
                else:
                    signals.error.emit("Download failed. Please try again or download manually.")
            except Exception as e:
                signals.error.emit(str(e))

        thread = threading.Thread(target=_download, daemon=True)
        thread.start()

    def _on_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = min(int(downloaded * 100 / total), 100)
            self._progress_bar.setValue(pct)
            self._progress_label.setText(
                f"{format_size(downloaded)} / {format_size(total)} ({pct}%)"
            )

    def _on_complete(self, path: str):
        self._download_path = Path(path)
        self._progress_bar.setValue(100)
        self._progress_label.setText("Download complete!")
        self._btn_update.setVisible(False)

        if sys.platform == "darwin":
            # macOS: open the DMG
            self._progress_label.setText("Opening DMG...")
            apply_update(self._download_path, get_app_dir())
            self._btn_later.setText("Close")
            self._btn_later.setEnabled(True)
        else:
            # Windows / Linux: prepare swap
            app_dir = get_app_dir()
            success = apply_update(self._download_path, app_dir)
            if success:
                self._progress_label.setText("Ready to install. Restart to apply the update.")
                self._btn_restart.setVisible(True)
                self._btn_later.setText("Later")
                self._btn_later.setEnabled(True)
            else:
                self._progress_label.setText("Failed to prepare update. Please download manually.")
                self._btn_later.setText("Close")
                self._btn_later.setEnabled(True)
                self._btn_github.setVisible(True)

    def _on_error(self, message: str):
        self._downloading = False
        self._progress_bar.setVisible(False)
        self._progress_label.setText(f"Error: {message}")
        self._progress_label.setVisible(True)
        self._btn_update.setEnabled(True)
        self._btn_update.setText("Retry")
        self._btn_later.setEnabled(True)

    def _restart_app(self):
        reply = QMessageBox.question(
            self, "Restart",
            "The app will close and restart with the new version.\n"
            "Any unsaved work will be lost. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            launch_swap_and_exit(get_app_dir())


class UpToDateDialog(QDialog):
    """Simple dialog shown when no update is available."""

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Up to Date")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        icon_label = QLabel(
            "<span style='font-size: 32px;'>&#10004;</span>"
        )
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        msg = QLabel(
            f"<b>You're up to date!</b><br><br>"
            f"iiSU Asset Tool v{current_version} is the latest version."
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)


def show_update_check(current_version: str, parent=None, silent: bool = True):
    """
    Perform an update check and show the appropriate dialog.
    If silent=True (startup check), only shows dialog when update is available.
    If silent=False (manual check), shows "up to date" dialog too.
    """
    info = check_for_updates(current_version)

    if info and info.is_update_available:
        dialog = UpdateDialog(info, parent=parent)
        dialog.exec()
    elif not silent:
        if info:
            dialog = UpToDateDialog(current_version, parent=parent)
            dialog.exec()
        else:
            QMessageBox.warning(
                parent, "Update Check Failed",
                "Could not check for updates.\nPlease check your internet connection."
            )
