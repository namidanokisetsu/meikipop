import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import threading
import sys
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QWidget
from meikipop.gui.first_run import FirstLanguage, LanguageSuggestion, complete_first_setup, needs_setup


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
        self.window.directory = self.directory.name
        self.window.preferred_foreign = "ja"
        self.window._setup = None
        self.window.refresh_library = Mock()
        self.window.scan_settings_changed = Mock()
        self.wizard = LanguageSuggestion(self.window)
        self.addCleanup(self.window.deleteLater)

    def test_only_fresh_installations_offer_the_initial_language(self):
        self.assertTrue(needs_setup(self.settings))
        self.settings.setValue("profile", "ja")
        self.assertTrue(needs_setup(self.settings))
        self.settings.setValue("profiles/ja/target", "en")
        self.assertFalse(needs_setup(self.settings))

    def test_first_language_keeps_dictionary_languages_and_existing_profiles(self):
        from meikipop.gui.quick_lookup import LANGUAGE_NAMES
        from meikipop.language.support import DICTIONARY_LANGUAGES
        self.settings.setValue("profiles/fil/target", "en")
        picker = FirstLanguage(self.settings, imported=("abc",))
        self.addCleanup(picker.deleteLater)
        codes = {picker.language.itemData(i) for i in range(1, picker.language.count())}
        self.assertEqual(codes, DICTIONARY_LANGUAGES | {"fil", "abc"})
        self.assertTrue({"ja", "tr", "en", "fr", "ru", "yi"} <= codes)
        self.assertIn("zh-hant", LANGUAGE_NAMES)
        self.assertNotIn("zh-hant", codes)

    def test_selected_language_survives_window_and_settings_without_extra_profiles(self):
        from meikipop.gui.quick_lookup import QuickLookupWindow
        from meikipop.gui.dictionary_manager import SetupDialog
        from meikipop.language.profiles import configured_profiles
        from test_quick_lookup import FakeEngine
        for code in ("tr", "en", "fr"):
            with self.subTest(language=code):
                self.settings.clear()
                picker = FirstLanguage(self.settings)
                picker.language.setCurrentIndex(picker.language.findData(code))
                picker.accept()
                picker.deleteLater()
                engine = FakeEngine()
                engine.library.packs = []
                popup = QuickLookupWindow(self.directory.name, lambda: engine, self.settings)
                dialog = SetupDialog(self.directory.name, self.settings, Mock())
                try:
                    self.app.processEvents()
                    self.assertEqual(configured_profiles(self.settings), (code,))
                    self.assertEqual([popup.source.itemData(i) for i in range(popup.source.count())], [code])
                    self.assertEqual([dialog.profile.itemData(i) for i in range(dialog.profile.count())], [code])
                    self.assertFalse(self.settings.value(f"profiles/{code}/selection_lookup", False, bool))
                    self.assertFalse(self.settings.value(f"profiles/{code}/auto_translate_miss", False, bool))
                finally:
                    dialog.close()
                    dialog.deleteLater()
                    popup.shutdown()
                    popup.worker._thread.join(timeout=2)
                    popup.deleteLater()
                    self.app.processEvents()

    def test_first_language_has_no_default_and_does_not_add_japanese(self):
        from meikipop.language.profiles import configured_profiles
        picker = FirstLanguage(self.settings)
        self.addCleanup(picker.deleteLater)
        self.assertIsNone(picker.language.currentData())
        picker.accept()
        self.assertFalse(self.settings.allKeys())
        picker.language.setCurrentIndex(picker.language.findData("tr"))
        picker.accept()
        self.assertEqual(self.settings.value("profile"), "tr")
        self.assertEqual(configured_profiles(self.settings), ("tr",))
        self.assertFalse(needs_setup(self.settings))

    def test_reopening_setup_preserves_existing_profile_preferences(self):
        self.settings.setValue("profiles/tr/target", "ru")
        self.settings.setValue("profiles/ja/scan_bindings", "alt")
        picker = FirstLanguage(self.settings)
        self.addCleanup(picker.deleteLater)
        picker.language.setCurrentIndex(picker.language.findData("tr"))
        picker.accept()
        self.assertEqual(self.settings.value("profiles/tr/target"), "ru")
        self.assertEqual(self.settings.value("profiles/ja/scan_bindings"), "alt")

    def test_closing_language_picker_leaves_first_run_pending(self):
        picker = FirstLanguage(self.settings)
        self.addCleanup(picker.deleteLater)
        picker.language.setCurrentIndex(picker.language.findData("ru"))
        picker.reject()
        self.assertTrue(needs_setup(self.settings))

    def test_first_setup_registers_the_current_install_only_after_acceptance(self):
        from meikipop.utils import startup
        values = {}
        key = Mock()
        key.__enter__ = Mock(return_value=key)
        key.__exit__ = Mock(return_value=False)
        registry = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(), KEY_SET_VALUE=1, REG_SZ=1,
            OpenKey=Mock(side_effect=FileNotFoundError), CreateKeyEx=Mock(return_value=key),
            SetValueEx=lambda _key, name, _reserved, _kind, value: values.__setitem__(name, value))
        picker = FirstLanguage(self.settings)
        self.addCleanup(picker.deleteLater)
        with patch.object(startup.sys, "platform", "win32"), \
                patch.object(startup.sys, "frozen", True, create=True), \
                patch.dict(sys.modules, {"winreg": registry}):
            picker.reject()
            self.assertFalse(values)
            self.assertFalse(self.settings.contains("start_with_windows"))
            picker.language.setCurrentIndex(picker.language.findData("tr"))
            picker.accept()
            self.assertFalse(values)
            complete_first_setup(self.settings)
            self.assertEqual(values, {startup.VALUE_NAME: f'"{Path(sys.executable).resolve()}"'})
            self.assertTrue(self.settings.value("start_with_windows", False, bool))

    def test_first_setup_preserves_saved_startup_choice_and_existing_registration(self):
        with patch("sys.platform", "win32"), \
                patch("meikipop.utils.startup.is_startup_enabled", return_value=True) as enabled, \
                patch("meikipop.utils.startup.set_startup_enabled") as register:
            self.settings.setValue("start_with_windows", False)
            complete_first_setup(self.settings)
            enabled.assert_not_called()
            register.assert_not_called()
            self.assertFalse(self.settings.value("start_with_windows", True, bool))
            self.settings.remove("start_with_windows")
            complete_first_setup(self.settings)
            register.assert_not_called()
            self.assertTrue(self.settings.value("start_with_windows", False, bool))

    def test_failed_startup_registration_keeps_setup_usable_and_the_choice_unset(self):
        with patch("sys.platform", "win32"), \
                patch("meikipop.utils.startup.is_startup_enabled", return_value=False), \
                patch("meikipop.utils.startup.set_startup_enabled", side_effect=OSError("denied")), \
                self.assertLogs("meikipop.gui.first_run", level="ERROR"):
            complete_first_setup(self.settings)
        self.assertFalse(self.settings.contains("start_with_windows"))

    def test_suggestion_is_shown_once_per_profile_even_after_later(self):
        from meikipop.gui.first_run import offer_resources
        first = offer_resources(self.window, "ja")
        first.reject()
        self.assertIsNone(offer_resources(self.window, "ja"))
        second = offer_resources(self.window, "tr")
        self.assertEqual(second.language, "tr")
        self.assertIsNone(offer_resources(self.window, "tr"))
        self.assertFalse(self.settings.contains("setup/pending"))

    def test_unchecking_everything_closes_without_downloads(self):
        for task, check in self.wizard.choices:
            check.setChecked(False)
        with patch("meikipop.gui.language_setup.LanguageSetup") as setup:
            self.wizard.accept()
        setup.assert_not_called()
        self.assertIsNone(self.wizard.operation)

    def test_dictionary_is_optional_and_translation_uses_selected_size(self):
        self.assertTrue(all(check.isChecked() for task, check in self.wizard.choices))
        for task, check in self.wizard.choices:
            check.setChecked(task.kind == "translation")
        self.wizard.translation.setCurrentIndex(1)
        tasks = self.wizard.selected_tasks()
        self.assertEqual([(task.kind, task.value) for task in tasks], [("translation", "quality")])

    def test_setup_starts_once_with_only_selected_resources(self):
        with patch("meikipop.gui.language_setup.LanguageSetup") as setup:
            self.wizard.accept()
            self.wizard.accept()
        setup.assert_called_once()
        setup.return_value.thread.start.assert_called_once()
        self.assertTrue(any(task.kind == "translation" for task in setup.call_args.args[0]))
        self.wizard.operation = None

    def test_language_plan_uses_supported_models_and_native_mac_ocr(self):
        from meikipop.gui.language_setup import language_plan
        japanese = language_plan("ja", platform="win32")
        self.assertEqual([task.kind for task in japanese], ["dictionary"] * 4 + ["ocr", "translation"])
        self.assertEqual(japanese[-1].value, "lightweight")
        with patch("meikipop.ocr.macos_vision.supported_languages", return_value={"tr"}):
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
