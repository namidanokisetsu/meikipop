"""Global input listeners; all widget work is delivered through Qt signals."""
import sys
import threading
from time import monotonic

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard, mouse

from meikipop.gui.activation import ActivationState, normalise_pynput_key, normalise_pynput_button
from meikipop.gui.text_shortcuts import TextHotKeys, validate_shortcuts


def validate_pin_shortcut(value):
    keys = keyboard.HotKey.parse(value) if value else []
    modifiers = {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.alt, keyboard.Key.cmd}
    primary = [key for key in keys if key not in modifiers]
    if value and (len(primary) != 1 or primary[0] == keyboard.Key.esc.value):
        raise ValueError("Choose a pin key other than Escape or a modifier alone.")
    chord = None
    if primary and sys.platform == "win32":
        import ctypes
        native = getattr(primary[0], "value", primary[0])
        vk = native.vk
        if vk is None and native.char:
            # Latin shortcut presets use stable Windows virtual keys even when
            # the active typing layout cannot produce that character (e.g. RU).
            if native.char.isascii() and native.char.isalnum():
                vk = ord(native.char.upper())
        if vk is None and native.char:
            user32 = ctypes.WinDLL("user32")
            user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
            user32.VkKeyScanW.restype = ctypes.c_short
            code = user32.VkKeyScanW(native.char)
            vk = code & 0xff if code != -1 else None
        if vk is None:
            raise ValueError("Choose a pin key available on this keyboard.")
        native_modifiers = {keyboard.Key.ctrl: (0x11,), keyboard.Key.shift: (0x10,),
                            keyboard.Key.alt: (0x12,), keyboard.Key.cmd: (0x5B, 0x5C)}
        chord = (vk, [native_modifiers[key] for key in keys if key in native_modifiers])
    return keys, chord


class DesktopInput(QObject):
    hold_changed = pyqtSignal(bool)
    clicked = pyqtSignal()
    selected = pyqtSignal()
    dragged = pyqtSignal()
    selection_requested = pyqtSignal()
    dismissed = pyqtSignal()
    clipboard_requested = pyqtSignal()
    search_requested = pyqtSignal()
    pin_requested = pyqtSignal()

    def __init__(self, bindings, clipboard_hotkey, search_hotkey, double_click_ms, parent=None):
        super().__init__(parent)
        self.activation = ActivationState(bindings)
        self.visible = threading.Event()
        self.pin_ready = threading.Event()
        self.pin_pending = threading.Event()
        self.pin_gesture = "popup"
        self._consumed_pin = None
        self._escape_down = False
        self._pin_binding = ""
        self._pin_hotkey = None
        self._pin_native = None
        self._consumed_pin_keys = set()
        self._last_click = None
        self._press_point = None
        self.double_click_seconds = double_click_ms / 1000
        self.keys = keyboard.Listener(on_press=lambda key: self.key(key, True),
                                      on_release=lambda key: self.key(key, False),
                                      **({"win32_event_filter": self.filter_key} if sys.platform == "win32" else {}))
        self.clicks = mouse.Listener(on_click=self.click,
                                     **({"win32_event_filter": self.filter_mouse} if sys.platform == "win32" else {}))
        self.shortcuts = None
        self.set_shortcuts(clipboard_hotkey, search_hotkey)
        self.keys.start()
        self.clicks.start()

    def set_shortcuts(self, clipboard_hotkey, search_hotkey, selection_hotkey=""):
        validate_shortcuts((clipboard_hotkey, search_hotkey, selection_hotkey))
        bindings = {key: callback for key, callback in
                    ((clipboard_hotkey, self.clipboard_requested.emit),
                     (search_hotkey, self.search_requested.emit),
                     (selection_hotkey, self.selection_requested.emit)) if key}
        replacement = TextHotKeys(bindings) if bindings else None
        if replacement:
            replacement.start()
        previous, self.shortcuts = self.shortcuts, replacement
        if previous:
            previous.stop()
            previous.join(timeout=2)

    def key(self, key, down):
        token = normalise_pynput_key(key)
        if token:
            self.activation.update(token, down)
            self.hold_changed.emit(self.activation.active)
        if self._pin_hotkey is not None and sys.platform != "win32":
            canonical = self.keys.canonical(key)
            (self._pin_hotkey.press if down else self._pin_hotkey.release)(canonical)

    def set_pin_shortcut(self, value):
        if value == self._pin_binding:
            return
        keys, native = validate_pin_shortcut(value)
        self._pin_binding = value
        self._pin_hotkey = keyboard.HotKey(keys, self._request_ready_pin) if keys else None
        self._pin_native = native

    def _request_ready_pin(self):
        if self.activation.active and self.visible.is_set() and self.pin_ready.is_set():
            self.pin_ready.clear()
            self.pin_pending.set()
            self.pin_requested.emit()
            return True
        return False

    def filter_key(self, message, data):
        down = message in (0x100, 0x104)
        if self._pin_native and down and data.vkCode == self._pin_native[0] and data.vkCode not in self._consumed_pin_keys:
            import ctypes
            state = ctypes.windll.user32.GetAsyncKeyState
            if (all(any(state(mod) & 0x8000 for mod in group) for group in self._pin_native[1])
                    and self._request_ready_pin()):
                self._consumed_pin_keys.add(data.vkCode)
        if data.vkCode in self._consumed_pin_keys:
            if not down:
                self._consumed_pin_keys.discard(data.vkCode)
            self.keys.suppress_event()
            return False
        if data.vkCode == 0x1B and (self.visible.is_set() or self._escape_down):
            if down and not self._escape_down:
                self.dismissed.emit()
            self._escape_down = down
            self.keys.suppress_event()

    def _request_pin(self, button):
        return button == self.pin_gesture and self._request_ready_pin()

    def filter_mouse(self, message, data):
        event = {0x201: ("left", True), 0x202: ("left", False),
                 0x207: ("middle", True), 0x208: ("middle", False)}.get(message)
        if event is None:
            return True
        button, down = event
        if down and self._request_pin(button):
            self._consumed_pin = button
            self.clicks.suppress_event()
            return False
        if not down and button == self._consumed_pin:
            # Consume the matching release even if the scan key was released
            # first, so the foreground application never receives half a click.
            self._consumed_pin = None
            self.clicks.suppress_event()
            return False
        return True

    def click(self, x, y, button, down):
        if down and sys.platform != "win32":
            self._request_pin(getattr(button, "name", ""))
        token = normalise_pynput_button(button)
        if token:
            self.activation.update(token, down)
            self.hold_changed.emit(self.activation.active)
        if down:
            self.clicked.emit()
            if button == mouse.Button.left:
                self._press_point = (x, y)
        if button == mouse.Button.left and not down:
            origin, self._press_point = self._press_point, None
            if origin and abs(x - origin[0]) + abs(y - origin[1]) >= 8:
                self._last_click = None
                self.dragged.emit()
                return
            now = monotonic()
            previous, self._last_click = self._last_click, (now, x, y)
            if previous and now - previous[0] <= self.double_click_seconds and abs(x - previous[1]) <= 4 and abs(y - previous[2]) <= 4:
                self._last_click = None
                self.selected.emit()

    def shutdown(self):
        self.pin_ready.clear()
        self.pin_pending.clear()
        for listener in (self.keys, self.clicks, self.shortcuts):
            if listener:
                listener.stop()
                listener.join(timeout=2)
