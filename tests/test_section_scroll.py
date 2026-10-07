import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from meikipop.dictionary.library import Entry
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

    def test_default_uses_normal_wheel_scrolling(self):
        self.assertFalse(self.scroller.enabled)
        self.wheel()
        self.assertGreater(self.bar.value(), 0)
        self.assertNotEqual(self.bar.value(), self.scroller.stops()[1])

    def test_short_sections_snap_both_directions(self):
        self.scroller.set_enabled(True)
        second = self.scroller.stops()[1]
        self.wheel()
        self.assertEqual(self.bar.value(), second)
        self.wheel(angle=120)
        self.assertEqual(self.bar.value(), 0)

    def test_long_sections_keep_overlapping_pages_before_next_dictionary(self):
        self.render(lines=20)
        self.scroller.set_enabled(True)
        second = self.scroller.section_tops()[1]
        stops = self.scroller.stops()
        self.assertGreater(second, self.browser.viewport().height())
        self.assertLess(stops[1], self.browser.viewport().height())
        self.assertIn(second, stops)
        for left, right in zip(stops, stops[1:]):
            self.assertLessEqual(right - left, self.browser.viewport().height())
        for target in stops[1:]:
            self.wheel()
            self.assertEqual(self.bar.value(), target)
        self.wheel()
        self.assertEqual(self.bar.value(), self.bar.maximum())

    def test_trackpad_advances_once_and_ignores_momentum(self):
        self.scroller.set_enabled(True)
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollBegin)
        self.wheel(angle=0, pixel=-20, phase=Qt.ScrollPhase.ScrollUpdate)
        self.assertEqual(self.bar.value(), 0)
        self.wheel(angle=0, pixel=-25, phase=Qt.ScrollPhase.ScrollUpdate)
        first = self.bar.value()
        self.assertEqual(first, self.scroller.stops()[1])
        self.wheel(angle=0, pixel=-100, phase=Qt.ScrollPhase.ScrollUpdate)
        self.wheel(angle=0, pixel=-100, phase=Qt.ScrollPhase.ScrollMomentum)
        self.assertEqual(self.bar.value(), first)
        self.wheel(angle=0, phase=Qt.ScrollPhase.ScrollEnd)
        self.wheel(angle=0, pixel=-45, phase=Qt.ScrollPhase.ScrollBegin)
        self.assertEqual(self.bar.value(), self.scroller.stops()[2])

    def test_unphased_trackpad_resets_after_idle(self):
        self.scroller.set_enabled(True)
        self.wheel(angle=0, pixel=-45)
        first = self.bar.value()
        self.wheel(angle=0, pixel=-45)
        self.assertEqual(self.bar.value(), first)
        self.scroller._idle.timeout.emit()
        self.wheel(angle=0, pixel=-45)
        self.assertEqual(self.bar.value(), self.scroller.stops()[2])

    def test_fractional_wheel_steps_accumulate(self):
        self.scroller.set_enabled(True)
        for _ in range(3):
            self.wheel(angle=-30)
        self.assertEqual(self.bar.value(), 0)
        self.wheel(angle=-30)
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


if __name__ == "__main__":
    unittest.main()
