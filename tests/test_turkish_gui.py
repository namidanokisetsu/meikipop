import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

from meikipop.gui.text_input import ClipboardWindow
from meikipop.scripts.build_turkish_dictionary import build


class ClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        with closing(sqlite3.connect(root / "source.db")) as db:
            db.executescript((Path(__file__).parent / "fixtures/turkish.sql").read_text(encoding="utf-8"))
        build(root / "source.db", root / "pack")
        with patch("pynput.keyboard.GlobalHotKeys"):
            self.window = ClipboardWindow(root / "pack/dictionary.sqlite3", "exact")

    def tearDown(self):
        self.window.shutdown()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_result(self):
        deadline = time.monotonic() + 3
        while self.window.result is None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNotNone(self.window.result)

    def test_clipboard_button_repeats_and_window_stays_visible(self):
        with patch.object(QApplication, "clipboard") as clipboard:
            clipboard.return_value.text.return_value = "kitap"
            self.window.read_clipboard()
            self.wait_result()
            first = self.window.requests.current
            self.window.read_clipboard()
            self.wait_result()
        self.assertGreater(self.window.requests.current, first)
        self.assertTrue(self.window.isVisible())
        self.assertIn("Bir eser", self.window.browser.toPlainText())

    def test_newer_request_and_dismissal_reject_old_delivery(self):
        self.window.submit("kitap")
        old_id = self.window.requests.current
        self.wait_result()
        old_result = self.window.result
        self.window.submit("yaz")
        self.window.deliver(old_id, old_result, "")
        self.assertIsNone(self.window.result)
        self.wait_result()
        self.assertEqual(self.window.result.text, "yaz")
        current = self.window.requests.current
        self.window.close()
        self.window.deliver(current, old_result, "")
        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.isVisible())

    def test_token_and_related_navigation(self):
        self.window.submit("kitap yaz")
        self.wait_result()
        self.window.navigate(QUrl("token:1"))
        self.wait_result()
        self.assertEqual(self.window.result.target, 1)
        self.assertEqual(len(self.window.result.entries), 2)
        self.window.submit("kitap")
        self.wait_result()
        self.window.navigate(QUrl("related:tdk:1:1"))
        self.wait_result()
        self.assertEqual(self.window.result.text, "kitap kurdu")

    def test_oversized_input_invalidates_pending_lookup(self):
        self.window.submit("kitap")
        old = self.window.requests.current
        self.window.submit("x" * 2001)
        self.window.deliver(old, None, "stale failure")
        self.assertIn("2,000", self.window.browser.toPlainText())

    def test_suggestion_navigation(self):
        self.window.submit("cocugu")
        self.wait_result()
        self.assertEqual(self.window.result.text, "cocugu")
        self.assertIn("Did you mean?", self.window.browser.toPlainText())
        index = next(i for i, s in enumerate(self.window.result.suggestions) if s.headword == "çocuk")
        self.window.navigate(QUrl(f"suggestion:{index}"))
        self.wait_result()
        self.assertEqual(self.window.result.entries[0]["headword"], "çocuk")


if __name__ == "__main__":
    unittest.main()
