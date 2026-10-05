import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QPoint, QRectF
from PyQt6.QtGui import QFont, QImage, QPainter, QTextCursor
from PyQt6.QtWidgets import QApplication

from meikipop.dictionary.library import Entry
from meikipop.dictionary.search import SearchResult
from meikipop.gui.quick_lookup import LocalDictionaryBrowser, render_result
from meikipop.gui.ruby import BASE, READING, RUBY, ruby_html
from meikipop.config.config import config
from unittest.mock import patch


class RubyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser()
        self.browser.resize(300, 200)

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()

    def objects(self):
        result = []
        block = self.browser.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.charFormat().objectType() == RUBY:
                    result.append(fragment)
                iterator += 1
            block = block.next()
        return result

    def test_definitions_use_paired_ruby_and_headword_defaults_to_brackets(self):
        definition = {"type": "structured-content", "content": {"tag": "ruby", "content": [
            "食", {"tag": "rt", "content": "た"}, "べ", "物", {"tag": "rt", "content": "べもの"}]}}
        entry = Entry("1", "食べ物", "たべもの", "Fixture", "ja", (definition,))
        result = SearchResult("食べ物", "ja", "en", (entry,))
        self.browser.setHtml(render_result(result))
        self.assertIn("食べ物 [たべもの]", self.browser.toPlainText())
        self.assertEqual([(f.charFormat().property(BASE), f.charFormat().property(READING))
                          for f in self.objects()], [("食", "た"), ("べ物", "べもの")])
        self.browser.setHtml(render_result(result, headword_furigana=True))
        self.assertNotIn("[たべもの]", self.browser.toPlainText())
        self.assertEqual(self.objects()[0].charFormat().property(READING), "たべもの")

    def test_copy_and_nested_lookup_keep_original_text_including_astral_kanji(self):
        self.browser.setHtml("𠮷 " + ruby_html("食べ物", "たべもの") + " &amp; " + ruby_html("猫", "ねこ"))
        self.browser.selectAll()
        expected = "𠮷 食べ物 & 猫"
        self.assertEqual(self.browser.toPlainText(), expected)
        self.assertEqual(self.browser.selected_text(), expected)
        self.assertEqual(self.browser.createMimeDataFromSelection().text(), expected)
        fragment = self.objects()[0]
        cursor = QTextCursor(self.browser.document())
        cursor.setPosition(fragment.position())
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        self.browser.setTextCursor(cursor)
        selected = []
        self.browser.word_selected.connect(selected.append)
        self.browser.lookup_selection()
        self.assertEqual(selected, ["食べ物"])
        cursor.clearSelection()
        self.browser.setTextCursor(cursor)
        self.browser.show()
        self.app.processEvents()
        self.assertFalse(self.browser.grab().isNull())
        hits = {self.browser.text_at(QPoint(x, y)) for x in range(0, 150, 3) for y in range(0, 40, 3)}
        self.assertIn("食べ物", hits)

    def test_reading_is_centered_above_base_and_reserves_line_height(self):
        self.browser.setHtml('<span style="font-size:24px">' + ruby_html("生", "せい") + '</span>')
        fmt = self.objects()[0].charFormat()
        renderer = self.browser._ruby_object
        document = self.browser.document()
        font, small, base, reading = renderer.metrics(document, fmt)
        size = renderer.intrinsicSize(document, 0, fmt)
        self.assertGreater(size.height(), -base.tightBoundingRect("生").top())
        self.assertGreaterEqual(size.width(), reading.horizontalAdvance("せい"))
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.setFont(small)
        painter.setFont(font)
        self.assertEqual(painter.font().pixelSize(), 24)
        renderer.drawObject(painter, QRectF(0, 0, size.width(), size.height()), document, 0, fmt)
        painter.end()
        reading_bottom = int(reading.tightBoundingRect("せい").height())
        for top, bottom in ((0, reading_bottom), (reading_bottom + 1, int(size.height()) + 5)):
            self.assertTrue(any(image.pixelColor(x, y).alpha() for x in range(100) for y in range(top, bottom)))

    def test_ruby_preserves_inherited_family_and_configurable_size_on_painter(self):
        font = QFont("Noto Sans JP Medium")
        font.setPixelSize(24)
        self.browser.setFont(font)
        self.browser.setHtml(ruby_html("猫", "ねこ"))
        fmt = self.objects()[0].charFormat()
        with patch.object(config, "furigana_scale", 60, create=True):
            base, small, _, _ = self.browser._ruby_object.metrics(self.browser.document(), fmt)
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            painter.setFont(QFont("Arial"))
            painter.setFont(small)
            self.assertEqual(painter.font().families(), font.families())
            self.assertEqual(painter.font().pixelSize(), 14)
            painter.setFont(base)
            self.assertEqual(painter.font().families(), font.families())
            self.assertEqual(painter.font().pixelSize(), 24)
        finally:
            painter.end()

    def test_plain_text_and_html_like_readings_remain_literal(self):
        self.browser.setHtml(ruby_html("&lt;猫&gt;", "&lt;ねこ&gt;"))
        self.assertEqual(self.browser.toPlainText(), "<猫>")
        self.assertEqual(self.objects()[0].charFormat().property(READING), "<ねこ>")
        self.browser.setHtml("normal definition")
        self.assertEqual(self.browser.toPlainText(), "normal definition")
        self.assertFalse(self.objects())

    def test_adjacent_identical_readings_keep_separate_annotations(self):
        self.browser.setHtml(ruby_html("日", "ひ") + ruby_html("日", "ひ"))
        self.assertEqual(sum(f.length() for f in self.objects()), 2)
        self.assertTrue(all(f.charFormat().property(BASE) == "日" for f in self.objects()))
        self.assertEqual(self.browser.toPlainText(), "日日")
