"""Opt-in selection lookup; native callbacks never touch widgets."""
from time import monotonic
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication


class TextTriggers(QObject):
    clicked = pyqtSignal(int, int, bool)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.listener = None
        self.press = self.last_click = None
        self.clicked.connect(self.click)
        window.mode_changed.connect(self.reload)
        window.scan_settings_changed.connect(self.reload)
        self.reload()

    def reload(self, *_):
        enabled = self.window.settings.value(f"profiles/{self.window.preferred_foreign}/selected_text", False, type=bool)
        if enabled and self.listener is None:
            from meikipop.utils.macos import require_input_monitoring_permission, InputMonitoringPermissionError
            try:
                require_input_monitoring_permission()
            except InputMonitoringPermissionError as error:
                self.window.show_message(str(error))
                return
            from pynput import mouse
            self.listener = mouse.Listener(on_click=lambda x, y, button, down:
                self.clicked.emit(x, y, down) if button == mouse.Button.left else None)
            self.listener.start()
        elif not enabled and self.listener is not None:
            self.listener.stop()
            self.listener = None

    def click(self, x, y, down):
        # Native hook coordinates are physical pixels; Qt geometry uses logical pixels.
        if (self.window._scan_hold_active or QApplication.activeWindow() is not None
                or QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None
                or self.window.isVisible() and self.window.geometry().contains(QCursor.pos())):
            self.press = self.last_click = None
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
            QTimer.singleShot(60, self.capture_selection)

    def capture_selection(self):
        if (not self.window._scan_hold_active and not self.window.selection.pending and QApplication.activeWindow() is None
                and not (self.window.isVisible() and self.window.geometry().contains(QCursor.pos()))
                and self.window.settings.value(f"profiles/{self.window.preferred_foreign}/selected_text", False, type=bool)):
            self.window._selection_for_search = False
            self.window._selection_passive = True
            self.window.selection.start()

    def shutdown(self):
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=1)
            self.listener = None
