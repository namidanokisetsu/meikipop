import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

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

    def test_background_ocr_submits_audio_when_idle(self):
        self.shared.active = False
        self.service.handle_lookup_result(self._result(0, "一"))
        self.assertEqual([request.activation_id for request in self.spy.requests], [0])

    def test_background_ocr_does_not_restart_same_word(self):
        self.shared.active = False
        self.service.handle_lookup_result(self._result(0, "one"))
        self.service.handle_lookup_result(self._result(0, "one"))
        self.assertEqual(len(self.spy.requests), 1)
        self.service.handle_lookup_result(LookupResult(0, None, ()))
        self.service.handle_lookup_result(self._result(0, "one"))
        self.assertEqual(len(self.spy.requests), 2)

    def test_text_audio_uses_revision_and_rejects_dismissed_results(self):
        clipboard = SimpleNamespace(active=True, revision=7)
        self.shared.clipboard_lookup = clipboard
        entries = self._result(0, "one").entries
        self.service.handle_text_result(7, entries)
        self.assertEqual(self.spy.requests[-1].activation_id, -7)
        self.service.player = Mock()
        clip = AudioClip(-7, self.spy.requests[-1].key, "one.mp3", "x", b"fixture")
        clipboard.active = False
        self.service._play_clip(clip)
        self.service.player.play.assert_not_called()
        clipboard.active = True
        clipboard.revision = 8
        self.service._play_clip(clip)
        self.service.player.play.assert_not_called()
        self.service.handle_text_result(8, entries)
        clip = AudioClip(-8, self.spy.requests[-1].key, "one.mp3", "x", b"fixture")
        self.service._play_clip(clip)
        self.service.player.play.assert_called_once()

    def test_rapid_ocr_finishes_current_clip_then_plays_latest(self):
        self.service.player = Mock()
        for word in ("one", "two", "three"):
            self.service.handle_lookup_result(self._result(4, word))
            request = self.spy.requests[-1]
            self.service._play_clip(AudioClip(4, request.key, word + ".mp3", "x", b"fixture"))
        self.service.player.play.assert_called_once()
        self.service._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertEqual(self.service.player.play.call_count, 2)
        self.assertEqual(self.service.player.setSourceDevice.call_args.args[1].fileName(), "three.mp3")

    def test_queued_clip_is_discarded_after_new_activation(self):
        self.service.player = Mock()
        for word in ("one", "two"):
            self.service.handle_lookup_result(self._result(4, word))
            request = self.spy.requests[-1]
            self.service._play_clip(AudioClip(4, request.key, word + ".mp3", "x", b"fixture"))
        self.shared.activation_id = 5
        self.service._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        self.service.player.play.assert_called_once()

    def test_clip_can_play_after_activation_key_release(self):
        class PlayerSpy:
            def stop(self): pass
            def setSourceDevice(self, device, url):
                self.device, self.url = device, url
            def play(self): pass

        self.service.handle_lookup_result(self._result(4, "一"))
        self.shared.active = False
        self.service.player = PlayerSpy()
        clip = AudioClip(4, ("一", "よみ"), "one.mp3", "x", b"fixture bytes")
        self.service._play_clip(clip)
        self.assertIsNotNone(self.service._buffer)

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
