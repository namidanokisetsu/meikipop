import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QLocale, QSettings
from PyQt6.QtWidgets import QApplication
from meikipop.gui.lookup_audio import LookupAudio


class SentenceAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
