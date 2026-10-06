import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meikipop.gui.native_selection import read_selection


class NativeReaderTests(unittest.TestCase):
    def reader(self, text="kitap"):
        automation, api, element, pattern = Mock(), Mock(), Mock(), Mock()
        automation.GetFocusedElement.return_value = element
        automation.CompareElements.return_value = True
        element.CurrentIsPassword = False
        element.GetCurrentPattern.return_value.QueryInterface.return_value = pattern
        ranges = SimpleNamespace(Length=1, GetElement=lambda _: SimpleNamespace(
            GetText=lambda limit: text[:limit], GetBoundingRectangles=lambda: (10, 20, 30, 40)))
        pattern.GetSelection.return_value = ranges
        return automation, api, element

    def test_selection_text_and_rectangles(self):
        automation, api, _ = self.reader()
        result = read_selection(automation, api, 123)
        self.assertEqual((result.status, result.text, result.rectangles),
                         ("selected", "kitap", ((10, 20, 30, 40),)))

    def test_password_is_rejected_before_accessing_text(self):
        automation, api, element = self.reader()
        element.CurrentIsPassword = True
        self.assertEqual(read_selection(automation, api, 123).status, "blocked")
        element.GetCurrentPattern.assert_not_called()

    def test_oversized_selection_is_rejected_not_truncated(self):
        automation, api, _ = self.reader("x" * 2100)
        self.assertEqual(read_selection(automation, api, 123).status, "blocked")

    def test_unrelated_focus_does_not_read_selection(self):
        automation, api, element = self.reader()
        automation.CompareElements.return_value = False
        automation.RawViewWalker.GetParentElement.return_value = None
        self.assertEqual(read_selection(automation, api, 123).status, "blocked")
        element.GetCurrentPattern.assert_not_called()

    def test_utf16_limit_never_returns_a_truncated_selection(self):
        for length in (1500, 2001):
            with self.subTest(length=length):
                automation, api, element = self.reader()
                text = "😀" * length
                selected = SimpleNamespace(GetText=lambda limit: text.encode("utf-16-le")[:limit * 2].decode("utf-16-le", errors="ignore"),
                                           GetBoundingRectangles=lambda: ())
                pattern = element.GetCurrentPattern.return_value.QueryInterface.return_value
                pattern.GetSelection.return_value = SimpleNamespace(Length=1, GetElement=lambda _: selected)
                result = read_selection(automation, api, 123)
                if length <= 2000:
                    self.assertEqual(result.text, text)
                else:
                    self.assertEqual(result.status, "blocked")

    def test_geometry_failure_keeps_successful_selection(self):
        automation, api, element = self.reader()
        selected = Mock()
        selected.GetText.return_value = "kitap"
        selected.GetBoundingRectangles.side_effect = RuntimeError("not visible")
        pattern = element.GetCurrentPattern.return_value.QueryInterface.return_value
        pattern.GetSelection.return_value = SimpleNamespace(Length=1, GetElement=lambda _: selected)
        self.assertEqual(read_selection(automation, api, 123).text, "kitap")

    def test_selection_bounds_map_negative_scaled_monitor(self):
        from PyQt6.QtCore import QPoint, QRect
        from meikipop.gui.native_selection import selection_bounds
        screen = SimpleNamespace(name=lambda: "left", geometry=lambda: QRect(-1000, 0, 1000, 800),
                                 availableGeometry=lambda: QRect(-1000, 0, 1000, 780))
        with patch("PyQt6.QtWidgets.QApplication.screens", return_value=[screen]), \
                patch("PyQt6.QtGui.QCursor.pos", return_value=QPoint(-500, 200)), \
                patch("meikipop.utils.capture.windows_screen_geometry", return_value=(-2000, 0, 2000, 1600)):
            self.assertEqual(selection_bounds(((-1000, 200, 200, 40),)), QRect(-500, 100, 100, 20))
