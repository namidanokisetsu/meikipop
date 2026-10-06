import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QLocale, QSettings
from PyQt6.QtWidgets import QApplication
from meikipop.gui.lookup_audio import LookupAudio
from meikipop.dictionary.library import Entry


class SentenceAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_saved_priority_overrides_legacy_mode_and_can_disable_sources(self):
        from meikipop.audio.sources import source_order
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/tr/audio_mode", "online")
            settings.setValue("profiles/tr/audio_priority", ["tts", "online"])
            audio = LookupAudio()
            word = Entry("ev", "ev", "", "Fixture", "tr", ("house",))
            try:
                with patch.object(audio, "_speak", return_value=True) as speak:
                    audio.play(word, 1, settings)
                    speak.assert_called_once_with("ev", "tr", 80)
                    audio.worker.submit.assert_not_called()
                    audio._speech_failed(None, "Voice failed")
                    self.app.processEvents()
                    self.assertTrue(audio.worker.submit.call_args.args[0].online)
                    audio.worker.submit.reset_mock()
                with patch.object(audio, "_speak", return_value=False):
                    audio.play(word, 2, settings)
                    self.assertTrue(audio.worker.submit.call_args.args[0].online)
                settings.setValue("profiles/tr/audio_priority", [])
                self.assertEqual(source_order(settings, "tr"), [])
                self.assertEqual(source_order(settings, "ru"), ["tts", "online"])
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_sentence_bypasses_word_database_and_invalidates_pending_word_clip(self):
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/audio_database", "words.db")
            settings.setValue("profiles/ja/audio_volume", 35)
            audio = LookupAudio()
            audio.speech = Mock()
            voice = Mock()
            voice.locale.return_value = QLocale("ja")
            audio.speech.availableVoices.return_value = [voice]
            try:
                audio.latest = (3, ("猫", "ねこ"))
                audio.play_text("猫がいる。", "ja", 3, settings, profile="ja")
                audio.worker.submit.assert_not_called()
                audio.speech.say.assert_called_once_with("猫がいる。")
                audio.speech.setLocale.assert_called_once_with(QLocale("ja"))
                audio.speech.setVolume.assert_called_once_with(.35)
                self.assertNotEqual(audio.latest, (3, ("猫", "ねこ")))
                with patch.object(audio.player, "play") as play:
                    audio._play_clip(Mock(activation_id=3, key=("猫", "ねこ")))
                    play.assert_not_called()
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_turkish_recordings_follow_priority_and_missing_sources_fall_back_to_tts(self):
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/tr/audio_database", "turkish.db")
            settings.setValue("profiles/tr/audio_order", ["db:recorded", "tts"])
            audio = LookupAudio()
            word = Entry("ev", "ev", "", "Turkdict", "tr", ("house",))
            try:
                with patch.object(audio, "_speak", return_value=True) as speak:
                    audio.play(word, 3, settings)
                    request = audio.worker.submit.call_args.args[0]
                    self.assertEqual(request.database_path, "turkish.db")
                    self.assertEqual(request.preferred_sources, ("recorded",))
                    self.assertTrue(request.strict_sources)
                    speak.assert_not_called()
                    audio._audio_result(request, None)
                    speak.assert_called_once()
                    settings.setValue("profiles/tr/audio_order", ["tts", "db:recorded"])
                    audio.worker.submit.reset_mock()
                    audio.play(word, 4, settings)
                    audio.worker.submit.assert_not_called()
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_source_override_ignores_late_results_even_for_same_revision(self):
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/audio_database", "japanese.db")
            audio = LookupAudio()
            word = Entry("cat", "猫", "ねこ", "Dictionary", "ja", ("cat",))
            try:
                audio.play(word, 1, settings, source="db:first")
                old = audio.worker.submit.call_args.args[0]
                audio.play(word, 1, settings, source="db:second")
                current = audio.worker.submit.call_args.args[0]
                with patch.object(audio, "_play_clip") as play:
                    audio._audio_result(old, Mock())
                    play.assert_not_called()
                    clip = Mock()
                    audio._audio_result(current, clip)
                    play.assert_called_once_with(clip)
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_online_defaults_to_entry_language_and_falls_back_to_system_voice(self):
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ru/audio_priority", ["online", "tts"])
            audio = LookupAudio()
            word = Entry("hello", "привет", "приве\u0301т", "Fixture", "ru", ("hello",))
            try:
                with patch.object(audio, "_speak", return_value=True) as speak:
                    audio.play(word, 1, settings)
                    request = audio.worker.submit.call_args.args[0]
                    self.assertTrue(request.online)
                    self.assertEqual((request.language, request.iso3), ("ru", "rus"))
                    audio._audio_result(request, None)
                    speak.assert_called_once_with("приве\u0301т", "ru", 80)
                    settings.setValue("profiles/ru/audio_mode", "tts")
                    settings.remove("profiles/ru/audio_priority")
                    audio.worker.submit.reset_mock()
                    audio.play(word, 2, settings)
                    audio.worker.submit.assert_not_called()
                    audio.cancel()
                    audio.worker.cancel.assert_called()
            finally:
                audio.shutdown()
                audio.deleteLater()
