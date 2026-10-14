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

    def test_unknown_locale_cannot_use_a_fallback_system_voice(self):
        with patch("meikipop.gui.lookup_audio.AudioWorker"):
            audio = LookupAudio()
            audio.speech = Mock()
            voice = Mock()
            voice.locale.return_value = QLocale.c()
            audio.speech.availableVoices.return_value = [voice]
            try:
                self.assertFalse(audio._speak("hello", "gem-pro", 80))
                audio.speech.say.assert_not_called()
                self.assertIn("gem-pro", audio._speech_error)
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_historical_locale_never_falls_back_to_english(self):
        from meikipop.gui.lookup_audio import speech_locale
        for language in ("egy", "got", "grc", "non", "sga", "gem-pro"):
            with self.subTest(language=language):
                self.assertIsNone(speech_locale(language))

    def test_historical_online_recordings_cannot_use_english_locale_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/egy/audio_priority", ["online"])
            audio = LookupAudio()
            try:
                audio.play(Entry("word", "word", "", "Fixture", "egy", ("word",)), 1, settings)
                request = audio.worker.submit.call_args.args[0]
                self.assertEqual(request.language, "egy")
                self.assertNotEqual(request.iso3, "eng")
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_supported_alias_uses_matching_installed_voice(self):
        with patch("meikipop.gui.lookup_audio.AudioWorker"):
            audio = LookupAudio()
            audio.speech = Mock()
            voice = Mock()
            voice.locale.return_value = QLocale("zh")
            audio.speech.availableVoices.return_value = [voice]
            try:
                self.assertTrue(audio._speak("中文", "cmn", 80))
                audio.speech.setLocale.assert_called_once_with(QLocale("zh"))
                audio.speech.say.assert_called_once_with("中文")
                voice.locale.return_value = QLocale("en")
                self.assertFalse(audio._speak("ייִדיש", "yi", 80))
                self.assertEqual(audio.speech.say.call_count, 1)
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_arabic_and_traditional_chinese_require_matching_installed_voices(self):
        with patch("meikipop.gui.lookup_audio.AudioWorker"):
            audio = LookupAudio()
            audio.speech = Mock()
            voice = Mock()
            audio.speech.availableVoices.return_value = [voice]
            try:
                for language, native in (("ar", "ar"), ("zh-hant", "zh_TW"), ("zh-hk", "zh_HK")):
                    with self.subTest(language=language):
                        voice.locale.return_value = QLocale(native)
                        self.assertTrue(audio._speak("word", language, 80))
                        self.assertEqual(audio.speech.setLocale.call_args.args[0], QLocale(native))
                voice.locale.return_value = QLocale("en")
                self.assertFalse(audio._speak("word", "ar", 80))
            finally:
                audio.shutdown()
                audio.deleteLater()

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
            settings.setValue("profiles/tr/audio_priority", ["db:recorded", "tts"])
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
                    settings.setValue("profiles/tr/audio_priority", ["tts", "db:recorded"])
                    audio.worker.submit.reset_mock()
                    audio.play(word, 4, settings)
                    audio.worker.submit.assert_not_called()
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_database_failure_does_not_report_error_before_next_source_succeeds(self):
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker") as worker:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/audio_database", "missing.db")
            settings.setValue("profiles/ja/audio_priority", ["db:first", "tts"])
            audio = LookupAudio()
            failed = Mock()
            audio.failed.connect(failed)
            try:
                with patch.object(audio, "_speak", return_value=True) as speak:
                    audio.play(Entry("cat", "猫", "ねこ", "Words", "ja", ("cat",)), 1, settings)
                    request = audio.worker.submit.call_args.args[0]
                    worker.call_args.args[1]("Audio database unavailable")
                    audio._audio_result(request, None)
                    speak.assert_called_once()
                    failed.assert_not_called()
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

    def test_cross_language_entry_uses_active_profile_source_preferences(self):
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/tr/audio_priority", ["db:english"])
            settings.setValue("profiles/tr/audio_database", "turkish-library.db")
            audio = LookupAudio()
            try:
                audio.play(Entry("house", "house", "", "EN-TR", "en", ("ev",)), 1, settings, profile="tr")
                request = audio.worker.submit.call_args.args[0]
                self.assertEqual(request.database_path, "turkish-library.db")
                self.assertEqual(request.preferred_sources, ("english",))
                settings.setValue("profiles/tr/audio_priority", [])
                audio.worker.submit.reset_mock()
                audio.play(Entry("house", "house", "", "EN-TR", "en", ("ev",)), 2, settings, profile="tr")
                audio.worker.submit.assert_not_called()
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_completed_clip_keeps_export_audio_and_releases_playback_buffer(self):
        from meikipop.audio.repository import AudioClip
        from PyQt6.QtMultimedia import QMediaPlayer
        with patch("meikipop.gui.lookup_audio.AudioWorker"):
            audio = LookupAudio()
            audio.player = Mock()
            audio.latest = (1, ("猫", "ねこ"))
            clip = AudioClip(1, audio.latest[1], "cat.wav", "Fixture", b"RIFFfixture")
            try:
                audio._play_clip(clip)
                self.assertIsNotNone(audio.buffer)
                audio._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
                self.assertIsNone(audio.buffer)
                self.assertIs(audio.current_clip, clip)
                audio._play_clip(clip)
                audio.cancel()
                self.assertIsNone(audio.buffer)
                self.assertIsNone(audio.current_clip)
                audio.player.setSource.assert_called_once()
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_shared_audio_follows_system_output(self):
        with patch("meikipop.gui.lookup_audio.AudioWorker"):
            audio = LookupAudio()
            try:
                output, device = Mock(), object()
                audio.output = output
                audio._media_devices = Mock()
                audio._media_devices.defaultAudioOutput.return_value = device
                audio._follow_system_audio_output()
                output.setDevice.assert_called_once_with(device)
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_source_menu_uses_active_profile_for_cross_language_entries(self):
        from types import SimpleNamespace
        from meikipop.gui.quick_lookup import QuickLookupWindow
        with tempfile.TemporaryDirectory() as folder, patch("meikipop.gui.quick_lookup.QMenu") as menu_type:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/tr/audio_priority", ["db:Turkish recordings", "online"])
            settings.setValue("profiles/tr/audio_database", "turkish.db")
            window = SimpleNamespace(_result=SimpleNamespace(entries=[SimpleNamespace(language="en")]),
                                     preferred_foreign="tr", settings=settings, audio_button=Mock(),
                                     audio=None, play_audio=Mock(), open_audio_settings=Mock())
            QuickLookupWindow.audio_source_menu(window, None)
            labels = [call.args[0] for call in menu_type.return_value.addAction.call_args_list]
            self.assertIn("Turkish recordings", labels)
            self.assertIn("Online pronunciations", labels)
            self.assertNotIn("System voice", labels)

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
                    settings.setValue("profiles/ru/audio_priority", ["tts"])
                    audio.worker.submit.reset_mock()
                    audio.play(word, 2, settings)
                    audio.worker.submit.assert_not_called()
                    audio.cancel()
                    audio.worker.cancel.assert_called()
            finally:
                audio.shutdown()
                audio.deleteLater()


class AudioSourceSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from meikipop.gui.audio_sources import AudioSources
        worker = patch("meikipop.gui.audio_sources.AudioWorker")
        worker.start()
        self.addCleanup(worker.stop)
        self.sources = AudioSources()
        self.addCleanup(self.sources.deleteLater)
        self.addCleanup(self.sources.shutdown)

    def test_import_enables_named_sources_before_fallbacks_in_one_update(self):
        self.sources.load(["tts", "online"], "android.db", prefer_local=True)
        changed = Mock()
        self.sources.changed.connect(changed)
        self.sources.received("android.db", ["jpod", "nhk"])
        self.assertEqual(self.sources.order(), ["db:jpod", "db:nhk", "tts", "online"])
        self.assertEqual(self.sources.items.count(), 4)
        changed.assert_called_once_with()

    def test_reload_preserves_custom_priority_and_disabled_sources(self):
        self.sources.load(["online", "db:nhk", "tts"], "android.db")
        self.sources.received("android.db", ["jpod", "nhk"])
        self.assertEqual(self.sources.order(), ["online", "db:nhk", "tts"])
        self.assertEqual(self.sources.items.count(), 4)
        self.sources.load([], "android.db")
        self.sources.received("android.db", ["jpod", "nhk"])
        self.assertEqual(self.sources.order(), [])
        self.assertEqual(self.sources.items.count(), 4)

    def test_legacy_aggregate_expands_once_without_remaining_in_list(self):
        self.sources.load(["tts", "online", "db:nhk", "database"], "android.db")
        self.sources.received("android.db", ["jpod", "nhk"])
        self.assertEqual(self.sources.order(), ["db:nhk", "db:jpod", "tts", "online"])
        self.assertEqual(self.sources.items.count(), 4)

    def test_removal_ignores_pending_database_response(self):
        self.sources.load(["db:jpod", "tts"], "android.db")
        self.sources.load(self.sources.order(), "")
        self.sources.received("android.db", ["jpod", "nhk"])
        self.assertEqual(self.sources.order(), ["tts"])
        self.assertEqual(self.sources.items.count(), 2)

    def test_remove_button_clears_profile_and_keeps_database_file(self):
        from meikipop.gui.dictionary_manager import SetupDialog
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "android.db"
            path.touch()
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/audio_database", str(path))
            settings.setValue("profiles/ja/audio_priority", ["db:jpod", "online", "tts"])
            settings.setValue("profiles/tr/audio_database", "other.db")
            dialog = SetupDialog(Path(folder) / "library", settings, Mock())
            try:
                dialog.audio_remove.click()
                self.assertTrue(path.exists())
                self.assertEqual(settings.value("profiles/ja/audio_database"), "")
                self.assertEqual(settings.value("profiles/ja/audio_priority"), ["online", "tts"])
                self.assertEqual(settings.value("profiles/tr/audio_database"), "other.db")
                self.assertTrue(dialog.audio_remove.isHidden())
            finally:
                dialog.audio_sources.shutdown()
                dialog.deleteLater()
