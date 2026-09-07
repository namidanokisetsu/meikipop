"""Clipboard input for the existing Japanese lookup worker and popup."""
import threading

from PyQt6.QtCore import QObject, pyqtSignal, QSettings, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QFrame, QVBoxLayout, QLineEdit
from PyQt6.QtGui import QAction, QCursor, QFont
from pynput import keyboard, mouse

from meikipop.config.config import config


class ClipboardLookup(QObject):
    requested = pyqtSignal()
    search_requested = pyqtSignal()
    dismissed = pyqtSignal()
    completed = pyqtSignal(int, object)

    def __init__(self, shared, popup, tray):
        super().__init__(popup)
        self.shared, self.popup = shared, popup
        self.tray = tray
        self._lock = threading.Lock()
        self._revision, self._text, self._processed = 0, None, -1
        self.settings = QSettings("Meikipop", "JapaneseClipboard")
        self.previous = QApplication.clipboard().text()
        self.requested.connect(self.read)
        self.search_requested.connect(self.open_search)
        self.dismissed.connect(self.dismiss)
        self.completed.connect(self.deliver)
        action = QAction("Look up clipboard", tray.menu)
        tray.menu.insertAction(tray.menu.actions()[0], action)
        action.triggered.connect(self.read)
        search_action = QAction("Search…", tray.menu)
        tray.menu.insertAction(action, search_action)
        search_action.triggered.connect(self.open_search)
        self.search_window = QDialog(popup, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.search_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self.search_window)
        outer.setContentsMargins(0, 0, 0, 0)
        self.search_frame = QFrame()
        outer.addWidget(self.search_frame)
        layout = QVBoxLayout(self.search_frame)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.search_text)
        layout.addWidget(self.search)
        self.automatic = tray.menu.addAction("Look up copied text automatically")
        self.automatic.setCheckable(True)
        self.automatic.setChecked(self.settings.value("automatic", False, bool))
        self.automatic.toggled.connect(lambda value: self.settings.setValue("automatic", value))
        QApplication.clipboard().dataChanged.connect(self.changed)
        self.keys = keyboard.GlobalHotKeys({"<ctrl>+<alt>+l": self.requested.emit,
                                            "<ctrl>+<alt>+d": self.search_requested.emit})
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
        self.lookup_text(QApplication.clipboard().text())

    def lookup_text(self, text):
        text = text.strip()
        if not config.is_enabled or not text or len(text) > 2000:
            return
        with self._lock:
            self._revision += 1
            self._text = text
        self.popup.set_latest_data(None)
        self.shared.lookup_queue.trigger()

    def open_search(self):
        if not config.is_enabled:
            return
        self.dismiss()
        self.search_frame.setStyleSheet(self.popup.frame.styleSheet())
        self.search.setStyleSheet(f"background:transparent; color:{config.color_foreground}; border:0;")
        font = QFont(config.font_family)
        font.setPixelSize(config.font_size_definitions)
        self.search.setFont(font)
        self.search.clear()
        self.search_window.resize(320, 48)
        geometry = self.tray.geometry()
        point = geometry.center() if geometry.isValid() else QCursor.pos()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.search_window.move(max(area.left(), min(point.x(), area.right() - 320)),
                                max(area.top(), min(point.y() - 60, area.bottom() - 48)))
        self.search_window.show()
        self.search_window.activateWindow()
        self.search.setFocus()

    def search_text(self):
        if self.search.text().strip():
            self.search_window.hide()
            self.lookup_text(self.search.text())

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
        self.search_window.hide()
        QApplication.clipboard().dataChanged.disconnect(self.changed)
        for listener in (self.keys, self.clicks):
            listener.stop()
            listener.join(timeout=2)
