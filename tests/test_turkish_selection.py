import unittest
from types import SimpleNamespace
from unittest.mock import patch
from meikipop.gui.turkish.desktop_input import DesktopInput


class DesktopInputTests(unittest.TestCase):
    def test_escape_is_suppressed_only_for_visible_popup_including_key_up(self):
        with patch("pynput.keyboard.Listener"), patch("meikipop.gui.turkish.desktop_input.TextHotKeys"), patch("pynput.mouse.Listener"):
            inputs = DesktopInput("shift,middle", "<ctrl>+<alt>+l", "<ctrl>+<alt>+d", 400)
        try:
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            inputs.keys.suppress_event.assert_not_called()
            inputs.visible.set()
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            inputs.visible.clear()
            inputs.filter_key(0x101, SimpleNamespace(vkCode=27))
            self.assertEqual(inputs.keys.suppress_event.call_count, 2)
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            self.assertEqual(inputs.keys.suppress_event.call_count, 2)
        finally:
            inputs.shutdown()
