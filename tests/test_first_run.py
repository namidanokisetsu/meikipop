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
        for task, check in self.wizard.choices:
            check.setChecked(False)
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

    def test_unchecking_everything_starts_without_downloads(self):
        for task, check in self.wizard.choices:
            check.setChecked(False)
        with patch("meikipop.gui.language_setup.LanguageSetup") as setup:
            self.wizard.accept()
        setup.assert_not_called()
        self.assertIsNone(self.wizard.operation)
        self.assertTrue(self.settings.value("setup/completed", False, bool))

    def test_dictionary_is_optional_and_translation_uses_selected_size(self):
        for task, check in self.wizard.choices:
            check.setChecked(task.kind == "translation")
        self.wizard.translation.setCurrentIndex(1)
        tasks = self.wizard.selected_tasks()
        self.assertEqual([(task.kind, task.value) for task in tasks], [("translation", "quality")])

    def test_automatic_setup_starts_once_after_language_selection(self):
        self.window.directory = self.directory.name
        with patch("meikipop.gui.language_setup.LanguageSetup") as setup:
            self.wizard.begin_downloads()
            self.wizard.begin_downloads()
        setup.assert_called_once()
        setup.return_value.thread.start.assert_called_once()
        self.wizard.operation = None

    def test_language_plan_uses_supported_models_and_native_mac_ocr(self):
        from meikipop.gui.language_setup import language_plan
        japanese = language_plan("ja", platform="win32")
        self.assertEqual([task.kind for task in japanese], ["dictionary", "ocr", "translation"])
        self.assertEqual(japanese[-1].value, "lightweight")
        turkish = language_plan("tr", platform="darwin")
        self.assertEqual([task.kind for task in turkish], ["dictionary", "morphology", "translation"])

    def test_cancelled_language_setup_does_not_start_downloads(self):
        from meikipop.gui.language_setup import LanguageSetup, language_plan
        operation = LanguageSetup(language_plan("ja"), self.directory.name)
        operation.cancelled.set()
        with patch("meikipop.gui.language_setup.install_task") as install:
            operation.run()
        install.assert_not_called()


class ModelInstallerTests(unittest.TestCase):
    def test_frozen_failure_retains_the_cause_instead_of_bootloader_footer(self):
        from meikipop.scripts.setup_morphology import _run
        output = "Traceback:\nModuleNotFoundError: No module named 'dependency'\n[PYI-10044:ERROR] Failed to execute script 'quick_lookup'\n"
        with patch("meikipop.scripts.setup_morphology.subprocess.Popen") as popen:
            popen.return_value.communicate.return_value = (output, None)
            popen.return_value.returncode = 1
            with self.assertLogs("meikipop.scripts.setup_morphology", level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "ModuleNotFoundError: No module named 'dependency'"):
                    _run(["--setup-morphology", "tr"])
        self.assertIn("Traceback", captured.output[0])

    def test_model_worker_validates_loaded_models_and_returns_readable_errors(self):
        from meikipop.scripts.quick_lookup import main
        with patch("meikipop.language.stanza_analyzer.setup_models") as download, \
                patch("meikipop.language.stanza_analyzer.StanzaAnalyzer") as analyzer, \
                patch("sys.stderr") as stderr:
            self.assertEqual(main(["--setup-morphology", "tr"]), 0)
            download.assert_called_once_with(language="tr")
            analyzer.assert_called_once_with(language="tr")
            analyzer.side_effect = RuntimeError("Cannot load downloaded model")
            self.assertEqual(main(["--setup-morphology", "tr"]), 1)
            self.assertIn("RuntimeError: Cannot load downloaded model", "".join(call.args[0] for call in stderr.write.call_args_list))

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
