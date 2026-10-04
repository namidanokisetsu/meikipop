"""Opt-in selection and clipboard lookup; native callbacks never touch widgets."""
from time import monotonic
from PyQt6.QtCore import QObject, QPoint, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication


class TextTriggers(QObject):
    clicked = pyqtSignal(int, int, bool)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.listener = None
        self.press = self.last_click = None
        self.last_text = ""
        self.clicked.connect(self.click)
        QApplication.clipboard().dataChanged.connect(self.clipboard_changed)
        window.mode_changed.connect(self.reload)
        window.scan_settings_changed.connect(self.reload)
        self.reload()

    def reload(self, *_):
        enabled = self.window.settings.value(f"profiles/{self.window.preferred_foreign}/selected_text", False, type=bool)
        if enabled and self.listener is None:
            from pynput import mouse
            self.listener = mouse.Listener(on_click=lambda x, y, button, down:
                self.clicked.emit(x, y, down) if button == mouse.Button.left else None)
            self.listener.start()
        elif not enabled and self.listener is not None:
            self.listener.stop()
            self.listener = None

    def click(self, x, y, down):
        if QApplication.activeWindow() is not None or self.window.geometry().contains(QPoint(x, y)) and self.window.isVisible():
            return
        if down:
            self.press = (x, y)
            if self.window.isVisible():
                self.window.hide()
            return
        now = monotonic()
        dragged = self.press and abs(x-self.press[0]) + abs(y-self.press[1]) >= 8
        double = self.last_click and now-self.last_click[0] <= QApplication.doubleClickInterval()/1000 and abs(x-self.last_click[1])+abs(y-self.last_click[2]) < 8
        self.last_click = None if double else (now, x, y)
        self.press = None
        if dragged or double:
            self.window._selection_passive = True
            QTimer.singleShot(60, self.window.selection.start)

    def clipboard_changed(self):
        text = QApplication.clipboard().text()
        previous, self.last_text = self.last_text, text
        if (text != previous and text.strip() and not self.window.selection.pending and QApplication.activeWindow() is None
                and self.window.settings.value(f"profiles/{self.window.preferred_foreign}/clipboard_lookup", False, type=bool)):
            self.window.lookup_selected(text, passive=True)

    def shutdown(self):
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=1)
            self.listener = None
