"""Turkish desktop popup with clipboard, local OCR, and offline dictionaries."""
from dataclasses import replace
from html import escape
import threading
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote

from PyQt6.QtCore import QObject, Qt, pyqtSignal, QTimer, QSettings, QPoint, QRect, QEvent, QLockFile
from PyQt6.QtGui import QCursor, QKeySequence, QShortcut, QImage, QIcon
from PyQt6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QMenu,
                            QPushButton, QSystemTrayIcon, QTextBrowser, QVBoxLayout, QWidget,
                            QStyle, QDialog, QFormLayout, QComboBox, QSpinBox, QLineEdit, QMessageBox)

from meikipop.dictionary.turkish_lookup import TurkishLookup
from meikipop.dictionary.turkish_store import TurkishStore
from meikipop.utils.lastest_queue import LatestValueQueue

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
    hold_changed = pyqtSignal(bool)
    dismissed = pyqtSignal()
    setup_completed = pyqtSignal(str)
    setup_busy = pyqtSignal(bool)
    setup_progress = pyqtSignal(str)


class TextWorker(threading.Thread):
    def __init__(self, signals, dictionary, analyzer, model_dir):
        super().__init__(daemon=True, name="TurkishLookup")
        self.signals = signals
        self.dictionary, self.analyzer, self.model_dir = Path(dictionary), analyzer, model_dir
        self.queue = LatestValueQueue()

    def run(self):
        store, lookup, wordnet, ocr = None, None, None, None
        try:
            while True:
                request = self.queue.get()
                if request is None:
                    break
                request_id, text, target, scan = request
                phase = "dictionary"
                try:
                    if lookup is None:
                        if store is None:
                            store = TurkishStore(self.dictionary)
                        lookup = TurkishLookup(store, self.analyzer, self.model_dir)
                    if scan is not None:
                        phase = "ocr"
                        from meikipop.ocr.turkish_paddle import LocalOCR
                        if ocr is None:
                            ocr = LocalOCR()
                        hit = ocr.lookup_point(*scan)
                        if hit is None:
                            self.signals.completed.emit(request_id, None, "No text under the pointer. Move onto a word and scan again.")
                            continue
                        text, offset = hit
                        target = next((i for i, token in enumerate(lookup.analyze(text))
                                       if token.start <= offset < token.end), None)
                        if target is None:
                            self.signals.completed.emit(request_id, None, "No selectable word under the pointer.")
                            continue
                    phase = "dictionary"
                    result = lookup.lookup(text, target)
                    from meikipop.dictionary.turkish_wordnet import WordNetStore, default_wordnet_path
                    try:
                        if wordnet is None:
                            wordnet = WordNetStore(default_wordnet_path())
                        words = [e["headword"] for e in result.entries]
                        if not words:
                            words = [text.strip()]
                            if result.target is not None:
                                token = result.tokens[result.target]
                                words.extend((text[token.start:token.end], token.lemma))
                        result = replace(result, wordnet=wordnet.lookup(words), wordnet_status="KeNet · Turkish WordNet")
                    except (OSError, ValueError, sqlite3.Error):
                        result = replace(result, wordnet_status="WordNet unavailable · install it in Settings")
                    self.signals.completed.emit(request_id, result, "")
                except Exception:
                    # No clipboard text or history is written to logs.
                    self.signals.completed.emit(request_id, None,
                        "Local OCR failed. Install OCR in Settings, then retry." if phase == "ocr" else
                        "Lookup failed. Check the dictionary path or run meikipop build-turkish-dict, then retry.")
        finally:
            if store is not None:
                store.close()
            if wordnet is not None:
                wordnet.close()


def render_result(result, show_more=False, examples=True):
    html = ['<style>a {color: #589bf0;} p {margin:6px 0;} h2 {margin:10px 0 4px;} li {margin-bottom:8px;}</style>']
    html.append(f"<p><small>{escape(result.status)}</small></p><p>")
    offset = 0
    for i, token in enumerate(result.tokens):
        html.append(escape(result.text[offset:token.start]).replace("\n", "<br>"))
        label = escape(result.text[token.start:token.end])
        if i == result.target:
            label = f"<b>{label}</b>"
        html.append(f'<a href="token:{i}">{label}</a>')
        offset = token.end
    html.append(escape(result.text[offset:]).replace("\n", "<br>") + "</p><hr>")
    if result.wordnet:
        html.append(f'<p><a href="section:wordnet">WordNet · {len(result.wordnet)} senses ↓</a></p>')
    if not result.entries:
        html.append("<p>No TDK entry found. Click another word above.</p>")
    if result.suggestions:
        html.append("<p><b>Did you mean?</b></p><ul>")
        for i, suggestion in enumerate(result.suggestions):
            html.append(f'<li><a href="suggestion:{i}">{escape(suggestion.headword)}</a>'
                        f' <small>via {escape(suggestion.candidate)}</small></li>')
        html.append("</ul>")
    for entry in result.entries:
        html.append(f"<h2>{escape(entry['headword'])}</h2>")
        match = next((m for m in result.matches if m.entry_id == entry["id"]), None)
        if match is not None:
            surface = result.text[match.start:match.end]
            label = " · casing retry" if match.route == "casing_lemma" else ""
            html.append(f"<p>{escape(surface)} → {escape(entry['headword'])}{label}</p>")
        elif result.target is not None:
            token = result.tokens[result.target]
            surface = result.text[token.start:token.end]
            html.append(f"<p>{escape(surface)} → {escape(token.lemma)} · {escape(token.pos or '')}</p>")
        html.append("<p><b>TDK · Türkçe</b></p><ol>")
        for sense in entry["senses"] if show_more else entry["senses"][:3]:
            tags = ", ".join(sense["labels"])
            html.append(f"<li><i>{escape(tags)}</i> {escape(sense['text'])}")
            if examples:
                for example in sense["examples"][:1]:
                    author = " — " + escape(example["author"]) if example["author"] else ""
                    html.append(f"<p>{escape(example['text'])}{author}</p>")
            html.append("</li>")
        html.append("</ol>")
        if not show_more and len(entry["senses"]) > 3:
            html.append('<p><a href="more:">Show all senses</a></p>')
        if entry["relations"]:
            if show_more:
                html.append("<p><b>Related expressions</b></p>")
                for i, rel in enumerate(entry["relations"]):
                    html.append(f'<p><a href="related:{entry["id"]}:{i}">{escape(rel["phrase"])}</a></p>')
            else:
                html.append('<p><a href="more:">Show related expressions</a></p>')
    if result.wordnet_status:
        html.append(f'<hr><a name="wordnet"></a><p><b>{escape(result.wordnet_status)}</b></p>')
    if result.wordnet:
        html.append("<p><small>Independent WordNet senses; not aligned to TDK senses.</small></p>")
        for group in result.wordnet if show_more else result.wordnet[:3]:
            html.append(f"<p><b>{escape(group['definition'])}</b> <small>{escape(group['pos'])}</small></p>")
            html.append(" · ".join(f'<a href="word:{quote(m["spelling"], safe="")}">{escape(m["spelling"])}</a>' for m in group["members"]))
            if examples and group.get("example"):
                html.append(f"<p>{escape(group['example'])}</p>")
            relations = group["relations"]
            labels = {"HYPERNYM": "Broader", "HYPONYM": "Narrower", "ANTONYM": "Antonyms"}
            for kind in dict.fromkeys(r["kind"] for r in relations):
                members = list(dict.fromkeys(r["spelling"] for r in relations if r["kind"] == kind))
                html.append(f'<p><small>{escape(labels.get(kind, kind.replace("_", " ").title()))}:</small> ')
                html.append(" · ".join(f'<a href="word:{quote(w, safe="")}">{escape(w)}</a>' for w in (members if show_more else members[:5])) + "</p>")
        if not show_more:
            html.append('<p><a href="more:">Show all WordNet senses and relations</a></p>')
    return "".join(html)


class ClipboardWindow(QWidget):
    def __init__(self, dictionary, analyzer="stanza", model_dir=None, hotkey="<ctrl>+<alt>+l"):
        super().__init__()
        self.settings = QSettings("Meikipop", "Turkish")
        self.setWindowTitle("Meikipop · Turkish")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(self.settings.value("width", 540, int), self.settings.value("height", 540, int))
        self.pinned = False
        self.holding = False
        self.suppress_hold = False
        self.last_scan = None
        self.scan_busy = False
        self.anchor = QCursor.pos()
        self.last_clipboard = QApplication.clipboard().text()
        self.hotkey = hotkey
        self.hold_key = self.settings.value("hold_key", "shift")
        self.setup_thread = None
        self.setup_status = ""
        self.requests = RequestState()
        self.result = None
        self.history = []
        self.show_more = False
        self.signals = Signals(self)
        self.signals.clipboard_requested.connect(self.read_clipboard)
        self.signals.completed.connect(self.deliver)
        self.signals.hold_changed.connect(self.set_hold)
        self.signals.dismissed.connect(self.dismiss)
        self.signals.setup_completed.connect(self.setup_finished)
        self.worker = TextWorker(self.signals, dictionary, analyzer, model_dir)
        self.worker.start()
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.back_button = QPushButton("←")
        self.back_button.setFixedWidth(32)
        self.back_button.setToolTip("Previous lookup")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(self.go_back)
        lookup = QPushButton("Clipboard")
        lookup.clicked.connect(self.read_clipboard)
        self.examples = QCheckBox("Examples")
        self.examples.setChecked(self.settings.value("examples", True, bool))
        self.examples.toggled.connect(self.render)
        self.examples.toggled.connect(lambda value: self.settings.setValue("examples", value))
        self.pin_button = QPushButton("Pin")
        self.pin_button.clicked.connect(self.pin)
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self.open_settings)
        close = QPushButton("×")
        close.setToolTip("Dismiss (Escape)")
        close.setFixedWidth(32)
        close.clicked.connect(self.dismiss)
        for widget in (self.back_button, lookup, self.pin_button, settings_button, close):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.hint = QLabel(f"Copy to pin · Hold {self.hold_key.title()} to scan · Click to pin · Escape to dismiss")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a Turkish word or sentence…")
        self.search.setMaxLength(MAX_TEXT)
        self.search.returnPressed.connect(lambda: self.submit(self.search.text()))
        layout.addWidget(self.search)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self.navigate)
        self.browser.setHtml("<h2>Turkish clipboard lookup</h2><p>Copy a word or sentence. "
                             "Click words in the result to explore their definitions.</p>")
        layout.addWidget(self.browser)
        self.apply_appearance()
        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.activated.connect(self.dismiss)
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView), self)
        self.tray.setToolTip("Meikipop Turkish clipboard")
        menu = QMenu(self)
        action = menu.addAction("Look up clipboard")
        action.triggered.connect(self.read_clipboard)
        show = menu.addAction("Show window")
        show.triggered.connect(self.show)
        self.auto_action = menu.addAction("Look up copied text automatically")
        self.auto_action.setCheckable(True)
        self.auto_action.setChecked(self.settings.value("auto_clipboard", True, bool))
        self.auto_action.toggled.connect(self.toggle_clipboard)
        menu.addAction("Settings").triggered.connect(self.open_settings)
        quit_action = menu.addAction("Quit Turkish mode")
        quit_action.triggered.connect(self.request_quit)
        self.tray.setContextMenu(menu)
        self.tray.show()
        QApplication.clipboard().dataChanged.connect(self.clipboard_changed)
        QApplication.instance().installEventFilter(self)
        self.scan_timer = QTimer(self)
        self.scan_timer.setInterval(300)
        self.scan_timer.timeout.connect(self.scan_pointer)
        self.scan_timer.start()
        self.listener = None
        self.key_listener = None
        try:
            from pynput.keyboard import GlobalHotKeys, Listener, Key
            self.listener = GlobalHotKeys({hotkey: self.signals.clipboard_requested.emit})
            self.listener.start()
            pressed = set()

            def update(key, down):
                if down:
                    pressed.add(key)
                else:
                    pressed.discard(key)
                if key == Key.esc and down:
                    self.signals.dismissed.emit()
                modifiers = {Key.shift, Key.shift_l, Key.shift_r} if self.hold_key == "shift" else {Key.alt, Key.alt_l, Key.alt_r}
                blocked = {Key.ctrl, Key.ctrl_l, Key.ctrl_r, Key.cmd, Key.cmd_l, Key.cmd_r}
                self.signals.hold_changed.emit(bool(pressed & modifiers) and not bool(pressed & blocked))

            self.key_listener = Listener(on_press=lambda k: update(k, True), on_release=lambda k: update(k, False))
            self.key_listener.start()
        except Exception:
            self.hint.setText("Global shortcut unavailable. Use Look up clipboard here or in the tray.")

    def read_clipboard(self):
        self.holding = False
        self.suppress_hold = True
        self.anchor = QCursor.pos()
        self.submit(QApplication.clipboard().text())

    def submit(self, text, target=None, scan=None, peek=False, remember=True):
        if self.setup_thread is not None:
            self.tray.showMessage("Meikipop", "Installation is running. Lookup resumes when it finishes.")
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
        self.pin_button.setText("Pinned" if self.pinned else "Pin")
        self.place_popup(self.anchor)
        self.show()
        if scan is None and (not text.strip() or len(text) > MAX_TEXT):
            self.result = None
            self.browser.setPlainText("Copy some text first." if not text.strip() else "Please copy at most 2,000 characters.")
            return
        self.result = None
        self.show_more = False
        self.browser.setPlainText("Reading screen locally… First model load can take a moment." if scan is not None else
                                  "Looking up… First Stanza model load can take a moment.")
        self.worker.queue.put((request_id, text, target, scan))

    def deliver(self, request_id, result, error):
        if request_id == getattr(self, "scan_request", None):
            self.scan_busy = False
        if not self.requests.accepts(request_id):
            return
        self.result = result
        if error:
            self.browser.setPlainText(error)
        else:
            self.render()

    def render(self):
        if self.result is not None:
            self.browser.setHtml(render_result(self.result, self.show_more, self.examples.isChecked()))

    def navigate(self, url):
        if self.result is None:
            return
        self.pin()
        if url.scheme() == "section":
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

    def toggle_clipboard(self, enabled):
        self.settings.setValue("auto_clipboard", enabled)
        self.last_clipboard = QApplication.clipboard().text()

    def clipboard_changed(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        previous, self.last_clipboard = self.last_clipboard, text
        if (not self.auto_action.isChecked() or text == previous or not text.strip()
                or len(text) > MAX_TEXT or QApplication.activeWindow() is not None):
            return
        self.anchor = QCursor.pos()
        self.holding = False
        self.suppress_hold = True
        self.submit(text)

    def pin(self):
        self.pinned = True
        self.pin_button.setText("Pinned")

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget)
                and (watched is self or self.isAncestorOf(watched))):
            self.pin()
        return super().eventFilter(watched, event)

    def place_popup(self, anchor):
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.resize(min(self.settings.value("width", 540, int), area.width()),
                    min(self.settings.value("height", 540, int), area.height()))
        x, y = anchor.x() + 18, anchor.y() + 24
        if x + self.width() > area.right() + 1:
            x = anchor.x() - self.width() - 18
        if y + self.height() > area.bottom() + 1:
            y = anchor.y() - self.height() - 24
        self.move(max(area.left(), min(x, area.right() + 1 - self.width())),
                  max(area.top(), min(y, area.bottom() + 1 - self.height())))

    def set_hold(self, active):
        if not active:
            self.suppress_hold = False
        if self.suppress_hold or active == self.holding:
            return
        self.holding = active
        if active:
            self.last_scan = None
            self.scan_pointer()
        elif not self.pinned:
            self.requests.next()
            self.hide()

    def scan_pointer(self):
        if self.setup_thread is not None or not self.holding or self.scan_busy or QApplication.activeModalWidget():
            return
        point = QCursor.pos()
        if self.isVisible() and self.geometry().contains(point):
            return
        if self.last_scan is not None and (point - self.last_scan).manhattanLength() < 14:
            return
        self.last_scan = QPoint(point)
        self.anchor = QPoint(point)
        self.hide()
        generation = self.requests.next()
        self.scan_busy = True
        self.scan_request = generation
        QTimer.singleShot(60, lambda: self.capture_pointer(point, generation))

    def capture_pointer(self, point, generation):
        if not self.requests.accepts(generation) or not self.holding:
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
            region = QRect(point.x() - 440, point.y() - 110, 880, 220).intersected(geometry)
            image = pixmap.toImage().copy(
                round((region.x() - geometry.x()) * sx), round((region.y() - geometry.y()) * sy),
                round(region.width() * sx), round(region.height() * sy)).convertToFormat(QImage.Format.Format_RGB888)
            bits = image.bits()
            bits.setsize(image.sizeInBytes())
            pixels = np.frombuffer(bits, dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
            pixels = pixels[:, :image.width() * 3].reshape(image.height(), image.width(), 3)[:, :, ::-1].copy()
            target = ((point.x() - region.x()) * sx, (point.y() - region.y()) * sy)
            self.submit("", scan=(pixels, target), peek=True)
            self.scan_request = self.requests.current
        except Exception:
            self.scan_busy = False
            self.submit("")
            self.browser.setPlainText("Screen capture failed. You can still copy text to look it up.")

    def apply_appearance(self):
        dark = self.settings.value("theme", "dark") == "dark"
        bg, fg, border = ("#20232b", "#edf0f5", "#404756") if dark else ("#fafafa", "#202530", "#c7ccd4")
        size = self.settings.value("font_size", 12, int)
        self.setStyleSheet(f"QWidget {{background:{bg}; color:{fg}; font-family:'Segoe UI'; font-size:{size}pt;}} "
                           f"QPushButton,QComboBox,QSpinBox,QLineEdit {{padding:5px; border:1px solid {border}; border-radius:5px;}} "
                           f"QTextBrowser {{border:1px solid {border}; padding:8px;}} QPushButton:hover {{border-color:#589bf0;}}")
        self.browser.document().setDefaultStyleSheet(f"body {{font-size:{size}pt;}} a {{color:#589bf0;}}")

    def open_settings(self):
        self.pin()
        dialog = QDialog(self)
        dialog.setWindowTitle("Meikipop · Turkish settings")
        form = QFormLayout(dialog)
        automatic = QCheckBox("Open a pinned popup when I copy text")
        automatic.setChecked(self.auto_action.isChecked())
        automatic.toggled.connect(self.auto_action.setChecked)
        form.addRow(automatic)
        examples = QCheckBox("Show examples")
        examples.setChecked(self.examples.isChecked())
        examples.toggled.connect(self.examples.setChecked)
        form.addRow(examples)
        theme = QComboBox()
        theme.addItems(["dark", "light"])
        theme.setCurrentText(self.settings.value("theme", "dark"))
        form.addRow("Theme", theme)
        hold = QComboBox()
        hold.addItems(["shift", "alt"])
        hold.setCurrentText(self.hold_key)
        form.addRow("Hold to scan locally", hold)
        fields = {}
        for key, label, minimum, maximum, default in (("font_size", "Text size", 9, 24, 12),
                ("width", "Popup width", 380, 1000, 540), ("height", "Popup height", 280, 1000, 540)):
            field = QSpinBox()
            field.setRange(minimum, maximum)
            field.setValue(self.settings.value(key, default, int))
            form.addRow(label, field)
            fields[key] = field
        shortcut = QLabel(f"Clipboard shortcut: {self.hotkey}\nOCR: local PaddleOCR 3.7.0 · PP-OCRv6 small · CPU\nDownloads happen only when you press Install.")
        shortcut.setWordWrap(True)
        form.addRow(shortcut)
        from meikipop.dictionary.turkish_wordnet import default_wordnet_path
        from meikipop.ocr.turkish_paddle import model_root
        status = QLabel(f"TDK: {'installed' if self.worker.dictionary.exists() else 'missing'}\n"
                        f"WordNet: {'installed' if default_wordnet_path().exists() else 'missing'}\n"
                        f"OCR models: {'installed' if (model_root() / 'manifest.json').exists() else 'missing'}")
        form.addRow(status)
        self.signals.setup_completed.connect(status.setText)
        for key, label in (("dictionary", "Install TDK"), ("wordnet", "Install WordNet"),
                           ("model", "Install Stanza models"), ("ocr", "Install local OCR models")):
            button = QPushButton(label)
            button.clicked.connect(lambda _, k=key: self.start_setup(k))
            button.clicked.connect(lambda: status.setText("Installing… You can close Settings while setup runs."))
            form.addRow(button)
        form.addRow(QLabel("KeNet / StarlangSoftware · GPL-3.0\nTDK snapshot: ogun/guncel-turkce-sozluk v12"))
        done = QPushButton("Save settings")
        form.addRow(done)

        def save():
            for key, field in fields.items():
                self.settings.setValue(key, field.value())
            self.settings.setValue("theme", theme.currentText())
            self.hold_key = hold.currentText()
            self.settings.setValue("hold_key", self.hold_key)
            self.hint.setText(f"Copy to pin · Hold {self.hold_key.title()} to scan · Click to pin · Escape to dismiss")
            self.apply_appearance()
            self.place_popup(self.anchor)
            self.render()
            dialog.accept()

        done.clicked.connect(save)
        dialog.exec()

    def start_setup(self, kind):
        if self.setup_thread is not None:
            self.tray.showMessage("Meikipop setup", "Installation is already running.")
            return
        self.requests.next()
        self.holding = False
        self.scan_busy = False
        self.worker.queue.put(None)
        worker = self.worker

        def install():
            # Release SQLite handles on their owning thread before replacing packs.
            worker.join()
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
        old = self.worker
        self.worker = TextWorker(self.signals, old.dictionary, old.analyzer, old.model_dir)
        self.worker.start()
        self.setup_status = message
        self.signals.setup_busy.emit(False)
        self.tray.showMessage("Meikipop setup", message)

    def request_quit(self):
        if self.setup_thread is not None:
            self.tray.showMessage("Meikipop setup", "Please wait for installation to finish before quitting.")
        else:
            QApplication.instance().quit()

    def dismiss(self):
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
        QApplication.instance().removeEventFilter(self)
        QApplication.clipboard().dataChanged.disconnect(self.clipboard_changed)
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=2)
        if self.key_listener:
            self.key_listener.stop()
            self.key_listener.join(timeout=2)
        self.worker.queue.put(None)
        self.worker.join(timeout=3)
        self.tray.hide()


def run_setup(kind, dictionary, model_dir=None):
    # pythonw has no stdout/stderr. Downloaders need real streams even without a console.
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    commands = {"dictionary": "build-turkish-dict", "model": "setup-turkish-model",
                "wordnet": "setup-turkish-wordnet", "ocr": "setup-turkish-ocr"}
    args = [str(executable), "-m", "meikipop.scripts.turkish", commands[kind]]
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
            raise RuntimeError("The data files are in use or not writable. Close other Meikipop instances and retry.")
        raise RuntimeError(detail.splitlines()[-1] if detail else f"Installer exited with code {completed.returncode}")


def run_clipboard(dictionary, analyzer="stanza", model_dir=None, hotkey="<ctrl>+<alt>+l"):
    app = QApplication([])
    from meikipop.utils.paths import paths
    lock = QLockFile(str(Path(paths.data_dir) / "turkish-desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "Meikipop", "Turkish mode is already running. Use its tray icon to open Settings or quit.")
        return 0
    app.setWindowIcon(QIcon(paths.get_resource_path("icon.ico")))
    app.setQuitOnLastWindowClosed(False)
    window = ClipboardWindow(dictionary, analyzer, model_dir, hotkey)
    app.aboutToQuit.connect(window.shutdown)
    window.place_popup(QCursor.pos())
    window.show()
    return app.exec()
