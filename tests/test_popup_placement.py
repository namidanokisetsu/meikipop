import unittest
from PyQt6.QtCore import QPoint, QRect, QSize
from meikipop.gui.popup_style import expanded_geometry, popup_position


class PopupPlacementTests(unittest.TestCase):
    def test_clamps_flush_to_inclusive_screen_edges(self):
        for area in (QRect(0, 0, 1920, 1040), QRect(-1280, -200, 1280, 720)):
            size = QSize(480, 340)
            x, _ = popup_position(area.right(), area.top() + 100, size, area, 'flip_vertically')
            _, y = popup_position(area.left() + 100, area.bottom(), size, area, 'flip_horizontally')
            self.assertEqual(x + size.width(), area.right() + 1)
            self.assertEqual(y + size.height(), area.bottom() + 1)

    def test_above_subtitles_preserves_lower_edge(self):
        previous = QRect(1500, 890, 350, 100)
        result = expanded_geometry(previous, QSize(480, 340), QRect(0, 0, 1920, 1040), QPoint(1600, 1005))
        self.assertEqual(result.bottom(), previous.bottom())
        self.assertLess(result.top(), previous.top())
        self.assertLess(result.bottom(), 1005)

    def test_below_source_grows_down_when_space_allows(self):
        previous = QRect(200, 150, 350, 100)
        result = expanded_geometry(previous, QSize(480, 340), QRect(0, 0, 1920, 1040), QPoint(200, 120))
        self.assertEqual(result.top(), previous.top())

    def test_flipping_a_below_text_preview_does_not_cover_the_source(self):
        previous = QRect(200, 925, 350, 100)
        anchor = QPoint(200, 910)
        result = expanded_geometry(previous, QSize(480, 340), QRect(0, 0, 1920, 1040), anchor)
        self.assertLess(result.bottom(), anchor.y())

    def test_no_room_below_grows_up_and_clamps_to_negative_origin_display(self):
        area = QRect(-1280, -200, 1280, 720)
        previous = QRect(-200, 390, 190, 100)
        result = expanded_geometry(previous, QSize(480, 340), area)
        self.assertEqual(result.bottom(), previous.bottom())
        self.assertTrue(area.contains(result))
        self.assertTrue(area.contains(expanded_geometry(previous, QSize(2000, 2000), area)))
