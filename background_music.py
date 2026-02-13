"""
Background Music Manager for iiSU Asset Tool Desktop

Plays the iiSU OST (audio.mp3 or audio.wav) when enabled in settings.
Music by Thaddeus Silva.
"""
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl, QObject
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from app_paths import get_app_dir, get_config_path, get_config, invalidate_config_cache


class BackgroundMusicManager(QObject):
    """Singleton manager for background music playback."""

    _instance: Optional['BackgroundMusicManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        super().__init__()
        self._initialized = True

        self._player: Optional[QMediaPlayer] = None
        self._audio_output: Optional[QAudioOutput] = None
        self._is_playing = False
        self._volume = 50  # Default 50%

    def _find_audio_file(self) -> Optional[Path]:
        """Find the audio file (audio.mp3 or audio.wav) in the app directory."""
        app_dir = get_app_dir()

        # Try mp3 first, then wav
        for ext in ['mp3', 'wav']:
            audio_path = app_dir / f"audio.{ext}"
            if audio_path.exists():
                return audio_path

        return None

    def _load_settings(self) -> dict:
        """Load music settings from config."""
        try:
            cfg = get_config()
            return cfg.get("background_music", {})
        except Exception as e:
            print(f"Error loading music settings: {e}")
        return {}

    def _save_settings(self, enabled: bool, volume: int):
        """Save music settings to config."""
        try:
            import yaml
            cfg_path = Path(get_config_path())
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                cfg["background_music"] = {
                    "enabled": enabled,
                    "volume": volume
                }
                with open(cfg_path, "w", encoding="utf-8") as f:
                    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
                invalidate_config_cache()
        except Exception as e:
            print(f"Error saving music settings: {e}")

    def initialize(self):
        """Initialize and start background music if enabled in settings."""
        settings = self._load_settings()
        enabled = settings.get("enabled", True)  # Default enabled
        self._volume = settings.get("volume", 50)

        if not enabled:
            print("Background music disabled in settings")
            return

        audio_path = self._find_audio_file()
        if not audio_path:
            print("No audio file found (audio.mp3 or audio.wav) - background music disabled")
            return

        try:
            # Create audio output
            self._audio_output = QAudioOutput()
            self._audio_output.setVolume(self._volume / 100.0)

            # Create media player
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio_output)
            self._player.setSource(QUrl.fromLocalFile(str(audio_path)))

            # Loop playback
            self._player.mediaStatusChanged.connect(self._on_media_status_changed)

            # Start playing
            self._player.play()
            self._is_playing = True
            print(f"Background music started: {audio_path.name}")

        except Exception as e:
            print(f"Error initializing background music: {e}")
            self.release()

    def _on_media_status_changed(self, status):
        """Handle media status changes for looping."""
        if status == QMediaPlayer.EndOfMedia:
            # Loop the music
            self._player.setPosition(0)
            self._player.play()

    def set_volume(self, volume: int):
        """Set volume as a percentage (0-100)."""
        self._volume = max(0, min(100, volume))
        if self._audio_output:
            self._audio_output.setVolume(self._volume / 100.0)
        print(f"Volume set to {self._volume}%")

    def get_volume(self) -> int:
        """Get current volume (0-100)."""
        return self._volume

    def is_enabled(self) -> bool:
        """Check if music is enabled in settings."""
        settings = self._load_settings()
        return settings.get("enabled", True)

    def set_enabled(self, enabled: bool):
        """Enable or disable music and save setting."""
        self._save_settings(enabled, self._volume)
        if enabled:
            if not self._is_playing:
                self.initialize()
        else:
            self.stop()

    def save_volume(self):
        """Save current volume to config."""
        settings = self._load_settings()
        enabled = settings.get("enabled", True)
        self._save_settings(enabled, self._volume)

    def pause(self):
        """Pause playback."""
        if self._player and self._is_playing:
            self._player.pause()
            print("Background music paused")

    def resume(self):
        """Resume playback."""
        if self._player and self._is_playing:
            self._player.play()
            print("Background music resumed")

    def stop(self):
        """Stop playback."""
        if self._player:
            self._player.stop()
            self._is_playing = False
            print("Background music stopped")

    def release(self):
        """Release all resources."""
        if self._player:
            self._player.stop()
            self._player = None
        if self._audio_output:
            self._audio_output = None
        self._is_playing = False
        print("Background music released")

    def toggle(self):
        """Toggle music on/off."""
        if self._is_playing:
            self.stop()
            self.set_enabled(False)
        else:
            self.set_enabled(True)

    def is_playing(self) -> bool:
        """Check if music is currently playing."""
        return self._is_playing


# Singleton accessor
_manager: Optional[BackgroundMusicManager] = None


def get_music_manager() -> BackgroundMusicManager:
    """Get the singleton background music manager."""
    global _manager
    if _manager is None:
        _manager = BackgroundMusicManager()
    return _manager
