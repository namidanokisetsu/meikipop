import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QUrl, QPoint, QRect, QSettings
from PyQt6.QtWidgets import QApplication

from meikipop.gui.text_input import ClipboardWindow, run_setup
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
        wordnet_path = patch("meikipop.dictionary.turkish_wordnet.default_wordnet_path", return_value=root / "missing.sqlite3")
        wordnet_path.start()
        self.addCleanup(wordnet_path.stop)
        with patch("pynput.keyboard.GlobalHotKeys"), patch("pynput.keyboard.Listener"), \
                patch("meikipop.gui.text_input.QSettings", return_value=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)):
            self.window = ClipboardWindow(root / "pack/dictionary.sqlite3", "exact")
            self.window.settings.setValue("auto_scan", False)

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

    def test_clipboard_monitor_deduplicates_and_skips_self_copy(self):
        self.window.auto_action.setChecked(True)
        self.window.last_clipboard = "old"
        with patch.object(QApplication, "clipboard") as clipboard, patch.object(QApplication, "activeWindow", return_value=None):
            clipboard.return_value.text.return_value = "kitap"
            self.window.clipboard_changed()
            current = self.window.requests.current
            self.assertTrue(self.window.pinned)
            self.window.clipboard_changed()
            self.assertEqual(self.window.requests.current, current)
            clipboard.return_value.text.return_value = "x" * 2001
            self.window.clipboard_changed()
            self.assertEqual(self.window.requests.current, current)
            with patch.object(QApplication, "activeWindow", return_value=self.window):
                clipboard.return_value.text.return_value = "yaz"
                self.window.clipboard_changed()
                self.assertEqual(self.window.requests.current, current)

    def test_release_rejects_pending_peek_but_click_pin_survives(self):
        self.window.submit("kitap", peek=True)
        self.window.holding = True
        old = self.window.requests.current
        self.window.set_hold(False)
        self.window.deliver(old, None, "stale OCR")
        self.assertFalse(self.window.isVisible())
        self.window.submit("kitap", peek=True)
        self.window.holding = True
        self.window.pin()
        self.window.set_hold(False)
        self.wait_result()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.pinned)

    def test_popup_clamps_to_negative_monitor_coordinates(self):
        with patch.object(QApplication, "screenAt") as screen:
            area = QRect(-1280, -100, 1280, 720)
            screen.return_value.availableGeometry.return_value = area
            for mode in ("visual_novel_mode", "flip_horizontally", "flip_vertically", "flip_both"):
                with patch("meikipop.gui.text_input.config.popup_position_mode", mode):
                    for point in (QPoint(-2, 618), QPoint(-1278, -98)):
                        self.window.place_popup(point)
                        self.assertTrue(area.contains(self.window.geometry()))

    def test_copy_during_scan_invalidates_scan_and_stops_hold(self):
        self.window.submit("kitap", peek=True)
        old = self.window.requests.current
        self.window.scan_busy = True
        self.window.holding = True
        with patch.object(QApplication, "clipboard") as clipboard:
            clipboard.return_value.text.return_value = "yaz"
            self.window.read_clipboard()
        self.window.deliver(old, None, "stale OCR")
        self.wait_result()
        self.assertEqual(self.window.result.text, "yaz")
        self.assertFalse(self.window.holding)
        self.assertFalse(self.window.scan_busy)

    def test_wordnet_only_navigation_and_back(self):
        from meikipop.dictionary.turkish_wordnet import build
        root = Path(self.temp.name)
        source = root / "wordnet.xml"
        source.write_text('<SYNSETS><SYNSET><ID>1</ID><SYNONYM><LITERAL>kitap<SENSE>1</SENSE></LITERAL>'
                          '<LITERAL>betik<SENSE>2</SENSE></LITERAL></SYNONYM><POS>n</POS>'
                          '<DEF>Yazılı eser</DEF></SYNSET></SYNSETS>', encoding="utf-8")
        build(source, root / "missing.sqlite3")
        self.window.submit("kitap")
        self.wait_result()
        self.assertEqual(len(self.window.result.wordnet), 1)
        self.assertNotIn("Yazılı eser", self.window.browser.toPlainText())
        self.window.navigate(QUrl("section:wordnet"))
        self.assertIn("Yazılı eser", self.window.browser.toPlainText())
        self.window.navigate(QUrl("word:betik"))
        self.wait_result()
        self.assertEqual(self.window.result.entries, ())
        self.assertIn("Yazılı eser", self.window.browser.toPlainText())
        self.window.go_back()
        self.wait_result()
        self.assertEqual(self.window.result.text, "kitap")

    def test_corrupt_optional_wordnet_does_not_break_tdk(self):
        with closing(sqlite3.connect(Path(self.temp.name) / "missing.sqlite3")) as db:
            db.execute("CREATE TABLE metadata(key TEXT,value TEXT)")
        self.window.submit("kitap")
        self.wait_result()
        self.assertTrue(self.window.result.entries)
        self.assertIn("WordNet unavailable", self.window.result.wordnet_status)

    def test_pinned_popup_does_not_scan_or_follow_pointer(self):
        self.window.submit("kitap")
        self.wait_result()
        position = self.window.pos()
        with patch("meikipop.gui.text_input.QCursor.pos", return_value=QPoint(700, 500)), \
                patch.object(self.window, "capture_pointer") as capture:
            self.window.set_hold(True)
            self.window.scan_pointer()
            self.app.processEvents()
            capture.assert_not_called()
            self.assertEqual(self.window.pos(), position)
        self.window.navigate(QUrl("more:"))
        self.assertEqual(self.window.pos(), position)

    def test_popup_sizes_to_content_and_scrolls_at_limit(self):
        self.window.settings.setValue("max_height", 200)
        self.window.browser.setPlainText("kitap")
        short_height = self.window.height()
        self.window.browser.setPlainText("definition\n" * 100)
        self.window.show()
        self.app.processEvents()
        self.assertLess(short_height, self.window.height())
        self.assertLessEqual(self.window.height(), 200)
        self.assertGreater(self.window.browser.verticalScrollBar().maximum(), 0)

    def test_setup_releases_database_and_restarts_after_failure(self):
        self.window.submit("kitap")
        self.wait_result()
        old_worker = self.window.worker

        def installer(kind, dictionary, model_dir):
            self.assertFalse(old_worker.is_alive())
            # Windows refuses this while the lookup worker holds the SQLite file.
            moved = dictionary.with_suffix(".moved")
            dictionary.rename(moved)
            moved.rename(dictionary)
            raise RuntimeError("Download unavailable")

        with patch("meikipop.gui.text_input.run_setup", side_effect=installer):
            self.window.start_setup("dictionary")
            deadline = time.monotonic() + 3
            while self.window.setup_thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
        self.assertIsNone(self.window.setup_thread)
        self.assertIn("Download unavailable", self.window.setup_status)
        self.assertIsNot(old_worker, self.window.worker)
        self.window.submit("kitap")
        self.wait_result()
        self.assertTrue(self.window.result.entries)

    def test_console_free_installer_uses_pipes_and_selected_paths(self):
        with patch("meikipop.gui.text_input.sys.executable", "C:/env/pythonw.exe"), \
                patch("meikipop.gui.text_input.subprocess.run") as run:
            run.return_value.returncode = 0
            run_setup("model", Path("custom/dictionary.sqlite3"), Path("custom/models"))
            args = run.call_args.args[0]
            self.assertEqual(Path(args[0]).name, "python.exe")
            self.assertEqual(args[-2:], ["--model-dir", str(Path("custom/models"))])
            self.assertIsNotNone(run.call_args.kwargs["stderr"])
            self.assertIsNotNone(run.call_args.kwargs["stdout"])
            run_setup("dictionary", Path("custom/dictionary.sqlite3"))
            self.assertEqual(run.call_args.args[0][-2:], ["--output", "custom"])

    def test_background_delivery_never_opens_popup(self):
        self.window.background_request = self.window.requests.next()
        self.window.scan_request = self.window.background_request
        self.window.scan_busy = True
        self.window.deliver(self.window.background_request, None, "Local OCR failed")
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.scan_busy)
        self.assertTrue(self.window.prefetch_failed)

    def test_visible_peek_reuses_hit_scan_without_recapture(self):
        from meikipop.pipeline import REUSE_LAST_VALUE
        self.window.submit("kitap", peek=True)
        self.wait_result()
        self.window.move(500, 500)
        self.window.capture_region = QRect(0, 0, 400, 200)
        self.window.holding = True
        text = self.window.browser.toPlainText()
        with patch("meikipop.gui.text_input.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(self.window.worker.queue, "put") as put, \
                patch.object(self.window, "capture_pointer") as capture:
            self.window.scan_pointer()
            self.assertIs(put.call_args.args[0][3][0], REUSE_LAST_VALUE)
            self.assertEqual(self.window.browser.toPlainText(), text)
            capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
