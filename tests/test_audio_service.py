import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtMultimedia import QMediaPlayer

from meikipop.audio.playback import PronunciationAudioService
from meikipop.audio.repository import AudioClip
from meikipop.config.config import config
from meikipop.dictionary.lookup import DictionaryEntry
from meikipop.pipeline import LookupResult


class _SharedState:
    activation_id = 4
    active = True

    def activation_snapshot(self):
        return self.activation_id, self.active


class _WorkerSpy:
    def __init__(self):
        self.requests = []

    def submit(self, request):
        self.requests.append(request)

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


class AudioServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_values = (
            config.audio_autoplay_enabled,
            config.audio_database_path,
            config.audio_preferred_sources,
        )
        config.audio_autoplay_enabled = True
        config.audio_database_path = "fixture.db"
        config.audio_preferred_sources = "preferred"
        self.shared = _SharedState()
        self.service = PronunciationAudioService(self.shared)
        self.service.worker.stop()
        self.service.worker.join(2)
        self.spy = _WorkerSpy()
        self.service.worker = self.spy

    def tearDown(self):
        self.service.shutdown()
        (config.audio_autoplay_enabled, config.audio_database_path,
         config.audio_preferred_sources) = self.old_values

    @staticmethod
    def _result(activation_id, word):
        entry = DictionaryEntry(1, word, "よみ", [], 1, ())
        return LookupResult(activation_id, word, (entry,))

    def test_once_per_key_per_activation_and_replay_next_activation(self):
        self.service.handle_lookup_result(self._result(4, "一"))
        self.service.handle_lookup_result(self._result(4, "一"))
        self.service.handle_lookup_result(self._result(4, "二"))
        self.assertEqual([request.key for request in self.spy.requests], [("一", "よみ"), ("二", "よみ")])

        self.shared.activation_id = 5
        self.service.handle_lookup_result(self._result(5, "一"))
        self.assertEqual(self.spy.requests[-1].activation_id, 5)

    def test_old_activation_and_non_latest_clip_are_discarded(self):
        self.service.handle_lookup_result(self._result(4, "一"))
        self.service.handle_lookup_result(self._result(4, "二"))
        stale_key = AudioClip(4, ("一", "よみ"), "one.mp3", "x", b"not audio")
        self.service._play_clip(stale_key)
        self.assertIsNone(self.service._buffer)

        self.shared.activation_id = 5
        old_activation = AudioClip(4, ("二", "よみ"), "two.mp3", "x", b"not audio")
        self.service._play_clip(old_activation)
        self.assertIsNone(self.service._buffer)

    def test_current_clip_buffer_is_retained_until_end_of_media(self):
        class PlayerSpy:
            def stop(self): pass
            def setSourceDevice(self, device, url):
                self.device, self.url = device, url
            def play(self): pass

        self.service.handle_lookup_result(self._result(4, "一"))
        self.service.player = PlayerSpy()
        clip = AudioClip(4, ("一", "よみ"), "one.mp3", "x", b"fixture bytes")
        self.service._play_clip(clip)
        self.assertIsNotNone(self.service._buffer)
        self.assertTrue(self.service._buffer.isOpen())
        self.service._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertIsNone(self.service._buffer)

    def test_audio_output_follows_new_system_default(self):
        class Device:
            def description(self):
                return "Bluetooth headphones"

        class MediaDevicesSpy:
            def defaultAudioOutput(self):
                return device

        class OutputSpy:
            current_device = object()

            def device(self):
                return self.current_device

            def setDevice(self, new_device):
                self.current_device = new_device

        device = Device()
        output = OutputSpy()
        self.service._media_devices = MediaDevicesSpy()
        self.service.output = output

        self.service._follow_system_audio_output()

        self.assertIs(output.current_device, device)


if __name__ == "__main__":
    unittest.main()
