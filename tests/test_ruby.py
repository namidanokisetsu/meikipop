import os
from pathlib import Path
import tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QFont, QImage, QPainter, QTextCursor, QTextDocumentFragment
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

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

    def test_readings_default_to_brackets_with_independent_furigana_options(self):
        definition = {"type": "structured-content", "content": {"tag": "ruby", "content": [
            "食", {"tag": "rt", "content": "た"}, "べ", "物", {"tag": "rt", "content": "べもの"}]}}
        entry = Entry("1", "食べ物", "たべもの", "Fixture", "ja", (definition,))
        result = SearchResult("食べ物", "ja", "en", (entry,))
        self.browser.setHtml(render_result(result))
        self.assertIn("食べ物 [たべもの]", self.browser.toPlainText())
        self.assertIn("食 [た]べ物 [べもの]", self.browser.toPlainText())
        self.assertEqual(self.objects(), [])
        self.browser.setHtml(render_result(result, definition_furigana=True))
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

    def test_frequency_provenance_tooltips_preserve_visible_rank_and_copy(self):
        from meikipop.dictionary.metadata import Frequency
        from PyQt6.QtGui import QTextDocument
        word = Entry("1", "猫", "ねこ", "Words", "ja", ("cat",),
                     frequencies=(Frequency("Corpus <one>", 100, "100"),
                                  Frequency("Corpus <one>", 900, "900㋕"),
                                  Frequency("Corpus two", 400, "400")))
        result = SearchResult("猫", "ja", "en", (word,))
        details = ("Corpus <one>: #100, 900㋕", "Corpus two: #400")
        combined_detail = "Corpus <one>: #100; Corpus <one>: 900㋕; Corpus two: #400"
        for combined in (True, False):
            with self.subTest(combined=combined):
                html = render_result(result, combine_frequencies=combined)
                original = QTextDocument()
                original.setHtml(html)
                self.browser.setHtml(html)
                self.assertEqual(self.browser.toPlainText(), original.toPlainText())
                self.browser.selectAll()
                self.assertEqual(self.browser.createMimeDataFromSelection().text(), original.toPlainText())
                tooltips = []
                block = self.browser.document().begin()
                while block.isValid():
                    iterator = block.begin()
                    while not iterator.atEnd():
                        fmt = iterator.fragment().charFormat()
                        if fmt.toolTip() in (*details, combined_detail):
                            tooltips.append(fmt.toolTip())
                            self.assertFalse(fmt.isAnchor())
                            self.assertEqual(fmt.anchorHref(), "")
                        iterator += 1
                    block = block.next()
                self.assertEqual(tooltips, [combined_detail] if combined else list(details))
                self.assertIn("#160" if combined else "#100/900㋕", self.browser.toPlainText())

    def test_inline_pitch_then_frequency_stay_small_and_wrap_with_headword_ruby(self):
        from meikipop.dictionary.metadata import Frequency
        from meikipop.dictionary.pitch import Pitch, PITCH_OBJECT, PITCH_PREFIX
        word = Entry("1", "祈願", "きがん", "Words", "ja", ("prayer",), inflection=("past",),
                     frequencies=(Frequency("Corpus <one>", 123, "123"),), pitches=(Pitch("NHK", "きがん", 1),))
        result = SearchResult("祈願", "ja", "en", (word,))
        with patch.object(config, "font_size_header", 24), patch.object(config, "font_size_definitions", 14):
            for preview in (False, True):
                for furigana in (False, True):
                    with self.subTest(preview=preview, furigana=furigana):
                        html = render_result(result, preview=preview, headword_furigana=furigana)
                        self.assertLess(html.index(PITCH_PREFIX), html.index("frequency:"))
                        self.assertLess(html.index("frequency:"), html.index("</h2>"))
                        self.browser.setHtml(html)
                        self.assertIn("きがん [1]", self.browser.toPlainText())
                        self.assertNotIn("[きがん]", self.browser.toPlainText())
                        document = self.browser.document()
                        frequency = document.find("#123")
                        heading = frequency.block()
                        self.assertEqual(heading.blockFormat().headingLevel(), 2)
                        self.assertEqual(frequency.charFormat().font().pixelSize(), 13)
                        self.assertEqual(frequency.charFormat().toolTip(), "Corpus <one>: #123")
                        self.assertNotEqual(document.find("past").block().position(), heading.position())
                        iterator = heading.begin()
                        pitch_sizes = []
                        while not iterator.atEnd():
                            fmt = iterator.fragment().charFormat()
                            if fmt.objectType() == PITCH_OBJECT:
                                pitch_sizes.append(fmt.font().pixelSize())
                            iterator += 1
                        self.assertEqual(pitch_sizes, [13])
                        if furigana:
                            self.assertEqual(self.objects()[0].charFormat().font().pixelSize(), 24)
                        self.browser.setLineWrapMode(self.browser.LineWrapMode.FixedPixelWidth)
                        for width in (120, 320):
                            self.browser.setLineWrapColumnOrWidth(width)
                            document.documentLayout().documentSize()
                            layout = heading.layout()
                            self.assertGreater(layout.lineCount(), 0)
                            self.assertTrue(all(layout.lineAt(line).naturalTextWidth() <= width
                                                for line in range(layout.lineCount())))

    def test_bracketed_reading_remains_when_inline_pitch_does_not_supply_it(self):
        from meikipop.dictionary.pitch import Pitch
        word = Entry("1", "猫", "ねこ", "Words", "ja", ("cat",), pitches=(Pitch("NHK", "ねこ", 1),))
        self.browser.setHtml(render_result(SearchResult("猫", "ja", "en", (word,)), preview=True, preview_pitch=False))
        self.assertIn("猫 [ねこ]", self.browser.toPlainText())
        alternate = Entry("2", "猫", "ねこ", "Words", "ja", ("cat",), pitches=(Pitch("Other", "ネコ", 1),))
        self.browser.setHtml(render_result(SearchResult("猫", "ja", "en", (alternate,))))
        self.assertIn("猫 [ねこ]", self.browser.toPlainText())

    def test_headword_ruby_links_each_kanji_and_preserves_reading_and_copy(self):
        self.browser.setHtml('<h2>' + ruby_html("祈願", "きがん", kanji="祈願") + '</h2>')
        self.browser.show()
        self.app.processEvents()
        points = {}
        for y in range(65):
            for x in range(100):
                character = self.browser._ruby_kanji_at(QPoint(x, y))
                if character:
                    points.setdefault(character, QPoint(x, y))
        self.assertEqual(set(points), set("祈願"))
        clicks, lookups = [], []
        self.browser.anchorClicked.connect(lambda url: clicks.append(url.path()))
        self.browser.word_selected.connect(lookups.append)
        for character, point in points.items():
            QTest.mouseClick(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(clicks, list(points))
        self.assertEqual(lookups, [])
        self.assertEqual(self.objects()[0].charFormat().property(READING), "きがん")
        self.browser.selectAll()
        self.assertEqual(self.browser.createMimeDataFromSelection().text(), "祈願")

    def test_pitch_objects_preserve_original_reading_for_copy_and_lookup(self):
        from meikipop.dictionary.pitch import Pitch, PITCH_OBJECT, render_pitches
        html = render_pitches((Pitch("NHK", "きがん", 1, nasal=(2,)),))
        self.browser.setHtml(html)
        self.browser.show()
        self.app.processEvents()
        cursor = QTextCursor(self.browser.document())
        cursor.select(QTextCursor.SelectionType.Document)
        self.browser.setTextCursor(cursor)
        self.assertEqual(self.browser.createMimeDataFromSelection().text(), "きがん [1]")
        fragment = self.browser.document().begin().begin().fragment()
        self.assertEqual(fragment.charFormat().objectType(), PITCH_OBJECT)
        cursor.setPosition(fragment.position())
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        self.browser.setTextCursor(cursor)
        selected=[]
        self.browser.word_selected.connect(selected.append)
        self.browser.lookup_selection()
        self.assertEqual(selected,["きがん"])
        self.assertFalse(self.browser.grab().isNull())

    def test_table_breaks_and_spaces_copy_like_qt_with_inline_annotations(self):
        from meikipop.dictionary.pitch import Pitch, render_pitches
        self.browser.setHtml('<table><tr><td>𠮷 ' + ruby_html("食べ物", "たべもの")
                             + '<br>first&nbsp;sense</td><td>second sense</td></tr></table>'
                             + render_pitches((Pitch("NHK", "きがん", 1, nasal=(2,)),)))
        self.browser.selectAll()
        expected = (QTextDocumentFragment(self.browser.textCursor()).toPlainText()
                    .replace("\ufffc", "食べ物", 1).replace("\ufffc", "きがん [1]", 1))
        self.assertEqual(self.browser.toPlainText(), expected)
        self.assertEqual(self.browser.createMimeDataFromSelection().text(), expected)
        self.assertNotIn("\ufdd0", expected)
        self.assertIn("first sense", expected)

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

    def test_many_annotations_batch_document_changes_and_keep_copy_text(self):
        changes = []
        self.browser.document().contentsChanged.connect(lambda: changes.append(True))
        self.browser.setHtml("".join(ruby_html("猫", "ねこ") for _ in range(100)))
        self.assertLessEqual(len(changes), 3)
        self.assertEqual(sum(fragment.length() for fragment in self.objects()), 100)
        self.assertTrue(all(fragment.charFormat().property(READING) == "ねこ" for fragment in self.objects()))
        self.browser.selectAll()
        self.assertEqual(self.browser.createMimeDataFromSelection().text(), "猫" * 100)

    def test_long_ruby_document_lays_out_the_last_paragraph(self):
        self.browser.show()
        self.app.processEvents()
        self.browser.setHtml("Previous short definition")
        self.app.processEvents()
        image = QImage(200, 300, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.browser.library_root = Path(directory.name)
        assets = self.browser.library_root / ("ja-" + "a" * 64 + ".assets")
        assets.mkdir()
        image.save(str(assets / ("b" * 64 + ".png")))
        image_html = '<img src="meikipop-image:/ja-' + "a" * 64 + "/" + "b" * 64 + '.png" width="200" height="300">'
        paragraph = "説明 " + ("これは " + ruby_html("食べ物", "たべもの") + " の読みです。") * 5
        self.browser.setHtml('<style>h2 {font-size:18px}</style><h2>Headword</h2><div><div>'
                             + paragraph + image_html + paragraph + '</div>'
                             + "".join(f'<div style="margin-top:1px;margin-bottom:1px">{index} {paragraph}</div>'
                                       for index in range(80)) + '<div>' + image_html + '</div></div>')
        self.app.processEvents()
        document = self.browser.document()
        height = document.size().height()
        last = document.lastBlock()
        bounds = document.documentLayout().blockBoundingRect(last)
        self.assertGreater(last.layout().lineCount(), 0)
        self.assertGreater(bounds.height(), 0)
        self.assertGreater(bounds.bottom(), height - 10)
        self.assertEqual(sum(fragment.length() for fragment in self.objects()), 410)
        self.assertIn("79 説明 " + ("これは 食べ物 の読みです。") * 5, self.browser.toPlainText())
