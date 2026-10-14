import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QWidget
from meikipop.dictionary.translation import TranslationSettings, load_profile_settings, save_profile_settings
from meikipop.gui.dictionary_manager import SetupDialog
from meikipop.gui.resources import translation_ready


class ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_translation_ready_requires_shared_model_and_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "server.exe").write_bytes(b"runtime")
            (root / "model.gguf").write_bytes(b"model")
            (root / "installation.json").write_text(json.dumps({
                "executable": "server.exe", "models": {"lightweight": {"path": "model.gguf", "size": 5}}}))
            with patch("meikipop.scripts.translation_server.translation_path", return_value=root):
                self.assertTrue(translation_ready("lightweight"))
                self.assertFalse(translation_ready("quality"))
                (root / "model.gguf").write_bytes(b"partial")
                self.assertFalse(translation_ready("lightweight"))

    def test_removing_recommended_dictionary_restores_download_action(self):
        import threading
        import zipfile
        from meikipop.dictionary.library import import_yomitan, remove_dictionary
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "dictionary.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("index.json", json.dumps({"title": "wty-tr-en", "sourceLanguage": "tr", "format": 3}))
                bundle.writestr("term_bank_1.json", json.dumps([["ev", "", "", "", 0, ["house"]]]))
            pack = import_yomitan(archive, root / "library")
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profile", "tr")
            with patch("meikipop.gui.resources.ocr_ready", return_value=False), \
                    patch("meikipop.gui.resources.translation_ready", return_value=False):
                dialog = SetupDialog(root / "library", settings, Mock())
                try:
                    self.assertTrue(dialog.resources.dictionary_install.isHidden())
                    remove_dictionary(root / "library", pack.name, lambda: None, threading.Event())
                    dialog.resources.refresh()
                    self.assertFalse(dialog.resources.dictionary_install.isHidden())
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()

    def test_shared_downloads_and_profile_model_selection_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            for code in ("ja", "tr"):
                save_profile_settings(settings, code, TranslationSettings(profile="quality"))
            with patch("meikipop.gui.resources.ocr_ready", return_value=True), \
                    patch("meikipop.gui.resources.translation_ready", side_effect=lambda name: name == "lightweight"):
                dialog = SetupDialog(Path(directory) / "library", settings, Mock())
                try:
                    resources = dialog.resources
                    self.assertEqual([dialog.tabs.tabText(i) for i in range(dialog.tabs.count())],
                                     ["Lookup", "Dictionaries", "Appearance", "Audio", "Translation", "Anki"])
                    dialog.show_anki()
                    self.assertIs(dialog.tabs.currentWidget(), dialog.anki_tab)
                    dialog.show_audio()
                    self.assertIs(dialog.tabs.currentWidget(), dialog.audio_tab)
                    self.assertFalse(resources.downloads["lightweight"].isEnabled())
                    self.assertTrue(resources.downloads["quality"].isEnabled())
                    dialog.translation_mode.setCurrentIndex(dialog.translation_mode.findData("lightweight"))
                    self.assertEqual(load_profile_settings(settings, "ja").profile, "lightweight")
                    self.assertTrue(resources.model_rows["lightweight"].isHidden())
                    dialog.sync_profile("tr")
                    self.assertEqual(load_profile_settings(settings, "tr").profile, "quality")
                    self.assertFalse(resources.downloads["lightweight"].isEnabled())
                    self.assertFalse(resources.model_rows["quality"].isHidden())
                    with patch.object(dialog, "begin_operation") as install:
                        resources.downloads["quality"].click()
                        install.assert_called_once_with([], profile="quality")
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()

    def test_translation_defaults_hide_manual_direction_and_start_models_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            save_profile_settings(settings, "ja", TranslationSettings(auto_start=False))
            with patch("meikipop.gui.resources.ocr_ready", return_value=False), \
                    patch("meikipop.gui.resources.translation_ready", return_value=False):
                dialog = SetupDialog(Path(directory) / "library", settings, Mock())
                try:
                    self.assertFalse(dialog.translation_advanced.isChecked())
                    self.assertTrue(dialog.translation_advanced_widget.isHidden())
                    self.assertTrue(load_profile_settings(settings, "ja").auto_start)
                    dialog.translation_advanced.click()
                    self.assertFalse(dialog.translation_advanced_widget.isHidden())
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()

    def test_unsupported_resources_never_offer_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profile", "gem-pro")
            settings.setValue("profiles/gem-pro/target", "en")
            settings.setValue("profiles/yi/ocr_provider", "paddle")
            with patch("meikipop.gui.resources.ocr_ready", return_value=False), \
                    patch("meikipop.gui.resources.translation_ready", return_value=False):
                dialog = SetupDialog(Path(directory) / "library", settings, Mock())
                try:
                    for code in ("gem-pro", "yi"):
                        with self.subTest(code=code), patch.object(dialog, "begin_operation") as install:
                            dialog.sync_profile(code)
                            resources = dialog.resources
                            self.assertTrue(resources.ocr_section.isHidden())
                            self.assertFalse(resources.ocr_install.isEnabled())
                            self.assertNotIn("Unavailable", resources.ocr_install.text())
                            self.assertTrue(resources.translation_section.isHidden())
                            self.assertTrue(all(row.isHidden() for row in resources.model_rows.values()))
                            resources.ocr_install.click()
                            for download in resources.downloads.values():
                                self.assertFalse(download.isEnabled())
                                download.click()
                            install.assert_not_called()
                    self.assertEqual(settings.value("profiles/yi/ocr_provider"), "paddle")
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()

    def test_translation_downloads_refresh_after_unsupported_pair_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profile", "ja")
            settings.setValue("profiles/ja/target", "yi")
            with patch("meikipop.gui.resources.ocr_ready", return_value=True), \
                    patch("meikipop.gui.resources.translation_ready", return_value=False):
                dialog = SetupDialog(Path(directory) / "library", settings, Mock())
                try:
                    self.assertTrue(dialog.resources.translation_section.isHidden())
                    self.assertFalse(dialog.resources.downloads["quality"].isEnabled())
                    self.assertEqual(settings.value("profiles/ja/target"), "yi")
                    dialog.translation_partner.setCurrentIndex(dialog.translation_partner.findData("ru"))
                    self.assertFalse(dialog.resources.model_rows["quality"].isHidden())
                    self.assertTrue(dialog.resources.downloads["quality"].isEnabled())
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()

    def test_empty_japanese_settings_only_offer_actionable_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/target", "en")
            with patch("meikipop.gui.resources.ocr_ready", return_value=True), \
                    patch("meikipop.gui.resources.translation_ready", return_value=False):
                dialog = SetupDialog(Path(directory) / "library", settings, Mock())
                try:
                    self.assertTrue(dialog.resources.base_install.isHidden())
                    self.assertTrue(dialog.resources.ocr_section.isHidden())
                    self.assertTrue(dialog.combine_frequencies.isHidden())
                    self.assertTrue(dialog.packs.isHidden())
                    self.assertTrue(dialog.translation_endpoint.isHidden())
                    with patch.object(dialog, "begin_operation") as install:
                        dialog.resources.dictionary_install.click()
                    dictionaries = install.call_args.kwargs["recommended"]
                    self.assertEqual([item.pack_title for item in dictionaries],
                                     ["Jitendex", "KANJIDIC", "BCCWJ", "Kanjium Pitch Accents"])
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()

    def test_recommended_batch_keeps_successful_imports_after_a_failure(self):
        from meikipop.dictionary.catalog import recommendations
        from meikipop.gui.dictionary_manager import SetupOperation
        dictionaries = recommendations("ja")
        operation = SetupOperation([], "/unused", recommended=dictionaries)
        results = []
        operation.finished.connect(lambda status, changed: results.append((status, changed)))
        with patch("meikipop.dictionary.import_job.background_import", side_effect=[
                ("Installed", True), RuntimeError("Offline"), ("Installed", True), ("Installed", True)]) as install:
            operation._run()
        self.assertEqual(install.call_count, 4)
        self.assertEqual(results, [("Kanji · KANJIDIC: Offline", True)])

    def test_cancelling_recommended_batch_stops_before_next_dictionary(self):
        from meikipop.dictionary.catalog import recommendations
        from meikipop.gui.dictionary_manager import SetupOperation
        operation = SetupOperation([], "/unused", recommended=recommendations("ja"))
        results = []
        operation.finished.connect(lambda status, changed: results.append((status, changed)))

        def install(*args):
            operation.cancelled.set()
            return "Installed", True

        with patch("meikipop.dictionary.import_job.background_import", side_effect=install) as download:
            operation._run()
        self.assertEqual(download.call_count, 1)
        self.assertEqual(results, [("Download cancelled.", True)])

    def test_stroke_order_font_action_is_japanese_only_and_uses_setup_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profile", "ja")
            settings.setValue("profiles/ja/target", "en")
            settings.setValue("profiles/tr/target", "en")
            with patch("meikipop.utils.stroke_order_font.font_ready", return_value=False), \
                    patch("meikipop.gui.resources.ocr_ready", return_value=True), \
                    patch("meikipop.gui.resources.translation_ready", return_value=True):
                dialog = SetupDialog(Path(directory) / "library", settings, Mock())
                try:
                    button = dialog.resources.font_install
                    self.assertTrue(dialog.appearance.detail_form.isRowVisible(button))
                    with patch.object(dialog, "begin_operation") as install:
                        button.click()
                        install.assert_called_once_with([], fonts=True)
                    dialog.sync_profile("tr")
                    self.assertFalse(dialog.appearance.detail_form.isRowVisible(button))
                    dialog.sync_profile("ja")
                    with patch("meikipop.utils.stroke_order_font.font_ready", return_value=True):
                        dialog.resources.refresh()
                        self.assertFalse(dialog.appearance.detail_form.isRowVisible(button))
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()
        from meikipop.gui.dictionary_manager import SetupOperation
        operation = SetupOperation([], "/unused", fonts=True)
        results = []
        operation.finished.connect(lambda status, changed: results.append((status, changed)))
        with patch("meikipop.scripts.setup_stroke_order_font.install") as install:
            operation._run()
            self.assertIs(install.call_args.args[1], operation.cancelled)
        self.assertEqual(results, [("Stroke-order font installed.", True)])

    def test_font_install_completion_redraws_current_kanji_without_preference_change(self):
        from meikipop.gui.dictionary_manager import SetupOperation
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/target", "en")
            parent = QWidget()
            parent.set_mode = Mock()
            parent.reload_appearance = Mock()
            parent.scan_settings_changed = Mock()
            parent._render_identity = ("existing kanji",)
            with patch("meikipop.utils.stroke_order_font.font_ready", return_value=True), \
                    patch("meikipop.gui.resources.ocr_ready", return_value=True), \
                    patch("meikipop.gui.resources.translation_ready", return_value=True):
                dialog = SetupDialog(Path(directory) / "library", settings, Mock(), parent)
                try:
                    parent.reload_appearance.reset_mock()
                    dialog.operation = SetupOperation([], directory, fonts=True)
                    dialog._finished("Stroke-order font installed.", True)
                    self.assertIsNone(parent._render_identity)
                    parent.reload_appearance.assert_called_once_with()
                    self.assertIsNone(dialog.operation)
                finally:
                    dialog.deleteLater(); parent.deleteLater()
                    self.app.processEvents()
