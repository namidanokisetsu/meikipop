import unittest
from types import SimpleNamespace
from unittest.mock import Mock

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
