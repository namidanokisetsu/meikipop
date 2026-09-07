import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings, QRect
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
        with patch("meikipop.gui.clipboard_lookup.keyboard.GlobalHotKeys"), \
                patch("meikipop.gui.clipboard_lookup.mouse.Listener"), \
                patch("meikipop.gui.clipboard_lookup.QSettings", return_value=QSettings(
                    str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)):
            self.controller = ClipboardLookup(self.shared, self.popup, self.tray)

    def tearDown(self):
        self.controller.shutdown()
        self.popup.deleteLater()
        self.temp.cleanup()

    def read(self, text):
        with patch.object(QApplication, "clipboard") as clipboard:
            clipboard.return_value.text.return_value = text
            self.controller.read()

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
