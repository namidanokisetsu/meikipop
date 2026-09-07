import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings, QRect
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication, QWidget, QMenu

from meikipop.gui.clipboard_lookup import ClipboardLookup
from meikipop.utils.lastest_queue import LatestValueQueue


class ClipboardLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.popup = QWidget()
        self.popup.frame = QWidget()
        self.popup.set_latest_data = Mock()
        self.tray = SimpleNamespace(menu=QMenu())
        self.tray.geometry = lambda: QRect(20, 20, 24, 24)
        self.tray.menu.addAction("Settings")
        self.shared = SimpleNamespace(lookup_queue=LatestValueQueue())
        with patch("meikipop.gui.clipboard_lookup.TextHotKeys"), \
                patch("meikipop.gui.clipboard_lookup.mouse.Listener") as listener, \
                patch("meikipop.gui.clipboard_lookup.QSettings", return_value=QSettings(
                    str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)):
            self.controller = ClipboardLookup(self.shared, self.popup, self.tray)
            self.click_callback = listener.call_args.kwargs["on_click"]

    def tearDown(self):
        self.controller.shutdown()
        self.popup.deleteLater()
        self.temp.cleanup()

    def read(self, text):
        with patch.object(QApplication, "clipboard") as clipboard:
            clipboard.return_value.text.return_value = text
            self.controller.read()

    def test_mouse_callback_accepts_real_listener_and_forwards_click(self):
        from pynput import mouse
        listener = mouse.Listener(on_click=self.click_callback)
        self.controller.mouse_clicked.disconnect(self.controller.on_click)
        received = Mock()
        self.controller.mouse_clicked.connect(received)
        listener.on_click(10, 20, mouse.Button.left, True, False)
        received.assert_called_once_with(10, 20, mouse.Button.left, True)

    def test_dragged_selection_starts_copy_capture(self):
        from pynput import mouse
        self.controller.settings.setValue("double_click", True)
        with patch.object(self.controller.selection, "start") as start:
            self.controller.on_click(10, 10, mouse.Button.left, True)
            self.controller.on_click(30, 10, mouse.Button.left, False)
            start.assert_called_once_with(wait_for_modifiers=True)

    def test_reuses_lookup_and_dismissal_rejects_pending_result(self):
        self.read("食べました")
        revision = self.controller.revision
        lookup = Mock(return_value=["existing dictionary entries"])
        self.controller.process(lookup)
        lookup.assert_called_once_with("食べました")
        self.popup.set_latest_data.assert_called_with(["existing dictionary entries"])
        self.controller.process(lookup)
        lookup.assert_called_once()
        self.controller.dismiss()
        self.controller.deliver(revision, ["stale"])
        self.popup.set_latest_data.assert_called_with(None)
        self.assertFalse(self.controller.active)

    def test_empty_and_oversized_clipboards_do_not_activate(self):
        for text in ("", " ", "あ" * 2001):
            self.read(text)
            self.assertFalse(self.controller.active)

    def test_selection_delivers_audio_only_for_current_result(self):
        self.controller.audio_service = Mock()
        self.controller.selection.completed.emit("selected")
        revision = self.controller.revision
        self.controller.process(lambda text: [text])
        self.controller.audio_service.handle_text_result.assert_called_once_with(revision, ["selected"])
        self.controller.dismiss()
        self.controller.deliver(revision, ["stale"])
        self.controller.audio_service.handle_text_result.assert_called_once()

    def test_miss_closes_and_new_request_can_repeat_word(self):
        self.read("猫")
        self.controller.process(lambda text: [])
        self.assertFalse(self.controller.active)
        self.read("猫")
        self.controller.process(lambda text: [text])
        self.popup.set_latest_data.assert_called_with(["猫"])

    def test_search_uses_existing_lookup_without_touching_clipboard(self):
        self.controller.search_requested.emit()
        self.assertTrue(self.controller.search_window.isVisible())
        self.assertLessEqual(self.controller.search_window.height(), 64)
        self.controller.search.setText("食べました")
        with patch.object(QApplication, "clipboard") as clipboard:
            self.controller.search.returnPressed.emit()
            self.controller.process(lambda text: [text])
            clipboard.assert_not_called()
        self.popup.set_latest_data.assert_called_with(["食べました"])
        self.assertFalse(self.controller.search_window.isVisible())

    def test_monitor_is_opt_in_and_deduplicates(self):
        self.assertFalse(self.controller.automatic.isChecked())
        with patch.object(QApplication, "clipboard") as clipboard, \
                patch.object(QApplication, "activeWindow", return_value=None):
            clipboard.return_value.text.return_value = "猫"
            self.controller.changed()
            self.assertFalse(self.controller.active)
            self.controller.automatic.setChecked(True)
            clipboard.return_value.text.return_value = "犬"
            self.controller.changed()
            revision = self.controller.revision
            self.controller.changed()
            self.assertEqual(self.controller.revision, revision)

    def test_selection_uses_lookup_and_suppresses_automatic_copy(self):
        with patch.object(self.controller.selection, "start") as start:
            self.controller.selection_requested.emit()
            start.assert_called_once_with(wait_for_modifiers=True)
        self.controller.automatic.setChecked(True)
        self.controller.selection.pending = True
        with patch.object(QApplication, "clipboard") as clipboard:
            clipboard.return_value.text.return_value = "selected"
            self.controller.changed()
        self.assertFalse(self.controller.active)
        self.controller.selection.completed.emit("selected")
        self.controller.process(lambda text: [text])
        self.popup.set_latest_data.assert_called_with(["selected"])

    def test_shortcuts_opt_in_reconfigure_disable_and_reject_duplicates(self):
        self.assertIsNone(self.controller.keys)
        page = self.controller.settings_page()
        self.assertTrue(all(not field.text() for field in page.shortcuts.values()))
        page.shortcuts["clipboard"].recorder.setKeySequence(QKeySequence("Ctrl+Shift+K"))
        page.shortcuts["clipboard"].enabled.setChecked(True)
        with patch("meikipop.gui.clipboard_lookup.TextHotKeys") as listener:
            self.controller.save_settings_page(page)
            self.assertIn("<ctrl>+<shift>+k", listener.call_args.args[0])
            page.shortcuts["search"].recorder.setKeySequence(QKeySequence("Ctrl+Shift+K"))
            page.shortcuts["search"].enabled.setChecked(True)
            with self.assertRaises(ValueError):
                self.controller.save_settings_page(page)
            self.assertEqual(self.controller.settings.value("search_hotkey"), "")
            page.shortcuts["search"].enabled.setChecked(False)
            page.shortcuts["clipboard"].enabled.setChecked(False)
            self.controller.save_settings_page(page)
            listener.return_value.stop.assert_called_once()
            self.assertIsNone(self.controller.keys)
        page.deleteLater()

    def test_recorded_defaults_and_double_click_opt_in(self):
        from pynput import mouse
        page = self.controller.settings_page()
        self.assertEqual(page.shortcuts["selection"].binding(), "<ctrl>+<alt>+s")
        self.assertFalse(page.double_click.isChecked())
        with patch.object(self.controller.selection, "start") as start:
            for _ in range(2):
                self.controller.on_click(10, 10, mouse.Button.left, True)
                self.controller.on_click(10, 10, mouse.Button.left, False)
            self.assertFalse(self.controller.double_click_timer.isActive())
            self.controller.settings.setValue("double_click", True)
            for _ in range(2):
                self.controller.on_click(10, 10, mouse.Button.left, True)
                self.controller.on_click(10, 10, mouse.Button.left, False)
            self.assertTrue(self.controller.double_click_timer.isActive())
            self.controller.double_click_timer.stop()
            self.controller.capture_double_click()
            start.assert_called_once_with()
        page.deleteLater()
