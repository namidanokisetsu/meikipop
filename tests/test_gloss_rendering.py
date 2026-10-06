import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PyQt6.QtGui import QTextCursor, QTextTable
from PyQt6.QtWidgets import QApplication

from meikipop.config.config import config
from meikipop.dictionary.library import Entry
from meikipop.dictionary.search import SearchResult
from meikipop.gui.popup_style import surface_colors
from meikipop.gui.quick_lookup import LocalDictionaryBrowser, render_result


class GlossRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def render(self, nodes):
        definition = {"type": "structured-content", "content": nodes}
        entry = Entry("fixture", "word", "", "Fixture", "en", (definition,))
        return render_result(SearchResult("word", "en", "en", (entry,)), {"Fixture"})

    def test_forms_cells_have_visible_status_and_theme_borders(self):
        table = {"tag": "table", "content": [
            {"tag": "tr", "content": [{"tag": "th", "content": label}
                                       for label in ("", "憂鬱", "幽鬱")]},
            {"tag": "tr", "content": [
                {"tag": "th", "content": "ゆううつ"},
                {"tag": "td", "data": {"class": "form-pri"},
                 "content": {"tag": "span", "title": "high priority form"}},
                {"tag": "td", "data": {"class": "form-rare"},
                 "content": {"tag": "span", "title": "rarely used form"}}]}]}
        browser = LocalDictionaryBrowser()
        try:
            for bg, fg in (("#000000", "#ffffff"), ("#ffffff", "#000000")):
                with self.subTest(background=bg), patch.object(config, "color_background", bg), \
                        patch.object(config, "color_foreground", fg):
                    browser.setHtml(self.render(table))
                    rendered = next(frame for frame in browser.document().rootFrame().childFrames()
                                    if isinstance(frame, QTextTable))
                    self.assertEqual((rendered.rows(), rendered.columns()), (2, 3))
                    for column, label in ((1, "common"), (2, "rare")):
                        cell = rendered.cellAt(1, column)
                        cursor = cell.firstCursorPosition()
                        cursor.setPosition(cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
                        self.assertEqual(cursor.selectedText(), label)
                        fmt = cell.format().toTableCellFormat()
                        self.assertGreater(fmt.topBorder(), 0)
                        self.assertEqual(fmt.topBorderBrush().color().name(), surface_colors(bg, fg)["border"])
        finally:
            browser.deleteLater()

    def test_wiktionary_labels_emphasis_and_line_breaks(self):
        html = self.render([
            {"tag": "div", "data": {"content": "tags"}, "content": [
                {"tag": "span", "data": {"content": "tag", "category": "topic"}, "content": "sports"},
                {"tag": "span", "data": {"content": "tag", "category": "usage"}, "content": "rare"}]},
            "A definition.", {"tag": "span", "data": {"content": "bold-text"}, "content": "example"},
            {"tag": "i", "content": "italic"}, {"tag": "sup", "content": "2"}, "line one\nline two"])
        self.assertIn("[sports]", html)
        self.assertIn("[rare]", html)
        self.assertIn('font-weight:bold', html)
        self.assertIn("<i>italic</i>", html)
        self.assertIn("<sup>2</sup>", html)
        self.assertIn("line one<br>line two", html)

    def test_table_spans_are_preserved_without_attribute_injection(self):
        html = self.render({"tag": "table", "content": {"tag": "tr", "content": [
            {"tag": "td", "colSpan": 2, "rowSpan": 3, "content": "merged"},
            {"tag": "td", "colSpan": '\" onclick=\"bad', "rowSpan": -1, "content": "safe"}]}})
        self.assertIn('colspan="2" rowspan="3"', html)
        self.assertNotIn("onclick", html)
        self.assertNotIn('rowspan="-1"', html)
