import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from meikipop.dictionary.translation import TranslationSettings, load_profile_settings, save_profile_settings
from meikipop.gui.dictionary_manager import SetupDialog
from meikipop.gui.resources import translation_ready


class ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_translation_ready_requires_shared_model_and_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "server.exe").write_bytes(b"runtime")
            (root / "model.gguf").write_bytes(b"model")
            (root / "installation.json").write_text(json.dumps({
                "executable": "server.exe", "models": {"lightweight": {"path": "model.gguf", "size": 5}}}))
            with patch("meikipop.scripts.translation_server.translation_path", return_value=root):
                self.assertTrue(translation_ready("lightweight"))
                self.assertFalse(translation_ready("quality"))
                (root / "model.gguf").write_bytes(b"partial")
                self.assertFalse(translation_ready("lightweight"))

    def test_removing_recommended_dictionary_clears_its_ready_indicator(self):
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
                    self.assertEqual(dialog.resources.indicators["dictionary"].text(), "● Installed")
                    remove_dictionary(root / "library", pack.name, lambda: None, threading.Event())
                    dialog.resources.refresh()
                    self.assertEqual(dialog.resources.indicators["dictionary"].text(), "○ Not installed")
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
                    self.assertEqual(dialog.tabs.tabText(0), "Resources")
                    self.assertFalse(resources.downloads["lightweight"].isEnabled())
                    self.assertTrue(resources.downloads["quality"].isEnabled())
                    resources.uses["lightweight"].click()
                    self.assertEqual(load_profile_settings(settings, "ja").profile, "lightweight")
                    self.assertIn("used by this profile", resources.indicators["lightweight"].text())
                    dialog.sync_profile("tr")
                    self.assertEqual(load_profile_settings(settings, "tr").profile, "quality")
                    self.assertFalse(resources.downloads["lightweight"].isEnabled())
                    self.assertNotIn("used by this profile", resources.indicators["lightweight"].text())
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
                    self.assertTrue(dialog.translation_autostart.isHidden())
                    self.assertTrue(load_profile_settings(settings, "ja").auto_start)
                    dialog.translation_advanced.click()
                    self.assertFalse(dialog.translation_advanced_widget.isHidden())
                finally:
                    dialog.deleteLater()
                    self.app.processEvents()
