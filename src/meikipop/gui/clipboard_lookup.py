"""Clipboard input for the existing Japanese lookup worker and popup."""
import sys
import threading
from time import monotonic

from PyQt6.QtCore import QObject, pyqtSignal, QSettings, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFrame, QVBoxLayout, QLineEdit, QWidget, QFormLayout, QCheckBox
from PyQt6.QtGui import QAction, QCursor, QFont
from pynput import keyboard, mouse

from meikipop.config.config import config
from meikipop.gui.text_shortcuts import TextHotKeys, validate_shortcuts
from meikipop.gui.selection import SelectionCapture
from meikipop.gui.shortcut_edit import ShortcutEdit


class ClipboardLookup(QObject):
    requested = pyqtSignal()
    search_requested = pyqtSignal()
    selection_requested = pyqtSignal()
    dismissed = pyqtSignal()
    mouse_clicked = pyqtSignal(int, int, object, bool)
    completed = pyqtSignal(int, object)

    def __init__(self, shared, popup, tray):
        super().__init__(popup)
        self.shared, self.popup = shared, popup
        self.tray = tray
        self._lock = threading.Lock()
        self._revision, self._text, self._processed = 0, None, -1
        self.settings = QSettings("Meikipop", "JapaneseClipboard")
        self.previous = QApplication.clipboard().text()
        self.requested.connect(lambda: self.read() if QApplication.activeWindow() is None else None)
        self.search_requested.connect(lambda: self.open_search() if QApplication.activeWindow() is None else None)
        self.dismissed.connect(self.dismiss)
        self.completed.connect(self.deliver)
        self.selection = SelectionCapture(self)
        self.selection.completed.connect(self.lookup_text)
        self.selection_requested.connect(self.read_selection)
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
        self.keys = None
        self.apply_shortcuts({name: self.settings.value(name + "_hotkey", "")
                              for name in ("clipboard", "search", "selection")})
        self._last_click = None
        self.double_click_timer = QTimer(self)
        self.double_click_timer.setSingleShot(True)
        self.double_click_timer.setInterval(60)
        self.double_click_timer.timeout.connect(self.capture_double_click)
        self.mouse_clicked.connect(self.on_click)
        self.clicks = mouse.Listener(on_click=self.mouse_clicked.emit)
        self.clicks.start()

    def apply_shortcuts(self, values):
        validate_shortcuts(values.values())
        signals = {"clipboard": self.requested, "search": self.search_requested,
                   "selection": self.selection_requested}
        bindings = {value: signals[name].emit for name, value in values.items()
                    if value and (name != "selection" or sys.platform == "win32")}
        replacement = TextHotKeys(bindings) if bindings else None
        if replacement:
            replacement.start()
        previous, self.keys = self.keys, replacement
        if previous:
            previous.stop()
            previous.join(timeout=2)
        for name, value in values.items():
            self.settings.setValue(name + "_hotkey", value)
        self.dismiss()

    def settings_page(self):
        page = QWidget()
        form = QFormLayout(page)
        page.shortcuts = {}
        for name, label in (("clipboard", "Clipboard shortcut:"), ("search", "Search shortcut:"),
                            ("selection", "Selected text shortcut:")):
            presets = {"clipboard": "Ctrl+Alt+L", "search": "Ctrl+Alt+D", "selection": "Ctrl+Alt+S"}
            field = ShortcutEdit(self.settings.value(name + "_hotkey", ""),
                                 self.settings.value(name + "_preset", presets[name]))
            field.setEnabled(name != "selection" or sys.platform == "win32")
            page.shortcuts[name] = field
            form.addRow(label, field)
        page.automatic = QCheckBox()
        page.automatic.setChecked(self.automatic.isChecked())
        form.addRow("Look up copied text:", page.automatic)
        page.double_click = QCheckBox()
        page.double_click.setChecked(self.settings.value("double_click", False, bool))
        page.double_click.setEnabled(sys.platform == "win32")
        form.addRow("Look up double-clicked text:", page.double_click)
        return page

    def save_settings_page(self, page):
        self.apply_shortcuts({name: field.text().strip() for name, field in page.shortcuts.items()})
        for name, field in page.shortcuts.items():
            self.settings.setValue(name + "_preset", field.recorder.keySequence().toString())
        self.automatic.setChecked(page.automatic.isChecked())
        self.settings.setValue("double_click", page.double_click.isChecked())
        self.double_click_timer.stop()

    def on_click(self, x, y, button, down):
        if down:
            self.double_click_timer.stop()
            self.dismiss()
            return
        if button != mouse.Button.left:
            self._last_click = None
            return
        now = monotonic()
        previous, self._last_click = self._last_click, (now, x, y)
        if previous and now - previous[0] <= QApplication.doubleClickInterval() / 1000 and abs(x - previous[1]) <= 4 and abs(y - previous[2]) <= 4:
            self._last_click = None
            if self.settings.value("double_click", False, bool):
                self.double_click_timer.start()

    def capture_double_click(self):
        if config.is_enabled and self.settings.value("double_click", False, bool):
            self.selection.start()

    @property
    def revision(self):
        with self._lock:
            return self._revision

    @property
    def active(self):
        with self._lock:
            return self._text is not None

    def read_selection(self):
        if config.is_enabled:
            self.selection.start(wait_for_modifiers=True)

    def read(self):
        self.selection.cancel()
        self.lookup_text(QApplication.clipboard().text())

    def lookup_text(self, text):
        self.selection.cancel()
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
        if not self.selection.pending and self.automatic.isChecked() and text != previous and QApplication.activeWindow() is None:
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
        self.selection.cancel()
        with self._lock:
            if self._text is None:
                return
            self._revision += 1
            self._text = None
        self.popup.set_latest_data(None)

    def shutdown(self):
        self.double_click_timer.stop()
        self.dismiss()
        self.search_window.hide()
        QApplication.clipboard().dataChanged.disconnect(self.changed)
        for listener in (self.keys, self.clicks):
            if listener:
                listener.stop()
                listener.join(timeout=2)
