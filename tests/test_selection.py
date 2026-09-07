import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QMimeData
from PyQt6.QtWidgets import QApplication
from meikipop.gui.selection import SelectionCapture


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.capture = SelectionCapture()
        self.capture.user32 = Mock()
        self.capture.user32.GetAsyncKeyState.return_value = 0
        self.capture.user32.GetForegroundWindow.return_value = 123
        self.capture.user32.GetClipboardSequenceNumber.return_value = 10
        self.values = []
        self.capture.completed.connect(self.values.append)

    def tearDown(self):
        self.capture.cancel()

    def test_selection_restores_rich_clipboard_and_timeout_rejects_old_text(self):
        mime = QMimeData()
        mime.setText("old clipboard")
        mime.setHtml("<b>old clipboard</b>")
        with patch("meikipop.gui.selection.sys.platform", "win32"), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch.object(QApplication, "clipboard") as clipboard, patch("pynput.keyboard.Controller"):
            clipboard.return_value.mimeData.return_value = mime
            self.capture.start()
            self.capture.deadline = 0
            self.capture.poll()
            self.assertEqual(self.values, [])
            clipboard.return_value.setMimeData.assert_not_called()
            self.capture.start()
            clipboard.return_value.text.return_value = "kitap"
            self.capture.user32.GetClipboardSequenceNumber.return_value = 11
            self.capture.poll()
            restored = clipboard.return_value.setMimeData.call_args.args[0]
            self.assertEqual(restored.html(), "<b>old clipboard</b>")
            self.assertEqual(self.values, ["kitap"])

    def test_shortcut_waits_for_modifiers_and_cancels_on_focus_change(self):
        with patch("meikipop.gui.selection.sys.platform", "win32"), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("pynput.keyboard.Controller") as controller:
            self.capture.user32.GetAsyncKeyState.return_value = 0x8000
            self.capture.start(wait_for_modifiers=True)
            self.capture.poll()
            controller.assert_not_called()
            self.capture.user32.GetAsyncKeyState.return_value = 0
            self.capture.poll()
            controller.return_value.press.assert_called()
            self.capture.cancel()
            controller.reset_mock()
            self.capture.start(wait_for_modifiers=True)
            self.capture.user32.GetForegroundWindow.return_value = 456
            self.capture.poll()
            controller.assert_not_called()
            self.assertFalse(self.capture.pending)
