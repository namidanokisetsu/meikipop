"""Global input listeners; all widget work is delivered through Qt signals."""
import sys
import threading
from time import monotonic

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard, mouse

from meikipop.gui.activation import ActivationState, normalise_pynput_key, normalise_pynput_button


class DesktopInput(QObject):
    hold_changed = pyqtSignal(bool)
    clicked = pyqtSignal()
    selected = pyqtSignal()
    dismissed = pyqtSignal()
    clipboard_requested = pyqtSignal()
    search_requested = pyqtSignal()

    def __init__(self, bindings, clipboard_hotkey, search_hotkey, double_click_ms, parent=None):
        super().__init__(parent)
        self.activation = ActivationState(bindings)
        self.visible = threading.Event()
        self._escape_down = False
        self._last_click = None
        self.double_click_seconds = double_click_ms / 1000
        self.keys = keyboard.Listener(on_press=lambda key: self.key(key, True),
                                      on_release=lambda key: self.key(key, False),
                                      **({"win32_event_filter": self.filter_key} if sys.platform == "win32" else {}))
        self.clicks = mouse.Listener(on_click=self.click)
        self.shortcuts = None
        self.set_shortcuts(clipboard_hotkey, search_hotkey)
        self.keys.start()
        self.clicks.start()

    def set_shortcuts(self, clipboard_hotkey, search_hotkey):
        if keyboard.HotKey.parse(clipboard_hotkey) == keyboard.HotKey.parse(search_hotkey):
            raise ValueError("Clipboard and search shortcuts must differ.")
        replacement = keyboard.GlobalHotKeys({clipboard_hotkey: self.clipboard_requested.emit,
                                               search_hotkey: self.search_requested.emit})
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

    def filter_key(self, message, data):
        if data.vkCode == 0x1B and (self.visible.is_set() or self._escape_down):
            down = message in (0x100, 0x104)
            if down and not self._escape_down:
                self.dismissed.emit()
            self._escape_down = down
            self.keys.suppress_event()

    def click(self, x, y, button, down):
        token = normalise_pynput_button(button)
        if token:
            self.activation.update(token, down)
            self.hold_changed.emit(self.activation.active)
        if down:
            self.clicked.emit()
        if button == mouse.Button.left and not down:
            now = monotonic()
            previous, self._last_click = self._last_click, (now, x, y)
            if previous and now - previous[0] <= self.double_click_seconds and abs(x - previous[1]) <= 4 and abs(y - previous[2]) <= 4:
                self._last_click = None
                self.selected.emit()

    def shutdown(self):
        for listener in (self.keys, self.clicks, self.shortcuts):
            if listener:
                listener.stop()
                listener.join(timeout=2)
