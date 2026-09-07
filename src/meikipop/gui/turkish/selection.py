"""Windows selection copy with a bounded wait and clipboard restoration."""
import sys
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, QMimeData, pyqtSignal
from PyQt6.QtWidgets import QApplication


class SelectionCapture(QObject):
    completed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending = False
        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self.poll)
        self.original = None
        self.foreground = None
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.GetForegroundWindow.restype = wintypes.HWND
            self.user32.GetClipboardSequenceNumber.restype = wintypes.DWORD

    def start(self):
        if sys.platform != "win32" or self.pending or QApplication.activeWindow() is not None:
            return
        # Do not release modifiers the reader is holding or copy into a new foreground app.
        if any(self.user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            return
        self.foreground = self.user32.GetForegroundWindow()
        self.sequence = self.user32.GetClipboardSequenceNumber()
        mime = QApplication.clipboard().mimeData()
        self.original = QMimeData()
        if mime:
            for name in mime.formats():
                self.original.setData(name, mime.data(name))
        self.pending = True
        self.deadline = monotonic() + .45
        from pynput.keyboard import Controller, Key
        keys = Controller()
        try:
            keys.press(Key.ctrl)
            try:
                keys.press("c")
                keys.release("c")
            finally:
                keys.release(Key.ctrl)
        except Exception:
            self.cancel()
            return
        self.timer.start()

    def poll(self):
        if self.user32.GetForegroundWindow() != self.foreground:
            self.cancel()
            return
        sequence = self.user32.GetClipboardSequenceNumber()
        if sequence != self.sequence:
            text = QApplication.clipboard().text()
            # Restore only while the clipboard is still the value just observed.
            if self.user32.GetClipboardSequenceNumber() == sequence:
                QApplication.clipboard().setMimeData(self.original)
                self.original = None
            self.cancel()
            if text.strip() and len(text) <= 2000:
                self.completed.emit(text)
        elif monotonic() >= self.deadline:
            self.cancel()

    def cancel(self):
        self.timer.stop()
        self.pending = False
        if self.original is not None:
            self.original.deleteLater()
            self.original = None
