import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QSettings, QUrl
from PyQt6.QtWidgets import QApplication

from meikipop.dictionary.library import Entry
from meikipop.dictionary.search import SearchResult
from meikipop.gui.quick_lookup import QuickLookupWindow


def _entry(source, definitions):
    return Entry(f"{source}:fixture", "fixture", "", source, "ja", tuple(definitions))


class DictionaryCollapseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.model_status_patch = patch("meikipop.language.stanza_analyzer.model_status", return_value="Model needed")
        self.model_status_patch.start()
        self.window = QuickLookupWindow(self.temp.name, lambda: None, self.settings)

    def tearDown(self):
        self.window.shutdown()
        self.window.worker._thread.join(timeout=2)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.model_status_patch.stop()
        self.temp.cleanup()

    def test_pinned_middle_school_dictionary_minus_reduces_content(self):
        self.window.settings.setValue("profiles/ja/expanded_dictionaries", ["Middle-school monolingual"])
        definitions = tuple(f"Meaning {index}: " + "x" * 120 for index in range(4))
        result = SearchResult("fixture", "ja", "en", (_entry("Middle-school monolingual", definitions),))

        self.window.set_compact_preview(False)
        self.window.show_entries(result.entries, result.text, peek=True)
        self.window.pin.setChecked(True)
        self.app.processEvents()

        expanded_text = self.window.browser.toPlainText()
        self.assertIn("Meaning 3", expanded_text)
        self.assertIn("−", self.window.browser.toHtml())

        self.window._link(QUrl("expand:0"))
        self.app.processEvents()
        collapsed_text = self.window.browser.toPlainText()
        self.assertNotIn("Meaning 3", collapsed_text)
        self.assertLess(len(collapsed_text), len(expanded_text))
        self.assertIn("+", self.window.browser.toHtml())


if __name__ == "__main__":
    unittest.main()
