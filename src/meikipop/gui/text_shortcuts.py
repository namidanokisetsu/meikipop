"""Text shortcuts also accept injected keys from accessibility input tools."""
import sys

from pynput.keyboard import GlobalHotKeys, KeyCode


class TextHotKeys(GlobalHotKeys):
    def canonical(self, key):
        canonical = super().canonical(key)
        vk = getattr(key, "vk", None)
        if sys.platform == "win32" and vk is not None and 0x41 <= vk <= 0x5A:
            return KeyCode.from_char(chr(vk).lower())
        return canonical

    def _on_press(self, key, injected=False):
        for hotkey in self._hotkeys:
            hotkey.press(self.canonical(key))

    def _on_release(self, key, injected=False):
        for hotkey in self._hotkeys:
            hotkey.release(self.canonical(key))
