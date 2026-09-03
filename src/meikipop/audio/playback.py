"""GUI-thread Qt playback and autoplay coordination."""
from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from meikipop.audio.worker import AudioRequest, AudioWorker
from meikipop.config.config import config

logger = logging.getLogger(__name__)


class PronunciationAudioService(QObject):
    clip_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)

    def __init__(self, shared_state, parent=None):
        super().__init__(parent)
        self.shared_state = shared_state
        self.output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self._bytes = None
        self._buffer = None
        self._played: dict[int, set[tuple[str, str]]] = {}
        self._latest_key: tuple[int, tuple[str, str] | None] = (0, None)
        self._dedupe_lock = threading.Lock()
        self._last_playback_error = None
        self.last_status = "Audio autoplay disabled" if not config.audio_autoplay_enabled else "Audio database not checked"
        self.clip_ready.connect(self._play_clip)
        self.status_changed.connect(self._remember_status)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_error)
        self.worker = AudioWorker(self.clip_ready.emit, self.status_changed.emit)
        self.worker.start()
        self.apply_settings(validate=config.audio_autoplay_enabled)

    def _preferences(self):
        return tuple(item.strip() for item in config.audio_preferred_sources.split(",") if item.strip())

    def handle_lookup_result(self, result):
        if not config.audio_autoplay_enabled or not result.activation_id:
            return
        current_id, active = self.shared_state.activation_snapshot()
        if not active or current_id != result.activation_id:
            return
        if not result.entries:
            with self._dedupe_lock:
                self._latest_key = (result.activation_id, None)
            return
        top = result.entries[0]
        if not hasattr(top, "written_form"):
            with self._dedupe_lock:
                self._latest_key = (result.activation_id, None)
            return
        key = (top.written_form, top.reading or "")
        with self._dedupe_lock:
            self._latest_key = (result.activation_id, key)
            played = self._played.setdefault(result.activation_id, set())
            if key in played:
                return
            played.add(key)
            self._played = {result.activation_id: played}
        self.worker.submit(AudioRequest(result.activation_id, key, config.audio_database_path, self._preferences()))

    def apply_settings(self, validate=True):
        self.output.setVolume(max(0, min(100, config.audio_volume)) / 100.0)
        if validate and config.audio_database_path:
            current_id, _ = self.shared_state.activation_snapshot()
            self.worker.submit(AudioRequest(current_id, None, config.audio_database_path, self._preferences()))
        elif not config.audio_autoplay_enabled:
            self.status_changed.emit("Audio autoplay disabled")

    def validate(self, database_path: str, preferred_sources: str):
        preferences = tuple(item.strip() for item in preferred_sources.split(",") if item.strip())
        current_id, _ = self.shared_state.activation_snapshot()
        self.worker.submit(AudioRequest(current_id, None, database_path.strip(), preferences))

    def _play_clip(self, clip):
        current_id, active = self.shared_state.activation_snapshot()
        with self._dedupe_lock:
            is_latest = self._latest_key == (clip.activation_id, clip.key)
        if not config.audio_autoplay_enabled or not active or clip.activation_id != current_id or not is_latest:
            return
        self.player.stop()
        self._release_buffer()
        self._bytes = QByteArray(clip.data)
        self._buffer = QBuffer(self._bytes, self)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.player.setSourceDevice(self._buffer, QUrl(f"memory:///{clip.filename}"))
        self.player.play()

    def _on_media_status(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._last_playback_error = None
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            self._release_buffer()

    def _on_error(self, _error, error_string):
        if error_string != self._last_playback_error:
            logger.warning("Pronunciation playback failed: %s", error_string)
            self.status_changed.emit(f"Playback failed: {error_string}")
            self._last_playback_error = error_string
        self._release_buffer()

    def _release_buffer(self):
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
        self._buffer = None
        self._bytes = None

    def _remember_status(self, status):
        self.last_status = status

    def shutdown(self):
        self.player.stop()
        self._release_buffer()
        self.worker.stop()
        self.worker.join(timeout=3)
