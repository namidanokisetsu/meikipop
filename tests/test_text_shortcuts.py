import sys
import unittest
from unittest.mock import Mock, patch

from pynput.keyboard import GlobalHotKeys
from meikipop.gui.text_shortcuts import TextHotKeys


@unittest.skipUnless(sys.platform == "win32", "Windows key propagation")
class ShortcutPropagationTests(unittest.TestCase):
    def test_selection_shortcut_is_dispatched_without_replacing_source_selection(self):
        listener = TextHotKeys({"<ctrl>+<alt>+s": Mock()})
        listener._message_loop = Mock()
        listener.suppress_event = Mock()
        listener._key_state = Mock(return_value=0x8000)
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x100, 0x53)):
            listener._convert(0, 0x100, None)
        listener._message_loop.post.assert_called_once_with(listener._WM_PROCESS, 0x100, 0x53)
        listener.suppress_event.assert_called_once()
        listener._key_state.return_value = 0
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x101, 0x53)):
            listener._convert(0, 0x101, None)
        self.assertEqual(listener.suppress_event.call_count, 2)
        listener.suppress_event.reset_mock()
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x100, 0x53)):
            listener._convert(0, 0x100, None)
        listener.suppress_event.assert_not_called()

    def test_other_keys_pass_through_while_modifiers_are_held(self):
        listener = TextHotKeys({"<ctrl>+<shift>+d": Mock()})
        listener._message_loop = Mock()
        listener.suppress_event = Mock()
        listener._key_state = Mock(return_value=0x8000)
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x100, 0x43)):
            self.assertEqual(listener._convert(0, 0x100, None), (0x100, 0x43))
        listener.suppress_event.assert_not_called()
        listener._message_loop.post.assert_not_called()
