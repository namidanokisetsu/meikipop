"""Text shortcuts also accept injected keys from accessibility input tools."""
import sys

from pynput.keyboard import GlobalHotKeys, HotKey, Key, KeyCode
from meikipop.gui.keyboard_listener import MacListenerMixin


class TextHotKeys(MacListenerMixin, GlobalHotKeys):
    def __init__(self, bindings):
        self._swallowed = set()
        self._native_chords = []
        if sys.platform == "win32":
            import ctypes
            self._key_state = ctypes.windll.user32.GetAsyncKeyState
            modifiers = {Key.ctrl: (0x11,), Key.shift: (0x10,), Key.alt: (0x12,), Key.cmd: (0x5B, 0x5C)}
            for binding in bindings:
                parsed = HotKey.parse(binding)
                required = [modifiers[key] for key in parsed if key in modifiers]
                for key in parsed:
                    if key in modifiers:
                        continue
                    native = getattr(key, "value", key)
                    vk = native.vk or (ord(native.char.upper()) if native.char and len(native.char) == 1 else None)
                    if vk:
                        self._native_chords.append((vk, required))
        super().__init__(bindings)

    def _convert(self, code, msg, data):
        converted = super()._convert(code, msg, data)
        if converted is not None:
            message, vk = converted
            down = msg in self._PRESS_MESSAGES
            if down and any(vk == key and all(any(self._key_state(mod) & 0x8000 for mod in group)
                                             for group in modifiers) for key, modifiers in self._native_chords):
                self._swallowed.add(vk)
            if vk in self._swallowed:
                if not down:
                    self._swallowed.discard(vk)
                # Dispatch our shortcut, but keep it out of the source application's text field.
                self._message_loop.post(self._WM_PROCESS, message, vk)
                self.suppress_event()
        return converted

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


def validate_shortcuts(values):
    """Blank disables a binding; compare parsed keys to catch reordered duplicates."""
    from pynput.keyboard import HotKey
    seen = []
    for value in values:
        if not value:
            continue
        keys = frozenset(HotKey.parse(value))
        if not keys or keys in seen:
            raise ValueError("Shortcuts must be nonempty and distinct.")
        seen.append(keys)
