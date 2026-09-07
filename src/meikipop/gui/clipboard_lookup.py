"""Clipboard input for the existing Japanese lookup worker and popup."""
import threading

from PyQt6.QtCore import QObject, pyqtSignal, QSettings
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QAction
from pynput import keyboard, mouse

from meikipop.config.config import config


class ClipboardLookup(QObject):
    requested = pyqtSignal()
    dismissed = pyqtSignal()
    completed = pyqtSignal(int, object)

    def __init__(self, shared, popup, tray):
        super().__init__(popup)
        self.shared, self.popup = shared, popup
        self._lock = threading.Lock()
        self._revision, self._text, self._processed = 0, None, -1
        self.settings = QSettings("Meikipop", "JapaneseClipboard")
        self.previous = QApplication.clipboard().text()
        self.requested.connect(self.read)
        self.dismissed.connect(self.dismiss)
        self.completed.connect(self.deliver)
        action = QAction("Look up clipboard", tray.menu)
        tray.menu.insertAction(tray.menu.actions()[0], action)
        action.triggered.connect(self.read)
        self.automatic = tray.menu.addAction("Look up copied text automatically")
        self.automatic.setCheckable(True)
        self.automatic.setChecked(self.settings.value("automatic", False, bool))
        self.automatic.toggled.connect(lambda value: self.settings.setValue("automatic", value))
        QApplication.clipboard().dataChanged.connect(self.changed)
        self.keys = keyboard.GlobalHotKeys({"<ctrl>+<alt>+l": self.requested.emit})
        self.clicks = mouse.Listener(on_click=lambda x, y, button, down: self.dismissed.emit() if down else None)
        self.keys.start()
        self.clicks.start()

    @property
    def revision(self):
        with self._lock:
            return self._revision

    @property
    def active(self):
        with self._lock:
            return self._text is not None

    def read(self):
        text = QApplication.clipboard().text().strip()
        if not config.is_enabled or not text or len(text) > 2000:
            return
        with self._lock:
            self._revision += 1
            self._text = text
        self.popup.set_latest_data(None)
        self.shared.lookup_queue.trigger()

    def changed(self):
        text = QApplication.clipboard().text()
        previous, self.previous = self.previous, text
        if self.automatic.isChecked() and text != previous and QApplication.activeWindow() is None:
            self.read()

    def process(self, lookup):
        with self._lock:
            revision, text = self._revision, self._text
            if text is None or revision == self._processed:
                return
            self._processed = revision
        self.completed.emit(revision, lookup(text))

    def deliver(self, revision, entries):
        with self._lock:
            if revision != self._revision or self._text is None:
                return
        if config.is_enabled:
            self.popup.set_latest_data(entries or None)
        if not entries:
            self.dismiss()

    def dismiss(self):
        with self._lock:
            if self._text is None:
                return
            self._revision += 1
            self._text = None
        self.popup.set_latest_data(None)

    def shutdown(self):
        self.dismiss()
        QApplication.clipboard().dataChanged.disconnect(self.changed)
        for listener in (self.keys, self.clicks):
            listener.stop()
            listener.join(timeout=2)
