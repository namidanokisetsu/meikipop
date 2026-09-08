"""Turkish desktop popup with clipboard, local OCR, and offline dictionaries."""
import threading
import subprocess
import sys
from time import monotonic
from pathlib import Path
from urllib.parse import unquote

from PyQt6.QtCore import QObject, Qt, pyqtSignal, QTimer, QSettings, QPoint, QRect, QEvent, QLockFile
from PyQt6.QtGui import QCursor, QKeySequence, QShortcut, QImage, QIcon, QFont
from PyQt6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QMenu,
                            QPushButton, QSystemTrayIcon, QTextBrowser, QVBoxLayout, QWidget,
                            QMessageBox, QFrame, QLineEdit)

from .worker import TextWorker, OCRWorker
from .rendering import render_result
from .browser import DictionaryBrowser
from .desktop_input import DesktopInput
from meikipop.gui.selection import SelectionCapture
from meikipop.gui.themes import THEMES

from meikipop.config.config import config
from meikipop.gui.popup_style import frame_stylesheet, popup_position

MAX_TEXT = 2000


class RequestState:
    def __init__(self):
        self.current = 0

    def next(self):
        self.current += 1
        return self.current

    def accepts(self, request_id):
        return request_id == self.current


class Signals(QObject):
    clipboard_requested = pyqtSignal()
    completed = pyqtSignal(int, object, str)
    recognized = pyqtSignal(int, object, str)
    hold_changed = pyqtSignal(bool)
    dismissed = pyqtSignal()
    setup_completed = pyqtSignal(str)
    setup_busy = pyqtSignal(bool)
    setup_progress = pyqtSignal(str)





class ClipboardWindow(QWidget):
    def __init__(self, dictionary, analyzer="stanza", model_dir=None, hotkey=None, search_hotkey=None):
        super().__init__()
        self.settings = QSettings("meikipop-turkish", "Turkish")
        if not self.settings.value("text_input_opt_in", False, bool):
            # Previous versions enabled these by default, without user opt-in.
            for key in ("auto_clipboard", "selection_lookup"):
                self.settings.setValue(key, False)
            for key in ("clipboard_hotkey", "search_hotkey"):
                self.settings.setValue(key, "")
            self.settings.setValue("text_input_opt_in", True)
        self.setWindowTitle("meikipop-turkish")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(320, 80)
        self.wordnet_expanded = False
        self.reposition = True
        self.pinned = False
        self.holding = False
        self.suppress_hold = False
        self.last_scan = None
        self.capture_region = None
        self.capture_scale = (1, 1)
        self.prefetch_failed = False
        self.background_request = None
        self.scan_busy = False
        self.ocr_results = None
        self.last_hit = None
        self.anchor = QCursor.pos()
        self.last_clipboard = QApplication.clipboard().text()
        self.hotkey = hotkey if hotkey is not None else self.settings.value("clipboard_hotkey", "")
        self.search_hotkey = search_hotkey if search_hotkey is not None else self.settings.value("search_hotkey", "")
        self.selection_hotkey = self.settings.value("selection_hotkey", "")
        self.bindings = self.settings.value("activation_bindings", self.settings.value("hold_key", config.activation_bindings))
        self.enabled = True
        self.searching = False
        self.input = None
        self.selection_ticket = 0
        self.selection = SelectionCapture(self)
        self.selection.completed.connect(self.selection_result)
        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.setInterval(350)
        self.leave_timer.timeout.connect(self.finish_peek)
        self.setup_thread = None
        self.setup_status = ""
        self.requests = RequestState()
        self.result = None
        self.history = []
        self.show_more = False
        from .audio import TurkishSpeech
        self.speech = TurkishSpeech(self)
        self.signals = Signals(self)
        self.signals.clipboard_requested.connect(self.read_clipboard)
        self.signals.completed.connect(self.deliver)
        self.signals.recognized.connect(self.recognized)
        self.ocr_worker = OCRWorker(self.signals)
        self.ocr_worker.start()
        self.signals.hold_changed.connect(self.set_hold)
        self.signals.dismissed.connect(self.dismiss)
        self.signals.setup_completed.connect(self.setup_finished)
        self.worker = TextWorker(self.signals, dictionary, analyzer, model_dir)
        self.worker.start()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(self)
        layout.addWidget(self.frame)
        content = QVBoxLayout(self.frame)
        content.setContentsMargins(10, 10, 10, 10)
        content.setSpacing(3)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(lambda: self.submit(self.search.text()) if self.search.text().strip() else None)
        self.search.hide()
        content.addWidget(self.search)
        self.browser = DictionaryBrowser()
        self.browser.word_selected.connect(self.submit)
        self.browser.setFrameShape(QFrame.Shape.NoFrame)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.anchorClicked.connect(self.navigate)
        content.addWidget(self.browser)
        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.back_button = QPushButton("←")
        self.back_button.setToolTip("Previous lookup")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(self.go_back)
        self.pin_button = QPushButton("📌")
        self.pin_button.setCheckable(True)
        self.pin_button.setToolTip("Pin")
        self.pin_button.clicked.connect(self.pin)
        self.audio_button = QPushButton("♪")
        self.audio_button.setToolTip("Pronounce")
        self.audio_button.setVisible(self.settings.value("audio_enabled", False, bool))
        self.audio_button.clicked.connect(self.pronounce)
        close = QPushButton("×")
        close.setToolTip("Dismiss (Escape)")
        close.clicked.connect(self.dismiss)
        controls.addWidget(self.back_button)
        controls.addStretch()
        for widget in (self.audio_button, self.pin_button, close):
            controls.addWidget(widget)
        for widget in (self.back_button, self.audio_button, self.pin_button, close):
            widget.setFlat(True)
            widget.setFixedHeight(20)
            widget.setFixedWidth(48 if widget is self.pin_button else 24)
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        content.addLayout(controls)
        self.examples = QCheckBox(self)
        self.examples.hide()
        self.examples.setChecked(self.settings.value("examples", config.show_examples, bool))
        self.examples.toggled.connect(self.render)
        self.examples.toggled.connect(lambda value: self.settings.setValue("examples", value))
        self.browser.textChanged.connect(self.fit_content)
        self.apply_appearance()
        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.activated.connect(self.dismiss)
        from meikipop.utils.paths import paths
        self.tray = QSystemTrayIcon(QIcon(paths.get_resource_path("icon.ico")), self)
        self.tray.setToolTip("meikipop-turkish")
        menu = QMenu(self)
        action = menu.addAction("Look up clipboard")
        action.triggered.connect(self.read_clipboard)
        menu.addAction("Search…").triggered.connect(self.open_search)
        self.auto_action = menu.addAction("Look up copied text automatically")
        self.auto_action.setCheckable(True)
        self.auto_action.setChecked(self.settings.value("auto_clipboard", False, bool))
        self.auto_action.toggled.connect(self.toggle_clipboard)
        menu.addAction("Settings").triggered.connect(self.open_settings)
        self.pause_action = menu.addAction("Pause meikipop-turkish")
        self.pause_action.setCheckable(True)
        self.pause_action.triggered.connect(self.toggle_enabled)
        self.tray.activated.connect(self.tray_activated)
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.request_quit)
        self.tray.setContextMenu(menu)
        self.tray.show()
        QApplication.clipboard().dataChanged.connect(self.clipboard_changed)
        QApplication.instance().installEventFilter(self)
        self.scan_timer = QTimer(self)
        self.scan_timer.setInterval(30)
        self.scan_timer.timeout.connect(self.scan_pointer)
        self.scan_timer.start()
        self.prefetch_timer = QTimer(self)
        self.prefetch_timer.setInterval(self.settings.value("auto_scan_ms", max(100, int(config.auto_scan_interval_seconds * 1000)), int))
        self.prefetch_timer.timeout.connect(lambda: self.scan_pointer(background=True))
        self.prefetch_timer.start()
        self.input = DesktopInput(self.bindings, self.hotkey, self.search_hotkey, QApplication.doubleClickInterval(), self)
        self.input.clipboard_requested.connect(self.read_clipboard)
        self.input.search_requested.connect(self.open_search)
        self.input.hold_changed.connect(self.set_hold)
        self.input.dismissed.connect(self.dismiss)
        self.input.clicked.connect(self.outside_click)
        self.input.selected.connect(self.selection_requested)
        self.input.dragged.connect(lambda: self.selection_requested(drag=True))
        self.input.selection_requested.connect(self.read_selection)
        self.input.set_shortcuts(self.hotkey, self.search_hotkey, self.selection_hotkey)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_enabled()

    def toggle_enabled(self):
        self.enabled = not self.enabled
        self.pause_action.setChecked(not self.enabled)
        from meikipop.utils.paths import paths
        self.tray.setIcon(QIcon(paths.get_resource_path("icon.ico" if self.enabled else "icon.inactive.ico")))
        if not self.enabled:
            self.dismiss()

    def outside_click(self):
        self.selection_ticket += 1
        point = QCursor.pos()
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return
        if self.isVisible() and not self.geometry().contains(point):
            self.dismiss()
        elif self.selection.pending:
            self.selection.cancel()

    def selection_requested(self, drag=False):
        if self.enabled and self.settings.value("drag_lookup" if drag else "selection_lookup", False, bool):
            ticket = self.selection_ticket
            QTimer.singleShot(60, lambda: self.selection.start(wait_for_modifiers=drag)
                              if self.enabled and ticket == self.selection_ticket else None)

    def read_selection(self):
        if self.enabled and self.setup_thread is None:
            self.selection.start(wait_for_modifiers=True)

    def selection_result(self, text):
        self.last_clipboard = QApplication.clipboard().text()
        if not self.enabled:
            return
        self.searching = False
        self.search.hide()
        self.anchor = QCursor.pos()
        self.reposition = True
        self.submit(text)

    def showEvent(self, event):
        if self.input:
            self.input.visible.set()
        super().showEvent(event)

    def hideEvent(self, event):
        if self.input:
            self.input.visible.clear()
        super().hideEvent(event)

    def enterEvent(self, event):
        self.leave_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.pinned:
            self.leave_timer.start()
        super().leaveEvent(event)

    def finish_peek(self):
        if not self.pinned and not self.geometry().contains(QCursor.pos()):
            self.dismiss()

    def read_clipboard(self):
        if not self.enabled:
            return
        self.searching = False
        self.search.hide()
        self.holding = False
        self.suppress_hold = True
        self.anchor = QCursor.pos()
        self.reposition = True
        self.submit(QApplication.clipboard().text())

    def submit(self, text, target=None, scan=None, peek=False, remember=True):
        if not self.enabled:
            return
        self.leave_timer.stop()
        if self.setup_thread is not None:
            self.tray.showMessage("meikipop-turkish", "Installation is running. Lookup resumes when it finishes.")
            return
        if remember and not peek and self.result is not None:
            previous = (self.result.text, self.result.target)
            if previous != (text, target):
                self.history = (self.history + [previous])[-32:]
                self.back_button.setEnabled(True)
        request_id = self.requests.next()
        if scan is None:
            self.scan_busy = False
        self.pinned = not peek
        self.pin_button.setChecked(self.pinned)
        self.reposition = self.reposition or not self.isVisible() or peek
        if scan is None and not text.strip():
            if not self.searching:
                self.dismiss()
            return
        if scan is None and len(text) > MAX_TEXT:
            self.result = None
            self.browser.setPlainText("Please copy at most 2,000 characters.")
            self.browser.show()
            self.show()
            return
        self.result = None
        self.show_more = False
        self.wordnet_expanded = False
        if scan is None:
            self.browser.setPlainText("Reading…" if scan is not None else "Looking up…")
        self.worker.queue.put((request_id, text, target, scan))

    def deliver(self, request_id, result, error):
        if request_id == getattr(self, "scan_request", None):
            self.scan_busy = False
        if not self.requests.accepts(request_id):
            return
        self.result = result
        if result is None and error.startswith(("No text", "No selectable")):
            self.hide()
            return
        if result is None and not error:
            self.hide()
            return
        self.browser.show()
        if error:
            self.browser.setPlainText(error)
        else:
            self.render()
        self.show()
        if not self.pinned and not self.holding:
            self.leave_timer.start()

    def render(self):
        if self.result is not None:
            self.browser.setToolTip(self.result.status)
            self.browser.setHtml(render_result(self.result, self.show_more, self.examples.isChecked(),
                                               self.wordnet_expanded, self.word_color, self.header_size,
                                               self.settings.value("dictionary_order")))

    def navigate(self, url):
        if self.result is None:
            return
        self.pin()
        if url.scheme() == "section":
            self.wordnet_expanded = True
            self.render()
            self.browser.scrollToAnchor(url.path())
        elif url.scheme() == "word":
            self.submit(unquote(url.path()))
        elif url.scheme() == "token":
            self.submit(self.result.text, int(url.path()))
        elif url.scheme() == "suggestion":
            index = int(url.path())
            if 0 <= index < len(self.result.suggestions):
                self.submit(self.result.suggestions[index].headword)
        elif url.scheme() == "more":
            self.show_more = True
            self.render()
        elif url.scheme() == "related":
            eid, index = url.path().rsplit(":", 1)
            for entry in self.result.entries:
                if entry["id"] == eid:
                    self.submit(entry["relations"][int(index)]["phrase"])
                    break

    def go_back(self):
        if self.history:
            text, target = self.history.pop()
            self.submit(text, target, remember=False)
            self.back_button.setEnabled(bool(self.history))

    def pronounce(self):
        if self.result is None:
            return
        self.pin()
        text = self.result.entries[0]["headword"] if self.result.entries else self.result.text
        if not self.speech.speak(text):
            self.tray.showMessage("meikipop-turkish", "Install a Turkish speech voice in Windows Settings.")

    def toggle_clipboard(self, enabled):
        self.settings.setValue("auto_clipboard", enabled)
        self.last_clipboard = QApplication.clipboard().text()

    def clipboard_changed(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        previous, self.last_clipboard = self.last_clipboard, text
        if (not self.enabled or self.selection.pending or not self.auto_action.isChecked() or text == previous or not text.strip()
                or len(text) > MAX_TEXT or QApplication.activeWindow() is not None):
            return
        self.anchor = QCursor.pos()
        self.reposition = True
        self.holding = False
        self.suppress_hold = True
        self.submit(text)

    def pin(self):
        self.leave_timer.stop()
        self.pinned = True
        self.holding = False
        self.suppress_hold = True
        self.pin_button.setChecked(True)

    def eventFilter(self, watched, event):
        if (self.isVisible() and event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget)
                and (watched is self or self.isAncestorOf(watched))):
            self.pin()
        return super().eventFilter(watched, event)

    def place_popup(self, anchor):
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        self.move(*popup_position(anchor.x(), anchor.y(), self.size(), area, self.settings.value("popup_position_mode", config.popup_position_mode)))

    def fit_content(self):
        screen = QApplication.screenAt(self.anchor) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        max_width = min(self.settings.value("max_width", 560, int), int(area.width() * .4))
        max_width = min(area.width(), max(240, max_width))
        doc = self.browser.document().clone()
        doc.setTextWidth(max_width - 24)
        width = min(max_width, max(240, int(doc.idealWidth()) + 24))
        doc.setTextWidth(width - 24)
        height = min(self.settings.value("max_height", 600, int), area.height(), int(doc.size().height()) + 48 + (32 if self.searching else 0))
        doc.deleteLater()
        self.resize(width, max(72, height))
        self.layout().activate()
        if self.reposition or not self.pinned:
            self.place_popup(self.anchor)
            # Keep positioning the initial loading/result pair at the source word.
            if self.result is not None:
                self.reposition = False
        else:
            self.move(max(area.left(), min(self.x(), area.right() + 1 - self.width())),
                      max(area.top(), min(self.y(), area.bottom() + 1 - self.height())))

    def set_hold(self, active):
        if not self.enabled or self.searching:
            return
        if not active:
            self.suppress_hold = False
            self.ocr_results = None
            self.last_hit = None
        if self.suppress_hold or active == self.holding:
            return
        self.holding = active
        if active:
            self.last_scan = None
            self.scan_pointer()
        elif not self.pinned:
            if self.result is None:
                self.requests.next()
                self.hide()
            elif not self.geometry().contains(QCursor.pos()):
                self.leave_timer.start()

    def scan_pointer(self, background=False):
        if background and (self.isVisible() or self.holding or self.prefetch_failed
                           or not self.settings.value("auto_scan", config.auto_scan_mode, bool)):
            return
        if not self.enabled or self.selection.pending or self.setup_thread is not None or self.pinned or (not self.holding and not background) or QApplication.activeModalWidget():
            return
        point = QCursor.pos()
        if self.isVisible() and self.geometry().contains(point):
            return
        if self.scan_busy and (background or self.ocr_results is None):
            return
        if not background and self.last_scan is not None and (point - self.last_scan).manhattanLength() < 3:
            return
        self.last_scan = QPoint(point)
        self.anchor = QPoint(point)
        if not background and self.ocr_results is not None and self.capture_region is not None and self.capture_region.contains(point):
            self.lookup_ocr(point)
            return
        if self.scan_busy:
            return
        was_visible = self.isVisible()
        self.hide()
        generation = self.requests.next()
        self.scan_busy = True
        self.scan_request = generation
        QTimer.singleShot(60 if was_visible else 0, lambda: self.capture_pointer(point, generation, background))

    def capture_pointer(self, point, generation, background=False):
        if not self.requests.accepts(generation) or (not self.holding and not background):
            self.scan_busy = False
            return
        try:
            import numpy as np
            screen = QApplication.screenAt(point) or QApplication.primaryScreen()
            geometry = screen.geometry()
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError("Screen capture unavailable")
            sx, sy = pixmap.width() / geometry.width(), pixmap.height() / geometry.height()
            self.capture_scale = (sx, sy)
            region = self.capture_region
            if region is None or not geometry.contains(region) or not region.adjusted(16, 16, -16, -16).contains(point):
                region = QRect(point.x() - 440, point.y() - 110, 880, 220).intersected(geometry)
                self.capture_region = QRect(region)
            image = pixmap.toImage().copy(
                round((region.x() - geometry.x()) * sx), round((region.y() - geometry.y()) * sy),
                round(region.width() * sx), round(region.height() * sy)).convertToFormat(QImage.Format.Format_RGB888)
            bits = image.bits()
            bits.setsize(image.sizeInBytes())
            pixels = np.frombuffer(bits, dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
            pixels = pixels[:, :image.width() * 3].reshape(image.height(), image.width(), 3)[:, :, ::-1].copy()
            self.background_request = generation if background else None
            self.scan_request = generation
            self.ocr_worker.queue.put((generation, pixels))
        except Exception:
            self.scan_busy = False
            if background:
                self.prefetch_failed = True
                return
            self.submit("")
            self.browser.setPlainText("Screen capture failed. You can still copy text to look it up.")

    def recognized(self, request_id, results, error):
        if request_id == getattr(self, "scan_request", None):
            self.scan_busy = False
        if not self.requests.accepts(request_id) or self.setup_thread is not None:
            return
        self.ocr_results = results
        self.last_hit = None
        self.prefetch_failed = bool(error)
        if request_id == self.background_request and not self.holding:
            return
        if error:
            self.deliver(request_id, None, error)
        elif self.holding and not self.pinned:
            self.lookup_ocr(QCursor.pos())

    def lookup_ocr(self, point):
        from meikipop.ocr.turkish_paddle import hit_word
        sx, sy = self.capture_scale
        target = ((point.x() - self.capture_region.x()) * sx,
                  (point.y() - self.capture_region.y()) * sy)
        hit = next((hit for result in self.ocr_results or ()
                    if (hit := hit_word(result, target))), None)
        if hit == self.last_hit and hit is not None:
            return
        self.last_hit = hit
        if hit is None:
            self.requests.next()
            self.result = None
            self.hide()
            return
        text, offset = hit
        self.submit(text, scan=offset, peek=True)

    def apply_appearance(self):
        theme = self.settings.value("popup_theme", "Meikipop")
        preset = THEMES.get(theme, {})
        if theme == "light":
            preset = THEMES["Academic"]
        elif theme == "dark":
            preset = THEMES["Nazeka"]
        def color(key):
            return preset.get(key, self.settings.value(key, getattr(config, key)))
        bg, fg = color("color_background"), color("color_foreground")
        self.word_color = color("color_highlight_word")
        size = self.settings.value("text_pixels", config.font_size_definitions, int)
        self.header_size = self.settings.value("header_pixels", config.font_size_header, int)
        family = self.settings.value("font_family", config.font_family)
        from PyQt6.QtGui import QRawFont, QFontDatabase
        for candidate in (family, "Segoe UI", "Noto Sans", "DejaVu Sans", QApplication.font().family()):
            if not candidate or candidate not in QFontDatabase.families():
                continue
            font = QFont(candidate)
            if all(QRawFont.fromFont(font).supportsCharacter(c) for c in "çğıöşüÇĞİÖŞÜ"):
                family = candidate
                break
        self.setStyleSheet("ClipboardWindow {background: transparent;}")
        opacity = self.settings.value("background_opacity", config.background_opacity, int)
        self.frame.setStyleSheet(frame_stylesheet(bg, fg, opacity, family) + f"""
            QTextBrowser {{background:transparent; color:{fg}; border:0; border-radius:0; padding:0;}}
            QLineEdit {{background:transparent; color:{fg}; border:0; padding:3px;}}
            QPushButton {{background:transparent; color:{fg}; border:0; padding:0;}}
            QPushButton:hover {{color:{self.word_color}; background:{bg};}}
            QPushButton:checked {{color:{self.word_color}; background:{bg};}}
            QPushButton:disabled {{color:#777;}}
            QPushButton::menu-indicator {{image:none; width:0;}}
        """)
        font = QFont(family)
        font.setPixelSize(size)
        self.browser.setFont(font)
        self.browser.document().setDefaultFont(font)
        self.search.setFont(font)

    def open_search(self):
        if not self.enabled:
            return
        self.dismiss()
        self.searching = True
        self.pinned = True
        self.search.show()
        self.browser.hide()
        self.search.clear()
        self.anchor = self.tray.geometry().center() if self.tray.geometry().isValid() else QCursor.pos()
        self.reposition = True
        self.resize(360, 76)
        self.place_popup(self.anchor)
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def open_settings(self):
        if self.isVisible():
            self.pin()
        from .settings import SettingsDialog
        SettingsDialog(self).exec()

    def start_setup(self, kind):
        if self.setup_thread is not None:
            self.tray.showMessage("meikipop-turkish setup", "Installation is already running.")
            return
        self.requests.next()
        self.holding = False
        self.scan_busy = False
        self.worker.queue.put(None)
        self.ocr_worker.queue.put(None)
        ocr_worker = self.ocr_worker
        worker = self.worker

        def install():
            # Release SQLite handles on their owning thread before replacing packs.
            worker.join()
            ocr_worker.join()
            try:
                run_setup(kind, worker.dictionary, worker.model_dir)
                message = "Installation complete. Ready to look up text."
            except Exception as error:
                message = f"Installation failed: {error}"
            self.signals.setup_completed.emit(message)

        self.setup_thread = threading.Thread(target=install, daemon=True, name="TurkishSetup")
        self.setup_status = "Installing… Lookup pauses until installation finishes. You can close Settings."
        self.signals.setup_progress.emit(self.setup_status)
        self.signals.setup_busy.emit(True)
        self.setup_thread.start()

    def setup_finished(self, message):
        self.setup_thread = None
        self.prefetch_failed = False
        self.ocr_results = None
        self.last_hit = None
        self.ocr_worker = OCRWorker(self.signals)
        self.ocr_worker.start()
        old = self.worker
        self.worker = TextWorker(self.signals, old.dictionary, old.analyzer, old.model_dir)
        self.worker.start()
        self.setup_status = message
        self.signals.setup_busy.emit(False)
        self.tray.showMessage("meikipop-turkish setup", message)

    def request_quit(self):
        if self.setup_thread is not None:
            self.tray.showMessage("meikipop-turkish setup", "Please wait for installation to finish before quitting.")
        else:
            QApplication.instance().quit()

    def dismiss(self):
        self.speech.stop()
        self.selection_ticket += 1
        self.leave_timer.stop()
        self.selection.cancel()
        self.searching = False
        self.search.hide()
        self.scan_busy = False
        self.requests.next()
        self.pinned = False
        self.holding = False
        self.suppress_hold = True
        self.result = None
        self.history.clear()
        self.back_button.setEnabled(False)
        self.browser.clear()
        self.hide()

    def closeEvent(self, event):
        self.dismiss()
        event.ignore()

    def shutdown(self):
        self.requests.next()
        self.scan_timer.stop()
        self.prefetch_timer.stop()
        QApplication.instance().removeEventFilter(self)
        QApplication.clipboard().dataChanged.disconnect(self.clipboard_changed)
        self.leave_timer.stop()
        self.selection.cancel()
        if self.input:
            self.input.shutdown()
        self.worker.queue.put(None)
        self.worker.join(timeout=3)
        self.ocr_worker.queue.put(None)
        self.ocr_worker.join(timeout=3)
        self.tray.hide()


def run_setup(kind, dictionary, model_dir=None):
    # pythonw has no stdout/stderr. Downloaders need real streams even without a console.
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    rollback = kind.startswith("rollback:")
    kind = kind.removeprefix("rollback:")
    commands = {"wiktionary": "setup-turkish-wiktionary", "dictionary": "build-turkish-dict", "model": "setup-turkish-model",
                "wordnet": "setup-turkish-wordnet", "ocr": "setup-turkish-ocr"}
    if getattr(sys, "frozen", False):
        args = [str(executable.with_name("meikipop-turkish-cli.exe")), "--setup", commands[kind]]
    else:
        args = [str(executable), "-m", "meikipop.scripts.turkish", commands[kind]]
    if rollback:
        args.append("--rollback")
    if kind == "dictionary":
        args.extend(["--output", str(Path(dictionary).parent)])
    if kind == "model" and model_dir:
        args.extend(["--model-dir", str(model_dir)])
    completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        if "PermissionError" in detail:
            raise RuntimeError("The data files are in use or not writable. Close other meikipop-turkish instances and retry.")
        raise RuntimeError(detail.splitlines()[-1] if detail else f"Installer exited with code {completed.returncode}")


def run_clipboard(dictionary, analyzer="stanza", model_dir=None, hotkey=None, search_hotkey=None):
    app = QApplication([])
    from meikipop.utils.paths import paths
    lock = QLockFile(str(Path(paths.data_dir) / "turkish-desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "meikipop-turkish", "meikipop-turkish is already running. Use its tray icon to open Settings or quit.")
        return 0
    app.setApplicationName("meikipop-turkish")
    app.setWindowIcon(QIcon(paths.get_resource_path("icon.ico")))
    app.setQuitOnLastWindowClosed(False)
    window = ClipboardWindow(dictionary, analyzer, model_dir, hotkey, search_hotkey)
    app.aboutToQuit.connect(window.shutdown)
    if not Path(dictionary).exists():
        QTimer.singleShot(0, window.open_settings)
    return app.exec()
