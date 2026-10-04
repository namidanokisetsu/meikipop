"""Global input listeners; all widget work is delivered through Qt signals."""
import sys
import threading
from time import monotonic

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard, mouse

from meikipop.gui.activation import ActivationState, normalise_pynput_key, normalise_pynput_button
from meikipop.gui.text_shortcuts import TextHotKeys, validate_shortcuts


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

    def filter_key(self, message, data):
        if data.vkCode == 0x1B and (self.visible.is_set() or self._escape_down):
            down = message in (0x100, 0x104)
            if down and not self._escape_down:
                self.dismissed.emit()
            self._escape_down = down
            self.keys.suppress_event()

    def _request_pin(self, button):
        if (button == self.pin_gesture and self.activation.active and
                self.visible.is_set() and self.pin_ready.is_set()):
            self.pin_ready.clear()
            self.pin_pending.set()
            self.pin_requested.emit()
            return True
        return False

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
