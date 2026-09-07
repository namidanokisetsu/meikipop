import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QMimeData
from PyQt6.QtWidgets import QApplication
from meikipop.gui.turkish.selection import SelectionCapture
from meikipop.gui.turkish.desktop_input import DesktopInput


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
        with patch("meikipop.gui.turkish.selection.sys.platform", "win32"), \
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

    def test_escape_is_suppressed_only_for_visible_popup_including_key_up(self):
        with patch("pynput.keyboard.Listener"), patch("pynput.keyboard.GlobalHotKeys"), patch("pynput.mouse.Listener"):
            inputs = DesktopInput("shift,middle", "<ctrl>+<alt>+l", "<ctrl>+<alt>+d", 400)
        try:
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            inputs.keys.suppress_event.assert_not_called()
            inputs.visible.set()
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            inputs.visible.clear()
            inputs.filter_key(0x101, SimpleNamespace(vkCode=27))
            self.assertEqual(inputs.keys.suppress_event.call_count, 2)
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            self.assertEqual(inputs.keys.suppress_event.call_count, 2)
        finally:
            inputs.shutdown()
