import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from meikipop.dictionary.library import Entry
from meikipop.dictionary.kanji import KanjiEntry
from meikipop.dictionary.search import SearchResult
from meikipop.gui.quick_lookup import LocalDictionaryBrowser, render_result


class SectionScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser(selection_lookup=False)
        self.browser.resize(320, 180)
        self.browser.show()
        self.scroller = self.browser.section_scroll
        self.bar = self.browser.verticalScrollBar()
        self.render()

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()

    def render(self, lines=1):
        entries = tuple(Entry(str(index), "word", "", f"Source {index}", "en",
                              ("\n".join(f"Definition {line}" for line in range(lines)),))
                        for index in range(8))
        self.result = SearchResult("word", "en", "ja", entries)
        self.browser.setHtml(render_result(self.result, expanded=tuple(e.source for e in entries)))
        self.app.processEvents()

    def wheel(self, angle=-120, pixel=0, phase=Qt.ScrollPhase.NoScrollPhase,
              modifiers=Qt.KeyboardModifier.NoModifier, horizontal=0):
        point = self.browser.viewport().rect().center()
        event = QWheelEvent(QPointF(point), QPointF(self.browser.viewport().mapToGlobal(point)),
                            QPoint(horizontal, pixel), QPoint(horizontal, angle),
                            Qt.MouseButton.NoButton, modifiers, phase, False)
        self.app.sendEvent(self.browser.viewport(), event)
        return event

    def test_progress_uses_equal_sections_and_interpolates_long_sections(self):
        value = SearchResult("word", "en", "ja", tuple(
            Entry(str(i), "word", "", f"Source {i}", "en", ("line\n" * lines,))
            for i, lines in enumerate((3, 20, 14))))
        self.browser.setHtml(render_result(value, expanded=tuple(e.source for e in value.entries)))
        self.app.processEvents()
        scroller = self.browser.section_scroll
        scroller.set_enabled(True)
        self.app.processEvents()
        bar = self.browser.verticalScrollBar()
        self.assertTrue(scroller.progress.isVisible())
        self.assertEqual(self.browser.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        starts = [max(0, top - scroller.header.height()) for top in scroller.section_tops()]
        for i, start in enumerate(starts):
            bar.setValue(start)
            self.assertAlmostEqual(scroller.progress_fraction(), i / 3)
        bar.setValue(round((starts[1] + starts[2]) / 2))
        self.assertAlmostEqual(scroller.progress_fraction(), .5, places=2)
        bar.setValue(bar.maximum())
        self.assertEqual(scroller.progress.value(), 1000)
        self.browser.resize(340, 190)
        self.app.processEvents()
        self.assertGreater(scroller.progress.x(), self.browser.viewport().geometry().right())
        self.browser.setHtml("Short")
        self.app.processEvents()
        self.assertFalse(scroller.progress.isVisible())
        scroller.set_enabled(False)
        self.assertEqual(self.browser.viewportMargins().right(), 0)
        self.assertEqual(self.browser.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def test_dragging_progress_jumps_between_stops_and_preserves_selection(self):
        self.render(lines=20)
        self.scroller.set_enabled(True)
        self.app.processEvents()
        self.browser.setTextCursor(self.browser.document().find("Definition"))
        selected = self.browser.selected_text()
        progress = self.scroller.progress
        QTest.mousePress(progress, Qt.MouseButton.LeftButton, pos=QPoint(progress.width() // 2, 0))
        values = []
        for fraction in (.25, .5, .75, 1, .5, 0):
            point = QPoint(progress.width() // 2, round((progress.height() - 1) * fraction))
            QTest.mouseMove(progress, point)
            values.append(self.bar.value())
            self.assertIn(self.bar.value(), self.scroller.stops())
            self.assertIsNone(self.scroller._target)
        QTest.mouseRelease(progress, Qt.MouseButton.LeftButton, pos=QPoint(progress.width() // 2, 0))
        self.assertFalse(progress.isSliderDown())
        self.assertEqual(values[3], self.bar.maximum())
        self.assertEqual(values[-1], 0)
        self.assertEqual(values[:4], sorted(values[:4]))
        self.assertGreater(len(set(values)), 3)
        self.assertEqual(self.browser.selected_text(), selected)

    def test_default_uses_normal_wheel_scrolling(self):
        self.assertFalse(self.scroller.enabled)
        self.wheel()
        self.assertGreater(self.bar.value(), 0)
        self.assertNotEqual(self.bar.value(), self.scroller.stops()[1])

    def test_sentence_and_first_definition_share_the_first_page(self):
        entries = (Entry("would", "would", "", "English", "en", ("past tense of will",)),
                   Entry("will", "will", "", "English", "en", ("expressing intention",)))
        html = render_result(SearchResult("would", "en", "ru", entries),
                             source_text="I would like to know.", show_source=True)
        self.assertNotIn("<hr>", html)
        self.browser.resize(400, 360)
        self.browser.setHtml(html)
        self.app.processEvents()
        self.scroller.set_enabled(True)
        self.app.processEvents()
        definition = self.browser.document().find("past tense of will")
        bottom = self.browser.cursorRect(definition).bottom()
        self.assertGreater(self.browser.viewport().mask().boundingRect().height(), bottom)
        self.assertEqual(self.scroller.boundaries()[0][0], 0)
        self.assertFalse(self.scroller.header.isVisible())
        second = self.scroller.boundaries()[1][0]
        self.wheel(angle=0, pixel=-10, phase=Qt.ScrollPhase.ScrollUpdate)
        self.assertEqual(self.bar.value(), second)
        self.assertFalse(self.scroller.header.isVisible())

    def test_replacing_result_hides_previous_sticky_header_immediately(self):
        self.render(lines=20)
        self.scroller.set_enabled(True)
        self.bar.setValue(80)
        self.assertTrue(self.scroller.header.isVisible())
        self.browser.setHtml("New result")
        self.assertFalse(self.scroller.header.isVisible())
        self.app.processEvents()
        self.assertFalse(self.scroller.header.isVisible())

    def test_first_sticky_baseline_matches_heading_at_viewport_top(self):
        from PyQt6.QtGui import QTextCursor
        for ruby in (False, True):
            with self.subTest(ruby=ruby):
                value = SearchResult("猫", "ja", "en", (
                    Entry("cat", "猫", "ねこ", "Source", "ja", ("line\n" * 30,)),))
                self.browser.setHtml(render_result(value, expanded=("Source",), headword_furigana=ruby))
                self.app.processEvents()
                self.scroller.set_enabled(True)
                self.scroller._refresh_header()
                source = self.browser.document().findBlock(self.scroller._headings[0])
                self.bar.setValue(self.scroller._top(source.position()))
                self.app.processEvents()
                baseline = self.browser.cursorRect(QTextCursor(source)).top() + source.layout().lineAt(0).ascent()
                self.bar.setValue(self.bar.value() + 1)
                self.app.processEvents()
                header = self.scroller.header
                sticky = header.document().begin()
                copied = header.cursorRect(QTextCursor(sticky)).top() + sticky.layout().lineAt(0).ascent()
                self.assertTrue(header.isVisible())
                self.assertAlmostEqual(copied, baseline, delta=1)
                self.assertEqual(header.y(), 0)

    def test_initial_and_scrolled_entries_align_all_rows_without_document_padding(self):
        entries = tuple(Entry(str(i), term, "", "Source", "en", (f"meaning {i}",))
                        for i, term in enumerate(("first", "second")))
        self.browser.setHtml(render_result(SearchResult("first", "en", "ja", entries)))
        self.app.processEvents()
        self.scroller.set_enabled(True)
        self.app.processEvents()
        def positions(word, definition):
            points = []
            for text in (word, definition):
                cursor = self.browser.document().find(text)
                cursor.setPosition(cursor.selectionStart())
                points.append(self.browser.cursorRect(cursor).topLeft())
            return points
        initial = positions("first", "meaning 0")
        self.assertEqual(initial[0].x(), 0)
        self.assertEqual(initial[0].y(), 0)
        self.bar.setValue(self.scroller.boundaries()[1][0])
        self.assertEqual(positions("second", "meaning 1"), initial)
        self.assertEqual(self.browser.document().documentMargin(), 0)
        self.assertEqual(self.scroller.header.document().documentMargin(), 0)

    def test_sticky_heading_does_not_copy_preceding_rule_or_paragraph(self):
        from PyQt6.QtGui import QTextFormat
        self.browser.setHtml('<p>Sentence</p><hr><h2><a name="scroll-headword-0"></a>'
                             '<a name="scroll-section-0"></a>would</h2><p>' + "definition<br>" * 30 + '</p>')
        self.app.processEvents()
        self.scroller.set_enabled(True)
        self.bar.setValue(120)
        self.assertTrue(self.scroller.header.isVisible())
        self.assertEqual(self.scroller.header.toPlainText(), "would")
        block = self.scroller.header.document().begin()
        self.assertFalse(block.blockFormat().hasProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth))

    def test_normal_mode_arrows_scroll_without_moving_the_text_selection(self):
        self.browser.setTextCursor(self.browser.document().find("Definition"))
        selected = self.browser.selected_text()
        QTest.keyClick(self.browser, Qt.Key.Key_Down)
        self.assertGreater(self.bar.value(), 0)
        self.assertEqual(self.browser.selected_text(), selected)
        QTest.keyClick(self.browser, Qt.Key.Key_Home)
        self.assertEqual(self.bar.value(), 0)

    def test_short_sections_snap_both_directions(self):
        self.scroller.set_enabled(True)
        self.wheel()
        self.finish_animation()
        self.assertGreater(self.bar.value(), 0)
        self.assertIn(self.bar.value(), self.scroller.line_starts())
        self.wheel(angle=120)
        self.finish_animation()
        self.assertEqual(self.bar.value(), 0)

    def test_long_sections_keep_overlapping_pages_before_next_dictionary(self):
        self.render(lines=20)
        self.scroller.set_enabled(True)
        second = self.scroller.section_tops()[1]
        stops = self.scroller.stops()
        self.assertGreater(second, self.browser.viewport().height())
        self.assertLess(stops[1], self.browser.viewport().height())
        self.assertIn(second - self.scroller.header.height(), stops)
        for left, right in zip(stops, stops[1:]):
            self.assertLessEqual(right - left, self.browser.viewport().height())
        for target in stops[1:]:
            self.scroller.advance(1)
            self.finish_animation()
            self.assertEqual(self.bar.value(), target)
        self.wheel()
        self.assertEqual(self.bar.value(), self.bar.maximum())

    def test_new_headword_lands_at_top_and_long_pages_stop_before_boundary(self):
        entries = tuple(Entry(str(i), term, "", "Source", "ja", ("line\n" * 20,))
                        for i, term in enumerate(("猫", "犬", "鳥")))
        self.browser.setHtml(render_result(SearchResult("猫", "ja", "en", entries), expanded=("Source",)))
        self.app.processEvents()
        self.scroller.set_enabled(True)
        second = self.scroller.boundaries()[1][0]
        stops = self.scroller.stops()
        height = self.browser.viewport().height() - self.scroller.header.height()
        self.assertIn(second, stops)
        self.assertGreaterEqual(max(stop for stop in stops if stop < second), second - height)
        self.bar.setValue(second)
        self.assertFalse(self.scroller.header.isVisible())
        self.assertGreaterEqual(self.browser.cursorRect(self.browser.document().find("犬")).top(), 0)

    def finish_animation(self):
        self.scroller.animation.setCurrentTime(self.scroller.animation.duration())

    def test_trackpad_scrolls_continuously_with_native_momentum(self):
        self.render(lines=20)
        self.scroller.set_enabled(True)
        total = 0
        for movement, phase in ((-20, Qt.ScrollPhase.ScrollUpdate),
                                (-25, Qt.ScrollPhase.ScrollUpdate),
                                (-100, Qt.ScrollPhase.ScrollMomentum)):
            self.wheel(angle=0, pixel=movement, phase=phase)
            total -= movement
            self.assertEqual(self.bar.value(), total)
            self.assertIsNone(self.scroller._target)

    def test_trackpad_crosses_dictionary_sections_without_snapping(self):
        self.scroller.set_enabled(True)
        boundary = self.scroller.section_tops()[1]
        self.bar.setValue(boundary - 5)
        self.wheel(angle=0, pixel=-10)
        self.assertEqual(self.bar.value(), boundary + 5)
        self.wheel(angle=0, pixel=3)
        self.assertEqual(self.bar.value(), boundary + 2)

    def test_scroll_does_not_skip_next_headword(self):
        entries = tuple(Entry(str(i), term, "", "Source", "ja", ("line\n" * 20,))
                        for i, term in enumerate(("猫", "犬", "鳥")))
        self.browser.setHtml(render_result(SearchResult("猫", "ja", "en", entries), expanded=("Source",)))
        self.app.processEvents()
        self.scroller.set_enabled(True)
        second = self.scroller.boundaries()[1][0]
        self.wheel(angle=0, pixel=-10000)
        self.assertEqual(self.bar.value(), second - self.browser.viewport().height())
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollBegin)
        self.wheel(angle=0, pixel=-10)
        self.assertEqual(self.bar.value(), second)
        self.wheel(angle=0, pixel=-10000, phase=Qt.ScrollPhase.ScrollMomentum)
        self.assertEqual(self.bar.value(), second)
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollBegin)
        self.wheel(angle=0, pixel=10000)
        self.assertEqual(self.bar.value(), second - self.browser.viewport().height())

    def test_mouse_wheel_scrolls_immediately_without_intermediate_animation(self):
        self.render(lines=20)
        self.scroller.set_enabled(True)
        self.wheel()
        first = self.bar.value()
        self.assertGreater(first, 0)
        self.assertIn(first, self.scroller.line_starts())
        self.assertIsNone(self.scroller._target)
        self.wheel()
        second = self.bar.value()
        self.assertGreater(second, first)
        self.assertIn(second, self.scroller.line_starts())
        self.finish_animation()
        self.assertEqual(self.bar.value(), second)

    def test_arrow_page_and_boundary_keys_preserve_text_selection(self):
        self.scroller.set_enabled(True)
        self.browser.setTextCursor(self.browser.document().find("Definition"))
        selected = self.browser.selected_text()
        QTest.keyClick(self.browser, Qt.Key.Key_Down)
        self.finish_animation()
        self.assertGreater(self.bar.value(), 0)
        self.assertIn(self.bar.value(), self.scroller.line_starts())
        QTest.keyClick(self.browser, Qt.Key.Key_Up)
        self.finish_animation()
        self.assertEqual(self.bar.value(), 0)
        QTest.keyClick(self.browser, Qt.Key.Key_PageDown)
        self.finish_animation()
        self.assertGreater(self.bar.value(), 0)
        QTest.keyClick(self.browser, Qt.Key.Key_End)
        self.finish_animation()
        self.assertEqual(self.bar.value(), self.bar.maximum())
        QTest.keyClick(self.browser, Qt.Key.Key_Home)
        self.finish_animation()
        self.assertEqual(self.bar.value(), 0)
        self.assertEqual(self.browser.selected_text(), selected)

    def test_sticky_headword_keeps_pitch_renderer_and_reading(self):
        from meikipop.dictionary.pitch import PITCH_OBJECT, Pitch
        entries = (Entry("cat", "猫", "ねこ", "Source", "ja", ("Meaning\n" * 30,),
                         pitches=(Pitch("Pitch", "ねこ", 1),)),)
        self.browser.setHtml(render_result(SearchResult("猫", "ja", "en", entries), expanded=("Source",)))
        self.app.processEvents()
        self.scroller.set_enabled(True)
        self.bar.setValue(50)
        header = self.scroller.header
        self.assertTrue(header.isVisible())
        self.assertIn("ねこ", header.toPlainText())
        self.assertIsNotNone(header._pitch_object)
        self.assertIsNotNone(header.document().documentLayout().handlerForObject(PITCH_OBJECT))
        block = header.document().begin()
        pitches = []
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.charFormat().objectType() == PITCH_OBJECT:
                    pitches.append(fragment)
                iterator += 1
            block = block.next()
        self.assertEqual(len(pitches), 1)
        self.assertGreater(header._pitch_object.intrinsicSize(header.document(), pitches[0].position(),
                                                            pitches[0].charFormat()).width(), 0)

    def test_sticky_headword_follows_groups_and_preserves_japanese_ruby(self):
        entries = tuple(Entry(str(i), term, reading, "Source", "ja",
                              ("\n".join(f"Meaning {n}" for n in range(20)),))
                        for i, (term, reading) in enumerate((("猫", "ねこ"), ("犬", "いぬ"))))
        self.browser.setHtml(render_result(SearchResult("猫", "ja", "en", entries),
                                           expanded=("Source",), headword_furigana=True))
        self.app.processEvents()
        self.scroller.set_enabled(True)
        self.assertEqual(self.browser.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bar.setValue(50)
        self.assertTrue(self.scroller.header.isVisible())
        self.assertEqual(self.scroller.header.pos(), QPoint(0, 0))
        self.assertEqual(self.scroller.header.toPlainText().strip(), "猫")
        second = self.scroller.boundaries()[1][0]
        height = self.scroller.header.height()
        self.bar.setValue(second - height)
        self.assertEqual(self.scroller.header.pos(), QPoint(0, 0))
        self.bar.setValue(second - height // 2)
        self.assertTrue(self.scroller.header.isVisible())
        self.assertEqual(self.scroller.header.toPlainText().strip(), "猫")
        self.assertEqual(self.scroller.header.y() + height, second - self.bar.value())
        self.bar.setValue(second)
        self.assertFalse(self.scroller.header.isVisible())
        self.bar.setValue(self.scroller._top(self.scroller._headings[1]) + 5)
        self.assertTrue(self.scroller.header.isVisible())
        self.assertEqual(self.scroller.header.pos(), QPoint(0, 0))
        self.assertEqual(self.scroller.header.toPlainText().strip(), "犬")
        self.bar.setValue(second - height // 2)
        self.assertEqual(self.scroller.header.toPlainText().strip(), "猫")
        self.assertEqual(self.scroller.header.y() + height, second - self.bar.value())
        self.bar.setValue(0)
        self.assertFalse(self.scroller.header.isVisible())
        self.scroller.set_preview(True)
        self.assertFalse(self.scroller.header.isVisible())
        self.scroller.set_enabled(False)
        self.assertEqual(self.browser.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def test_replacing_document_or_disabling_cancels_pending_motion(self):
        self.scroller.set_enabled(True)
        self.wheel()
        self.render(lines=3)
        value = self.bar.value()
        self.finish_animation()
        self.assertEqual(self.bar.value(), value)
        self.wheel()
        self.scroller.set_enabled(False)
        value = self.bar.value()
        self.finish_animation()
        self.assertEqual(self.bar.value(), value)

    def test_reduced_motion_uses_the_same_stops_without_animation(self):
        self.scroller.set_enabled(True)
        self.scroller.animation_enabled = False
        self.wheel()
        self.assertGreater(self.bar.value(), 0)
        self.assertIn(self.bar.value(), self.scroller.line_starts())

    def test_fractional_wheel_steps_accumulate(self):
        self.scroller.set_enabled(True)
        for _ in range(3):
            self.wheel(angle=-30)
        self.assertEqual(self.bar.value(), 0)
        self.wheel(angle=-30)
        self.finish_animation()
        self.assertGreater(self.bar.value(), 0)
        self.assertIn(self.bar.value(), self.scroller.line_starts())

    def test_partial_wheel_notch_does_not_carry_into_another_result(self):
        self.scroller.set_enabled(True)
        self.wheel(angle=-60)
        self.assertEqual(self.bar.value(), 0)
        self.render(lines=20)
        self.wheel(angle=-60)
        self.assertEqual(self.bar.value(), 0)
        self.wheel(angle=-60)
        self.assertGreater(self.bar.value(), 0)

    def test_modified_horizontal_and_selection_scrolls_are_not_intercepted(self):
        self.scroller.set_enabled(True)
        for modifiers, horizontal, selecting in ((Qt.KeyboardModifier.ControlModifier, 0, False),
                                                 (Qt.KeyboardModifier.NoModifier, 120, False),
                                                 (Qt.KeyboardModifier.NoModifier, 0, True)):
            self.browser.selecting = selecting
            event = QWheelEvent(QPointF(), QPointF(), QPoint(horizontal, 0), QPoint(horizontal, -30),
                                Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
            self.assertFalse(self.scroller.eventFilter(self.browser.viewport(), event))
        self.browser.selecting = False

    def test_free_scroll_position_and_text_selection_survive_snapping(self):
        self.scroller.set_enabled(True)
        cursor = self.browser.document().find("Definition")
        self.browser.setTextCursor(cursor)
        selected = self.browser.selected_text()
        self.bar.setValue(self.scroller.stops()[1] + 3)
        value = self.bar.value()
        self.assertEqual(value, self.scroller.stops()[1] + 3)
        self.wheel()
        self.finish_animation()
        self.assertGreater(self.bar.value(), value)
        self.assertIn(self.bar.value(), self.scroller.line_starts())
        self.assertEqual(self.browser.selected_text(), selected)

    def test_rich_explanation_never_shows_partial_edge_lines(self):
        import math
        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QRegion
        self.browser.resize(710, 430)
        font = self.browser.document().defaultFont()
        font.setPixelSize(24)
        self.browser.document().setDefaultFont(font)
        self.browser.setHtml('<style>body{font-size:24px}h2{font-size:28px;margin:0}</style>'
                             '<h2><a name="scroll-headword-0"></a><a name="scroll-section-0"></a>ちゃんと</h2>'
                             '<p>Bunpro Dictionary</p><p>[ちゃんと・きちんと]</p><h3>Meaning</h3>'
                             '<p>Properly, Neatly, Orderly, Sufficiently, Decently</p><h3>Explanation</h3>'
                             '<p>' + 'A long explanation of similar expressions and their usage. ' * 25 + '</p>')
        self.app.processEvents()
        self.scroller.set_enabled(True)
        self.app.processEvents()
        document = self.browser.document()
        self.assertGreater(self.bar.maximum(), 0)
        checked = 0
        for scroll in (0, 1, 7, 47, 84, 153):
            with self.subTest(scroll=scroll):
                self.bar.setValue(scroll)
                viewport = self.browser.viewport()
                top = self.scroller.header.height() if self.scroller.header.isVisible() else 0
                body = QRegion(QRect(0, top, viewport.width(), viewport.height() - top))
                mask = viewport.mask().intersected(body)
                block = document.begin()
                while block.isValid():
                    rect = document.documentLayout().blockBoundingRect(block)
                    for index in range(block.layout().lineCount()):
                        line = block.layout().lineAt(index)
                        start = math.ceil(rect.top() + line.y()) - self.bar.value()
                        end = math.ceil(rect.top() + line.y() + line.height()) - self.bar.value()
                        partial = start < top < end or start < viewport.height() < end
                        if partial and end - start <= viewport.height() - top:
                            visible = QRegion(QRect(0, start, viewport.width(), end - start)).intersected(mask)
                            self.assertTrue(visible.isEmpty(), (block.text(), start, end, top))
                            checked += 1
                    block = block.next()
        self.assertGreater(checked, 0)

    def test_document_replacement_and_resize_recompute_stops(self):
        self.scroller.set_enabled(True)
        old = self.scroller.stops()
        self.render(lines=20)
        tall = self.scroller.stops()
        self.assertNotEqual(old, tall)
        self.browser.resize(320, 290)
        self.app.processEvents()
        self.assertNotEqual(tall, self.scroller.stops())

    def test_repeated_sources_and_ruby_headings_keep_distinct_sections(self):
        entries = tuple(Entry(str(index), term, reading, "Source", "ja", ("definition",))
                        for index, (term, reading) in enumerate((("猫", "ねこ"), ("生", "き"), ("生", "せい"))))
        self.browser.setHtml(render_result(SearchResult("生", "ja", "en", entries),
                                           expanded=("Source",), headword_furigana=True))
        self.app.processEvents()
        self.assertEqual(len(self.scroller.section_tops()), 3)
        self.assertEqual(len(set(self.scroller.section_tops())), 3)

    def test_translation_and_kanji_are_reachable_sections(self):
        result = SearchResult("猫", "ja", "en", (Entry("cat", "猫", "ねこ", "Source", "ja", ("cat",)),),
                              translation="translated sentence", kanji=(KanjiEntry("猫", meanings=("cat",)),))
        self.browser.setHtml(render_result(result))
        self.app.processEvents()
        self.assertEqual(len(self.scroller.section_tops()), 3)
        self.assertEqual(len(set(self.scroller.section_tops())), 3)

    def test_short_final_kanji_panel_can_align_at_top_without_stale_headword(self):
        result = SearchResult("賛成票", "ja", "en", (
            Entry("vote", "賛成票", "さんせいひょう", "Source", "ja", ("vote in favor\n" * 12,)),),
            kanji=(KanjiEntry("票", meanings=("ballot",)),))
        self.browser.resize(400, 360)
        self.browser.setHtml(render_result(result, expanded=("Source",)))
        self.app.processEvents()
        normal_maximum = self.bar.maximum()
        self.scroller.set_enabled(True)
        self.app.processEvents()
        top = self.scroller.boundaries()[-1][0]
        self.assertGreater(top, normal_maximum)
        self.assertGreaterEqual(self.bar.maximum(), top)
        self.wheel(angle=0, pixel=-10000)
        if self.bar.value() < top:
            self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollBegin)
            self.wheel(angle=0, pixel=-10)
        self.assertEqual(self.bar.value(), top)
        self.assertFalse(self.scroller.header.isVisible())
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollBegin)
        self.wheel(angle=0, pixel=20)
        self.assertLess(self.bar.value(), top)
        self.scroller.set_enabled(False)
        self.app.processEvents()
        self.assertEqual(self.browser.document().rootFrame().frameFormat().bottomMargin(),
                         self.browser.document().documentMargin())

    def test_short_headword_hides_following_section_until_next_gesture(self):
        entries = tuple(Entry(str(i), term, "", "Source", "ja", ("meaning",))
                        for i, term in enumerate(("猫", "犬", "鳥")))
        self.browser.resize(400, 360)
        self.browser.setHtml(render_result(SearchResult("猫", "ja", "en", entries)))
        self.app.processEvents()
        self.scroller.set_enabled(True)
        self.app.processEvents()
        second, third = [top for top, _ in self.scroller.boundaries()[1:]]
        self.assertLess(second, self.browser.viewport().height())
        self.assertEqual(self.browser.viewport().mask().boundingRect().height(), second)
        self.wheel(angle=0, pixel=-10, phase=Qt.ScrollPhase.ScrollUpdate)
        self.assertEqual(self.bar.value(), second)
        self.assertEqual(self.browser.viewport().mask().boundingRect().height(), third - second)
        self.wheel(angle=0, pixel=-100, phase=Qt.ScrollPhase.ScrollMomentum)
        self.assertEqual(self.bar.value(), second)
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollBegin)
        self.wheel(angle=0, pixel=-10, phase=Qt.ScrollPhase.ScrollUpdate)
        self.assertEqual(self.bar.value(), third)
        self.scroller.set_enabled(False)
        self.assertTrue(self.browser.viewport().mask().isEmpty())


if __name__ == "__main__":
    unittest.main()
