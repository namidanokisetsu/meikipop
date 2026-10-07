import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from meikipop.dictionary.library import Entry
from meikipop.dictionary.search import SearchResult
from meikipop.gui.quick_lookup import LocalDictionaryBrowser, render_result


class DictionaryControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser(selection_lookup=True)
        self.browser.setOpenLinks(False)
        self.browser.resize(300, 180)
        self.browser.show()
        self.lookups = []
        self.browser.word_selected.connect(self.lookups.append)

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()

    def point(self, text):
        cursor = self.browser.document().find(text)
        self.assertFalse(cursor.isNull())
        start = cursor.selectionStart()
        cursor.setPosition(start)
        left = self.browser.cursorRect(cursor).center()
        cursor.setPosition(start + 1)
        right = self.browser.cursorRect(cursor).center()
        return QPoint((left.x() + right.x()) // 2, left.y())

    def test_scrolling_an_expansion_link_never_looks_up_its_plus(self):
        self.browser.setHtml('<a name="top"></a>' + '<p>Definition</p>' * 30
                             + '<p><a href="expand:0">+</a></p>')
        self.app.processEvents()
        self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().maximum())
        point = self.point("+")
        self.assertEqual(self.browser.anchorAt(point), "expand:0")
        clicked = []
        self.browser.anchorClicked.connect(clicked.append)
        self.browser.anchorClicked.connect(lambda _: self.browser.scrollToAnchor("top"))
        QTest.mouseClick(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(len(clicked), 1)
        self.assertLessEqual(self.browser.verticalScrollBar().value(), self.browser.document().documentMargin())
        self.assertEqual(self.lookups, [])

    def test_expansion_and_collapse_keep_the_same_word_without_lookup(self):
        entry = Entry("fixture", "terakki", "", "Wiktionary", "tr", ("progress", "growth", "advance", "development"))
        result = SearchResult("terakki", "tr", "en", (entry,))
        expanded = set()

        def render():
            self.browser.setHtml(render_result(result, expanded))

        def toggle(_):
            expanded.symmetric_difference_update((entry.source,))
            render()

        self.browser.anchorClicked.connect(toggle)
        render()
        self.app.processEvents()
        self.assertNotIn("development", self.browser.toPlainText())
        for symbol, expected in (("+", True), ("−", False)):
            self.browser.verticalScrollBar().setValue(0)
            cursor = self.browser.document().find(symbol)
            cursor.setPosition(cursor.selectionStart())
            point = self.browser.cursorRect(cursor).center()
            self.assertEqual(self.browser.anchorAt(point), "expand:0")
            QTest.mouseClick(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual("development" in self.browser.toPlainText(), expected)
            self.assertIn("terakki", self.browser.toPlainText())
        self.assertEqual(self.lookups, [])

    def test_double_clicking_definition_text_still_looks_it_up_once(self):
        self.browser.setHtml("<p>progress</p>")
        self.app.processEvents()
        point = self.point("progress")
        QTest.mouseDClick(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(self.lookups, ["progress"])
