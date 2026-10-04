import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from pynput import mouse

from meikipop.gui.turkish.desktop_input import DesktopInput


class ScanGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("meikipop.gui.turkish.desktop_input.keyboard.Listener"), \
                patch("meikipop.gui.turkish.desktop_input.mouse.Listener"):
            self.input = DesktopInput("shift,middle", "", "", 400)
        self.addCleanup(self.input.shutdown)
        self.requested = Mock()
        self.input.pin_requested.connect(self.requested)

    def ready(self, gesture="left"):
        self.input.activation.update("shift", True)
        self.input.visible.set()
        self.input.pin_ready.set()
        self.input.pin_gesture = gesture

    def test_windows_suppresses_only_eligible_pin_click_and_matching_release(self):
        self.assertTrue(self.input.filter_mouse(0x201, None))
        self.input.activation.update("shift", True)
        self.assertTrue(self.input.filter_mouse(0x201, None))
        self.ready()
        self.assertTrue(self.input.filter_mouse(0x204, None))  # Right click.
        self.assertFalse(self.input.filter_mouse(0x201, None))
        self.requested.assert_called_once_with()
        self.assertTrue(self.input.pin_pending.is_set())
        self.assertFalse(self.input.pin_ready.is_set())
        self.input.activation.update("shift", False)
        self.input.visible.clear()
        self.assertFalse(self.input.filter_mouse(0x202, None))
        self.assertEqual(self.input.clicks.suppress_event.call_count, 2)
        self.assertTrue(self.input.filter_mouse(0x201, None))
        self.assertTrue(self.input.filter_mouse(0x202, None))

    def test_no_trigger_or_manual_window_cannot_intercept_clicks(self):
        self.ready()
        self.input.activation.update("shift", False)
        self.assertTrue(self.input.filter_mouse(0x201, None))
        self.input.activation.update("shift", True)
        self.input.pin_ready.clear()
        self.assertTrue(self.input.filter_mouse(0x201, None))
        self.requested.assert_not_called()
        self.input.clicks.suppress_event.assert_not_called()

    def test_middle_gesture_is_configurable_and_popup_only_disables_global_pin(self):
        self.ready("middle")
        self.assertTrue(self.input.filter_mouse(0x201, None))
        self.assertFalse(self.input.filter_mouse(0x207, None))
        self.assertFalse(self.input.filter_mouse(0x208, None))
        self.requested.assert_called_once_with()
        self.ready("popup")
        self.assertTrue(self.input.filter_mouse(0x201, None))
        self.assertTrue(self.input.filter_mouse(0x207, None))
        self.requested.assert_called_once_with()

    def test_non_windows_pin_is_opt_in_and_preserves_normal_click_callback(self):
        clicked = Mock()
        self.input.clicked.connect(clicked)
        self.ready()
        with patch("meikipop.gui.turkish.desktop_input.sys.platform", "darwin"):
            self.input.click(10, 20, mouse.Button.left, True)
            self.input.click(10, 20, mouse.Button.left, False)
        self.requested.assert_called_once_with()
        clicked.assert_called_once_with()
        self.input.clicks.suppress_event.assert_not_called()


class ScanSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_defaults_and_saved_controls_update_current_window(self):
        from meikipop.gui.dictionary_manager import SetupDialog

        class Window(QWidget):
            scan_settings_changed = pyqtSignal()

        with tempfile.TemporaryDirectory() as temp:
            window = Window()
            window.set_compact_preview = Mock()
            changed = Mock()
            window.scan_settings_changed.connect(changed)
            settings = QSettings(str(Path(temp) / "settings.ini"), QSettings.Format.IniFormat)
            dialog = SetupDialog(Path(temp) / "library", settings, Mock(), window)
            try:
                self.assertFalse(dialog.auto_scan.isChecked())
                self.assertTrue(dialog.compact_preview.isChecked())
                self.assertEqual(dialog.pin_gesture.currentData(), "left")
                self.assertEqual(dialog.ja_ocr_provider.currentData(), "vision" if sys.platform == "darwin" else "meikiocr")
                self.assertEqual(dialog.tr_ocr_provider.currentData(), "vision" if sys.platform == "darwin" else "paddle")
                dialog.auto_scan.click()
                dialog.compact_preview.click()
                dialog.pin_gesture.setCurrentIndex(dialog.pin_gesture.findData("popup"))
                dialog.save_scan_settings()
                self.assertTrue(settings.value("auto_scan", False, bool))
                self.assertFalse(settings.value("compact_preview", True, bool))
                self.assertEqual(settings.value("pin_gesture"), "popup")
                window.set_compact_preview.assert_called_once_with(False)
                changed.assert_called_once_with()
                component = Path(temp) / "component"
                component.mkdir()
                from meikipop.ocr.providers.screenai.component import library_names
                (component / library_names()[0]).touch()
                dialog.screenai_directory.setText(str(component))
                dialog.ja_ocr_provider.setCurrentIndex(dialog.ja_ocr_provider.findData("screenai"))
                dialog.save_scan_settings()
                self.assertEqual(settings.value("ja_ocr_provider"), "screenai")
                self.assertEqual(settings.value("screenai_directory"), str(component))
                self.assertEqual(changed.call_count, 2)
            finally:
                dialog.deleteLater()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
