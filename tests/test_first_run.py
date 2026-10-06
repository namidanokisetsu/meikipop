import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QWidget
from meikipop.gui.first_run import SetupWizard, needs_setup


class FirstRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = QSettings(str(Path(self.directory.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.window = QWidget()
        self.window.settings = self.settings
        self.window.preferred_foreign = "ja"
        for name in ("update_languages", "set_mode", "apply_shortcut", "open_search"):
            setattr(self.window, name, Mock())
        self.wizard = SetupWizard(self.window)
        self.addCleanup(self.wizard.deleteLater)
        self.addCleanup(self.window.deleteLater)

    def test_new_existing_and_cancelled_installations(self):
        self.assertTrue(needs_setup(self.settings))
        self.settings.setValue("profile", "tr")
        self.assertFalse(needs_setup(self.settings))
        self.settings.setValue("setup/pending", True)
        self.wizard.reject()
        self.assertTrue(needs_setup(self.settings))
        self.assertFalse(self.settings.value("setup/completed", False, bool))

    def test_finish_preserves_models_and_keeps_shortcut_opt_in(self):
        self.settings.setValue("profiles/ja/translation_model", "existing.gguf")
        self.settings.setValue("setup/pending", True)
        self.wizard.language.setCurrentIndex(self.wizard.language.findData("tr"))
        self.wizard.accept()
        self.window.set_mode.assert_called_once_with("tr")
        self.window.apply_shortcut.assert_called_once_with("")
        self.assertFalse(needs_setup(self.settings))
        self.assertTrue(self.settings.value("setup/completed", False, bool))
        self.assertEqual(self.settings.value("profiles/ja/translation_model"), "existing.gguf")
        self.window.open_search.assert_called_once()

    def test_failed_shortcut_does_not_complete_setup(self):
        self.window.apply_shortcut.side_effect = OSError("Shortcut unavailable")
        self.wizard.accept()
        self.assertFalse(self.settings.value("setup/completed", False, bool))
        self.assertIn("unavailable", self.wizard.error.text())


class ModelInstallerTests(unittest.TestCase):
    def test_frozen_morphology_uses_bundled_worker(self):
        from meikipop.scripts.setup_morphology import install
        with patch("sys.frozen", True, create=True), patch("meikipop.scripts.setup_morphology._run") as run:
            install("tr")
        run.assert_called_once_with(["--setup-morphology", "tr"], None)

    def test_cancelled_ocr_does_not_start_downloader(self):
        from meikipop.scripts.setup_ocr import install
        cancelled = threading.Event()
        cancelled.set()
        with patch("meikipop.scripts.setup_morphology._run") as run:
            with self.assertRaises(InterruptedError):
                install("paddle", Mock(), cancelled)
        run.assert_not_called()

    def test_component_extraction_rejects_path_escape(self):
        from meikipop.scripts.setup_ocr import extract_component
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "component.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escaped.dll", b"bad")
            with self.assertRaises(ValueError):
                extract_component(archive, Path(folder) / "output")
            self.assertFalse((Path(folder) / "escaped.dll").exists())
