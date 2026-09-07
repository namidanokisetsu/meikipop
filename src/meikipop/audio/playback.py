"""GUI-thread Qt playback and autoplay coordination."""
from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from meikipop.audio.worker import AudioRequest, AudioWorker
from meikipop.config.config import config
from meikipop.pipeline import LookupResult

logger = logging.getLogger(__name__)


class PronunciationAudioService(QObject):
    clip_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)

    def __init__(self, shared_state, parent=None):
        super().__init__(parent)
        self.shared_state = shared_state
        self._media_devices = QMediaDevices(self)
        self.output = QAudioOutput(self)
        self._media_devices.audioOutputsChanged.connect(self._follow_system_audio_output)
        self._follow_system_audio_output()
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self._bytes = None
        self._buffer = None
        self._pending_clip = None
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

    def _follow_system_audio_output(self):
        """Route playback to the current system default output device."""
        device = self._media_devices.defaultAudioOutput()
        if self.output.device() != device:
            logger.info("Audio output changed to %s", device.description())
            self.output.setDevice(device)

    def _preferences(self):
        return tuple(item.strip() for item in config.audio_preferred_sources.split(",") if item.strip())

    def handle_lookup_result(self, result):
        if not config.audio_autoplay_enabled:
            return
        current_id, active = self.shared_state.activation_snapshot()
        clipboard = getattr(self.shared_state, "clipboard_lookup", None)
        if result.activation_id < 0:
            if not clipboard or not clipboard.active or clipboard.revision != -result.activation_id:
                return
        elif clipboard and clipboard.active:
            return
        elif result.activation_id and current_id != result.activation_id:
            return
        # A zero activation is the auto-scan OCR path. Do not let it interrupt
        # a manually held OCR activation, but allow it when the cursor is idle.
        if not result.activation_id and active:
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
            if self._latest_key == (result.activation_id, key):
                return
            self._latest_key = (result.activation_id, key)
            if result.activation_id:
                played = self._played.setdefault(result.activation_id, set())
                if key in played:
                    return
                played.add(key)
                self._played = {result.activation_id: played}
        self.worker.submit(AudioRequest(result.activation_id, key, config.audio_database_path, self._preferences()))

    def handle_text_result(self, revision, entries):
        # Negative IDs keep text revisions separate from OCR activations.
        self.handle_lookup_result(LookupResult(-revision, None, tuple(entries or ())))

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
        if not config.audio_autoplay_enabled or not is_latest:
            return
        clipboard = getattr(self.shared_state, "clipboard_lookup", None)
        if clip.activation_id < 0:
            if not clipboard or not clipboard.active or clipboard.revision != -clip.activation_id:
                return
        elif clipboard and clipboard.active:
            return
        elif clip.activation_id and clip.activation_id != current_id:
            return
        # Background OCR uses activation 0 and must not race a manual lookup.
        # Manual clips remain valid when the user releases the activation key
        # while the local audio worker is reading the database.
        if not clip.activation_id and active:
            return
        if self._buffer is not None:
            # Finish the current pronunciation; rapid OCR hits retain only the
            # latest next clip, revalidated when playback finishes.
            self._pending_clip = clip
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
            pending, self._pending_clip = self._pending_clip, None
            if pending is not None:
                self._play_clip(pending)

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
        self._pending_clip = None
        self.player.stop()
        self._release_buffer()
        self.worker.stop()
        self.worker.join(timeout=3)
