import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication, QWidget
from pynput import keyboard, mouse

from meikipop.gui.turkish.desktop_input import DesktopInput


class ScanGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("meikipop.gui.turkish.desktop_input.KeyboardListener"), \
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

    def test_non_windows_pin_does_not_also_dismiss_popup_and_normal_click_still_works(self):
        clicked = Mock()
        self.input.clicked.connect(clicked)
        self.ready()
        with patch("meikipop.gui.turkish.desktop_input.sys.platform", "darwin"):
            self.input.click(10, 20, mouse.Button.left, True)
            self.input.click(10, 20, mouse.Button.left, False)
        self.requested.assert_called_once_with()
        clicked.assert_not_called()
        self.input.clicks.suppress_event.assert_not_called()
        with patch("meikipop.gui.turkish.desktop_input.sys.platform", "darwin"):
            self.input.click(10, 20, mouse.Button.left, True)
        clicked.assert_called_once_with()

    def test_macos_pin_click_intercept_consumes_only_matching_down_and_up(self):
        self.ready()
        quartz = SimpleNamespace(kCGEventLeftMouseDown=1, kCGEventLeftMouseUp=2,
                                 kCGEventOtherMouseDown=25, kCGEventOtherMouseUp=26,
                                 kCGMouseEventButtonNumber=3, kCGMouseButtonCenter=2)
        event = object()
        with patch("meikipop.gui.turkish.desktop_input.sys.platform", "darwin"), \
                patch("pynput.mouse._darwin.Quartz", quartz):
            self.input.click(10, 20, mouse.Button.left, True)
            self.assertIsNone(self.input.darwin_intercept(1, event))
            self.input.click(10, 20, mouse.Button.left, False)
            self.assertIsNone(self.input.darwin_intercept(2, event))
            self.assertIs(self.input.darwin_intercept(1, event), event)

    def test_macos_unrelated_events_pass_through_without_a_pin(self):
        quartz = SimpleNamespace(kCGEventLeftMouseDown=1, kCGEventLeftMouseUp=2,
                                 kCGEventOtherMouseDown=25, kCGEventOtherMouseUp=26,
                                 kCGMouseEventButtonNumber=3, kCGMouseButtonCenter=2,
                                 kCGEventMouseMoved=5, kCGEventScrollWheel=22)
        event = object()
        with patch("pynput.mouse._darwin.Quartz", quartz):
            self.assertIs(self.input.darwin_intercept(5, event), event)
            self.assertIs(self.input.darwin_intercept(22, event), event)

    def test_macos_listener_uses_pynput_darwin_intercept_option(self):
        with patch("meikipop.gui.turkish.desktop_input.KeyboardListener") as keyboard_listener, \
                patch("meikipop.gui.turkish.desktop_input.mouse.Listener") as mouse_listener:
            probe = DesktopInput("shift", "", "", 400)
        try:
            self.assertEqual(keyboard_listener.call_args.kwargs["darwin_intercept"], probe.darwin_key_intercept)
            self.assertEqual(mouse_listener.call_args.kwargs["darwin_intercept"], probe.darwin_intercept)
        finally:
            probe.shutdown()

    @unittest.skipUnless(sys.platform == "darwin", "macOS listener backend")
    def test_actual_macos_listeners_store_interceptors_without_starting_hooks(self):
        from meikipop.gui.turkish.desktop_input import KeyboardListener
        with patch.object(KeyboardListener, "start"), patch.object(KeyboardListener, "stop"), \
                patch.object(KeyboardListener, "join"), patch.object(mouse.Listener, "start"), \
                patch.object(mouse.Listener, "stop"), patch.object(mouse.Listener, "join"):
            probe = DesktopInput("shift", "", "", 400)
            try:
                self.assertEqual(probe.keys._intercept, probe.darwin_key_intercept)
                self.assertEqual(probe.clicks._intercept, probe.darwin_intercept)
            finally:
                probe.shutdown()

    def test_macos_escape_intercept_consumes_release_after_dismissal(self):
        self.input.visible.set()
        quartz = SimpleNamespace(kCGEventKeyDown=10, kCGEventKeyUp=11,
                                 kCGKeyboardEventKeycode=9,
                                 CGEventGetIntegerValueField=lambda event, field: 53)
        event = object()
        with patch("meikipop.gui.turkish.desktop_input.sys.platform", "darwin"), \
                patch.multiple("pynput.keyboard._darwin", kCGEventKeyDown=10, kCGEventKeyUp=11,
                                kCGKeyboardEventKeycode=9,
                                CGEventGetIntegerValueField=quartz.CGEventGetIntegerValueField):
            self.input.key(keyboard.Key.esc, True)
            self.assertIsNone(self.input.darwin_key_intercept(10, event))
            self.input.visible.clear()
            self.input.key(keyboard.Key.esc, False)
            self.assertIsNone(self.input.darwin_key_intercept(11, event))
            self.assertIs(self.input.darwin_key_intercept(10, event), event)

    def test_macos_pin_shortcut_intercept_consumes_eligible_key_pair(self):
        self.ready()
        self.input.set_pin_shortcut("c")
        self.input.keys.canonical.side_effect = lambda key: keyboard.KeyCode.from_char("c")
        quartz = SimpleNamespace(kCGEventKeyDown=10, kCGEventKeyUp=11,
                                 kCGKeyboardEventKeycode=9,
                                 CGEventGetIntegerValueField=lambda event, field: 8)
        event = object()
        with patch("meikipop.gui.turkish.desktop_input.sys.platform", "darwin"), \
                patch.multiple("pynput.keyboard._darwin", kCGEventKeyDown=10, kCGEventKeyUp=11,
                                kCGKeyboardEventKeycode=9,
                                CGEventGetIntegerValueField=quartz.CGEventGetIntegerValueField):
            self.input.key(keyboard.KeyCode.from_vk(8), True)
            self.assertIsNone(self.input.darwin_key_intercept(10, event))
            self.input.key(keyboard.KeyCode.from_vk(8), False)
            self.assertIsNone(self.input.darwin_key_intercept(11, event))
            self.assertIs(self.input.darwin_key_intercept(10, event), event)

    @unittest.skipUnless(sys.platform == "win32", "Windows native hook")
    def test_pin_key_consumes_press_repeats_and_release_only_for_ready_preview(self):
        self.input.set_pin_shortcut("c")
        event = SimpleNamespace(vkCode=ord("C"))
        self.input.filter_key(0x100, event)
        self.input.keys.suppress_event.assert_not_called()
        self.ready()
        self.input.filter_key(0x100, event)
        self.input.filter_key(0x100, event)
        self.input.activation.update("shift", False)
        self.input.visible.clear()
        self.input.set_pin_shortcut("")
        self.input.filter_key(0x101, event)
        self.requested.assert_called_once_with()
        self.assertEqual(self.input.keys.suppress_event.call_count, 3)
        self.input.filter_key(0x100, event)
        self.assertEqual(self.input.keys.suppress_event.call_count, 3)

    def test_pin_key_can_be_changed_or_disabled_and_requires_scan_preview(self):
        with patch("meikipop.gui.turkish.desktop_input.sys.platform", "darwin"):
            self.input.keys.canonical.side_effect = lambda key: key
            self.input.set_pin_shortcut("x")
            self.input.key(keyboard.KeyCode.from_char("x"), True)
            self.input.key(keyboard.KeyCode.from_char("x"), False)
            self.requested.assert_not_called()
            self.ready()
            self.input.key(keyboard.KeyCode.from_char("c"), True)
            self.requested.assert_not_called()
            self.input.key(keyboard.KeyCode.from_char("x"), True)
            self.requested.assert_called_once_with()
            self.input.set_pin_shortcut("")
            self.ready()
            self.input.key(keyboard.KeyCode.from_char("x"), True)
            self.requested.assert_called_once_with()

    def test_escape_and_modifier_only_cannot_replace_dismiss_or_scan(self):
        for value in ("<esc>", "<shift>", "<ctrl>+<shift>"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.input.set_pin_shortcut(value)

    @unittest.skipUnless(sys.platform == "win32", "Windows virtual keys")
    def test_latin_pin_presets_work_when_typing_layout_cannot_produce_latin(self):
        with patch("ctypes.WinDLL") as library:
            library.return_value.VkKeyScanW.return_value = -1
            self.input.set_pin_shortcut("c")
            self.assertEqual(self.input._pin_native[0], 0x43)
            self.input.set_pin_shortcut("x")
            self.assertEqual(self.input._pin_native[0], 0x58)
            library.assert_not_called()


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
            window.set_mode = Mock()
            window._render = Mock()
            window.reload_appearance = Mock()
            changed = Mock()
            window.scan_settings_changed.connect(changed)
            settings = QSettings(str(Path(temp) / "settings.ini"), QSettings.Format.IniFormat)
            dialog = SetupDialog(Path(temp) / "library", settings, Mock(), window)
            dialog.profile.addItem("Turkish", "tr")
            try:
                self.assertFalse(hasattr(dialog, "auto_scan"))
                self.assertTrue(dialog.appearance.compact_preview.isChecked())
                self.assertEqual(dialog.pin_gesture.currentData(), "left")
                self.assertEqual(dialog.ja_ocr_provider.currentData(), "vision" if sys.platform == "darwin" else "meikiocr")
                self.assertEqual(dialog.tr_ocr_provider.currentData(), "vision" if sys.platform == "darwin" else "paddle")
                dialog.appearance.compact_preview.click()
                dialog.pin_gesture.setCurrentIndex(dialog.pin_gesture.findData("popup"))
                self.assertFalse(settings.value("profiles/ja/auto_scan", False, bool))
                self.assertFalse(settings.value("profiles/ja/compact_preview", True, bool))
                self.assertEqual(settings.value("profiles/ja/pin_gesture"), "popup")
                window._render.assert_called_once_with()
                changed.assert_called_once_with()
                component = Path(temp) / "component"
                component.mkdir()
                from meikipop.ocr.providers.screenai.component import library_names
                (component / library_names()[0]).touch()
                dialog.screenai_directory.setText(str(component))
                dialog.ja_ocr_provider.setCurrentIndex(dialog.ja_ocr_provider.findData("screenai"))
                self.assertEqual(settings.value("ja_ocr_provider"), "screenai")
                self.assertEqual(settings.value("screenai_directory"), str(component))
                self.assertEqual(changed.call_count, 2)
                self.assertFalse(dialog.selected_text.isChecked())
                self.assertEqual(dialog.scan_key.currentData(), "shift")
                self.assertEqual(dialog.scan_mouse.currentData(), "")
                self.assertEqual(dialog.pin_shortcut.text(), "c")
                dialog.pin_shortcut.recorder.setKeySequence(QKeySequence("X"))
                dialog.pin_shortcut.recorder.editingFinished.emit()
                self.assertEqual(settings.value("profiles/ja/pin_shortcut"), "x")
                dialog.selected_text.click()
                self.assertTrue(settings.value("profiles/ja/selected_text", False, bool))
                dialog.audio_autoplay.setCurrentIndex(dialog.audio_autoplay.findData("pin"))
                self.assertEqual(settings.value("profiles/ja/audio_autoplay_mode"), "pin")
                dialog.profile.setCurrentIndex(dialog.profile.findData("tr"))
                self.assertEqual(dialog.pin_shortcut.text(), "c")
                self.assertNotEqual(dialog.audio_autoplay.currentData(), "pin")
                dialog.profile.setCurrentIndex(dialog.profile.findData("ja"))
                self.assertEqual(dialog.pin_shortcut.text(), "x")
                self.assertEqual(dialog.audio_autoplay.currentData(), "pin")
                dialog.profile.setCurrentIndex(dialog.profile.findData("tr"))
                self.assertFalse(dialog.selected_text.isChecked())
                dialog.selected_text.click()
                self.assertTrue(settings.value("profiles/tr/selected_text", False, bool))
                self.assertTrue(settings.value("profiles/ja/selected_text", False, bool))
            finally:
                dialog.deleteLater()
                window.deleteLater()
                self.app.processEvents()

    def test_invalid_translation_preferences_do_not_prevent_opening_settings(self):
        from meikipop.gui.dictionary_manager import SetupDialog
        with tempfile.TemporaryDirectory() as temp:
            settings = QSettings(str(Path(temp) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/translation", '{"unknown": true}')
            settings.setValue("profiles/tr/translation", 'invalid json')
            dialog = SetupDialog(Path(temp) / "library", settings, Mock())
            try:
                self.assertIn("Invalid translation settings", dialog.status.text())
                dialog.profile.setCurrentIndex(dialog.profile.findData("tr"))
                self.assertIn("Invalid translation settings", dialog.status.text())
            finally:
                dialog.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
