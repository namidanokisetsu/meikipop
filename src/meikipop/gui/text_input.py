"""Standalone Turkish clipboard mode: no OCR, capture lock, or Japanese setup."""
from html import escape
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QMenu,
                            QPushButton, QSystemTrayIcon, QTextBrowser, QVBoxLayout, QWidget,
                            QStyle)

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


class TextWorker(threading.Thread):
    def __init__(self, signals, dictionary, analyzer, model_dir):
        super().__init__(daemon=True, name="TurkishLookup")
        self.signals = signals
        self.dictionary, self.analyzer, self.model_dir = dictionary, analyzer, model_dir
        self.queue = LatestValueQueue()

    def run(self):
        store, lookup = None, None
        try:
            while True:
                request = self.queue.get()
                if request is None:
                    break
                request_id, text, target = request
                try:
                    if lookup is None:
                        if store is None:
                            store = TurkishStore(self.dictionary)
                        lookup = TurkishLookup(store, self.analyzer, self.model_dir)
                    result = lookup.lookup(text, target)
                    self.signals.completed.emit(request_id, result, "")
                except Exception:
                    # No clipboard text or history is written to logs.
                    self.signals.completed.emit(request_id, None,
                        "Lookup failed. Check the dictionary path or run meikipop build-turkish-dict, then retry.")
        finally:
            if store is not None:
                store.close()


def render_result(result, show_more=False, examples=True):
    html = ['<style>body {font-size: 12pt;} a {color: #3978c6;} li {margin-bottom: 12px;}</style>']
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
    return "".join(html)


class ClipboardWindow(QWidget):
    def __init__(self, dictionary, analyzer="stanza", model_dir=None, hotkey="<ctrl>+<alt>+l"):
        super().__init__()
        self.setWindowTitle("Meikipop · Turkish clipboard")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(620, 650)
        self.requests = RequestState()
        self.result = None
        self.show_more = False
        self.signals = Signals(self)
        self.signals.clipboard_requested.connect(self.read_clipboard)
        self.signals.completed.connect(self.deliver)
        self.worker = TextWorker(self.signals, dictionary, analyzer, model_dir)
        self.worker.start()
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        lookup = QPushButton("Look up clipboard")
        lookup.clicked.connect(self.read_clipboard)
        self.examples = QCheckBox("Examples")
        self.examples.setChecked(True)
        self.examples.toggled.connect(self.render)
        close = QPushButton("Close")
        close.clicked.connect(self.dismiss)
        for widget in (lookup, self.examples, close):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.hint = QLabel(f"Copy Turkish text, then press {hotkey} or use the button.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self.navigate)
        self.browser.setHtml("<h2>Turkish clipboard lookup</h2><p>Copy a word or sentence. "
                             "Click words in the result to explore their definitions.</p>")
        layout.addWidget(self.browser)
        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.activated.connect(self.dismiss)
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView), self)
        self.tray.setToolTip("Meikipop Turkish clipboard")
        menu = QMenu(self)
        action = menu.addAction("Look up clipboard")
        action.triggered.connect(self.read_clipboard)
        show = menu.addAction("Show window")
        show.triggered.connect(self.show)
        quit_action = menu.addAction("Quit Turkish mode")
        quit_action.triggered.connect(QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.show()
        self.listener = None
        try:
            from pynput.keyboard import GlobalHotKeys
            self.listener = GlobalHotKeys({hotkey: self.signals.clipboard_requested.emit})
            self.listener.start()
        except Exception:
            self.hint.setText("Global shortcut unavailable. Use Look up clipboard here or in the tray.")

    def read_clipboard(self):
        self.submit(QApplication.clipboard().text())

    def submit(self, text, target=None):
        request_id = self.requests.next()
        if not self.isVisible():
            self.move(QCursor.pos())
        self.show()
        if not text.strip() or len(text) > MAX_TEXT:
            self.result = None
            self.browser.setPlainText("Copy some text first." if not text.strip() else "Please copy at most 2,000 characters.")
            return
        self.result = None
        self.show_more = False
        self.browser.setPlainText("Looking up… First Stanza model load can take a moment.")
        self.worker.queue.put((request_id, text, target))

    def deliver(self, request_id, result, error):
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
        if url.scheme() == "token":
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

    def dismiss(self):
        self.requests.next()
        self.result = None
        self.browser.clear()
        self.hide()

    def closeEvent(self, event):
        self.dismiss()
        event.ignore()

    def shutdown(self):
        self.requests.next()
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=2)
        self.worker.queue.put(None)
        self.worker.join(timeout=3)
        self.tray.hide()


def run_clipboard(dictionary, analyzer="stanza", model_dir=None, hotkey="<ctrl>+<alt>+l"):
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = ClipboardWindow(dictionary, analyzer, model_dir, hotkey)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()
