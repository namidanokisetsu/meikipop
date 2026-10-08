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

    def test_default_uses_normal_wheel_scrolling(self):
        self.assertFalse(self.scroller.enabled)
        self.wheel()
        self.assertGreater(self.bar.value(), 0)
        self.assertNotEqual(self.bar.value(), self.scroller.stops()[1])

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
        second = self.scroller.stops()[1]
        self.wheel()
        self.finish_animation()
        self.assertEqual(self.bar.value(), second)
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
            self.wheel()
            self.finish_animation()
            self.assertEqual(self.bar.value(), target)
        self.wheel()
        self.assertEqual(self.bar.value(), self.bar.maximum())

    def finish_animation(self):
        self.scroller.animation.setCurrentTime(self.scroller.animation.duration())

    def test_trackpad_moves_continuously_and_keeps_native_momentum(self):
        self.render(lines=4)
        self.scroller.set_enabled(True)
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollBegin)
        self.wheel(angle=0, pixel=-20, phase=Qt.ScrollPhase.ScrollUpdate)
        self.assertEqual(self.bar.value(), 20)
        self.wheel(angle=0, pixel=-25, phase=Qt.ScrollPhase.ScrollUpdate)
        self.assertEqual(self.bar.value(), 45)
        self.wheel(angle=0, pixel=-100, phase=Qt.ScrollPhase.ScrollMomentum)
        self.assertEqual(self.bar.value(), 145)
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollEnd)
        self.scroller._idle.timeout.emit()
        self.finish_animation()
        self.assertIn(self.bar.value(), self.scroller.stops())
        self.assertGreater(self.bar.value(), self.scroller.stops()[1])

    def test_unphased_trackpad_settles_after_idle(self):
        self.scroller.set_enabled(True)
        self.wheel(angle=0, pixel=-45)
        self.wheel(angle=0, pixel=-45)
        self.assertEqual(self.bar.value(), 90)
        target = min(self.scroller.stops(), key=lambda value: abs(value - 90))
        self.scroller._idle.timeout.emit()
        self.finish_animation()
        self.assertEqual(self.bar.value(), target)

    def test_repeated_steps_retarget_and_reverse_without_jumping(self):
        self.scroller.set_enabled(True)
        stops = self.scroller.stops()
        self.wheel()
        self.assertEqual(self.bar.value(), 0)
        self.scroller.animation.setCurrentTime(60)
        self.assertGreater(self.bar.value(), 0)
        self.assertLess(self.bar.value(), stops[1])
        self.wheel()
        self.finish_animation()
        self.assertEqual(self.bar.value(), stops[2])
        self.wheel(angle=120)
        self.finish_animation()
        self.assertEqual(self.bar.value(), stops[1])

    def test_arrow_page_and_boundary_keys_preserve_text_selection(self):
        self.scroller.set_enabled(True)
        self.browser.setTextCursor(self.browser.document().find("Definition"))
        selected = self.browser.selected_text()
        QTest.keyClick(self.browser, Qt.Key.Key_Down)
        self.finish_animation()
        self.assertEqual(self.bar.value(), self.scroller.stops()[1])
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
        second = self.scroller._top(self.scroller._headings[1])
        height = self.scroller.header.height()
        self.bar.setValue(second - height)
        self.assertEqual(self.scroller.header.pos(), QPoint(0, 0))
        self.bar.setValue(second - height // 2)
        self.assertTrue(self.scroller.header.isVisible())
        self.assertEqual(self.scroller.header.toPlainText().strip(), "猫")
        self.assertEqual(self.scroller.header.y() + height, second - self.bar.value())
        self.bar.setValue(second)
        self.assertFalse(self.scroller.header.isVisible())
        self.bar.setValue(second + 5)
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
        self.assertEqual(self.bar.value(), self.scroller.stops()[1])

    def test_fractional_wheel_steps_accumulate(self):
        self.scroller.set_enabled(True)
        for _ in range(3):
            self.wheel(angle=-30)
        self.assertEqual(self.bar.value(), 0)
        self.wheel(angle=-30)
        self.finish_animation()
        self.assertEqual(self.bar.value(), self.scroller.stops()[1])

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
        target = next(stop for stop in self.scroller.stops() if stop > value)
        self.wheel()
        self.finish_animation()
        self.assertEqual(self.bar.value(), target)
        self.assertEqual(self.browser.selected_text(), selected)

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


if __name__ == "__main__":
    unittest.main()
