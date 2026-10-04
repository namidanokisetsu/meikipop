"""Compact, shared dictionary surface with a latest-request background worker."""
from collections import OrderedDict
from html import escape
from urllib.parse import quote
import re
import math
import sys
import threading

from PyQt6.QtCore import QObject, QEvent, QSettings, QSignalBlocker, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from meikipop.config.config import config
from meikipop.dictionary.search import SearchEngine, SearchResult
from meikipop.gui.popup_style import frame_stylesheet, popup_position, surface_colors
from meikipop.gui.action_icons import action_icon
from meikipop.gui.turkish.browser import DictionaryBrowser
from meikipop.scripts.import_yomitan_dict_html import StructuredContentConverter


LANGUAGE_NAMES = {
    "ja": "日本語", "tr": "Türkçe", "en": "English", "de": "Deutsch",
    "fr": "Français", "es": "Español", "ru": "Русский", "zh": "中文",
    "ko": "한국어", "ar": "العربية", "it": "Italiano", "pt": "Português",
    "uk": "Українська", "nl": "Nederlands", "pl": "Polski",
}


def language_name(code):
    return LANGUAGE_NAMES.get(code, code)


def is_sentence(text):
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    return len(words) > 2 or bool(re.search(r"[。！？!?\n]", text.strip())) or "、" in text


class LookupWorker(QObject):
    completed = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)
    languages = pyqtSignal(object)

    def __init__(self, directory=None, engine_factory=None):
        super().__init__()
        self._factory = engine_factory or (lambda: SearchEngine(directory))
        self._condition = threading.Condition()
        self._pending = None
        self._refresh = True
        self._stopped = False
        self._engine = None
        self._thread = threading.Thread(target=self._run, name="dictionary-search", daemon=True)

    def start(self):
        self._thread.start()

    def request(self, revision, text, source, foreign, translate=False, target=None, pair=None, translation_settings=None):
        self.cancel()
        with self._condition:
            self._pending = (revision, text, source, foreign, translate, target, pair, translation_settings)
            self._condition.notify()

    def cancel(self):
        with self._condition:
            self._pending = None
            translator = getattr(self._engine, "translator", None)
        cancel = getattr(translator, "cancel", None)
        if callable(cancel):
            cancel()

    def refresh(self):
        with self._condition:
            self._refresh = True
            self._condition.notify()

    def shutdown(self):
        self.cancel()
        with self._condition:
            self._stopped = True
            self._pending = None
            self._condition.notify()

    def _emit(self, signal, *args):
        with self._condition:
            if self._stopped:
                return
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # The application may have closed while a local model was running.

    def _run(self):
        engine = None
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stopped or self._pending is not None or self._refresh)
                    if self._stopped:
                        return
                    pending, self._pending = self._pending, None
                    refresh, self._refresh = self._refresh, False
                try:
                    if engine is None:
                        engine = self._factory()
                        with self._condition:
                            self._engine = engine
                            if self._stopped:
                                return
                    elif refresh:
                        engine.refresh()
                    if refresh:
                        codes = sorted({meta["language"] for _, meta, _ in engine.library.packs})
                        self._emit(self.languages, codes)
                    if pending is not None:
                        revision, text, source, foreign, translate, target, pair, translation_settings = pending
                        options = {"target": target} if target else {}
                        if pair:
                            options.update(pair=pair, translation_settings=translation_settings)
                        result = engine.search(text, source=source, foreign=foreign, translate=translate, **options)
                        self._emit(self.completed, revision, result)
                except Exception as error:
                    self._emit(self.failed, pending[0] if pending else -1, str(error))
        finally:
            if engine is not None:
                engine.close()


class _GlossConverter(StructuredContentConverter):
    """Prune structured previews before conversion, retaining lists and emphasis."""
    def __init__(self, expanded=False, limit=360, preview=False, generic_source=False):
        super().__init__()
        self.expanded = expanded
        self.preview = preview
        self.generic_source = generic_source
        self.first_source = ""
        self.remaining = limit
        self.clipped = False

    def _node_to_html(self, node):
        if isinstance(node, str):
            if not self.expanded:
                text = node[:self.remaining]
                self.remaining -= len(text)
                if len(text) < len(node):
                    self.clipped = True
                    text += "…" if text else ""
                node = text
            return super()._node_to_html(node)
        if isinstance(node, list):
            parts = []
            for child in node:
                if not self.expanded and self.remaining <= 0:
                    self.clipped = True
                    break
                parts.append(self._node_to_html(child))
            return "".join(parts)
        if isinstance(node, dict):
            node = dict(node)
            tag, content = node.get("tag", ""), node.get("content")
            data = node.get("data", {})
            kind = str(data.get("content", "")) if isinstance(data, dict) else ""
            style = node.get("style", {})
            style = style if isinstance(style, dict) else {}
            heading_text = content[0] if isinstance(content, list) and len(content) == 1 else content
            source_heading = (isinstance(heading_text, str) and heading_text.strip() in
                              ("Tureng", "Wiktionary", "TDK", "KeNet", "Etymology")
                              and (tag in ("b", "strong") or style.get("fontWeight") in ("bold", "700")))
            if source_heading and self.generic_source:
                if not self.first_source:
                    self.first_source = heading_text.strip()
                    return ""
                if self.preview:
                    return ""
            # Turkdict's exporter retains this presentation signature for
            # examples, translations and sense context, but no CSS class name.
            turkdict_example = (tag == "div" and style.get("fontSize") == "0.9em"
                                and style.get("marginTop") == "0.1em")
            if not self.expanded:
                if self.preview and kind in ("forms", "attribution", "extra-info"):
                    self.clipped = True
                    return ""
                if tag == "details" or "example" in kind.lower() or turkdict_example:
                    self.clipped = True
                    return ""
                if (tag in ("ol", "ul") or kind == "glosses") and isinstance(content, list):
                    senses = [child for child in content if not isinstance(child, str) or child.strip()]
                    if len(senses) > 2:
                        node["content"] = senses[:2]
                        self.clipped = True
            if kind == "glossary":
                children = node.get("content")
                children = children if isinstance(children, list) else [children]
                return "; ".join(filter(None, (self._node_to_html(
                    child.get("content") if isinstance(child, dict) and child.get("tag") == "li" else child)
                    for child in children)))
            if isinstance(data, dict) and data.get("class") == "tag":
                return "<small>" + self._node_to_html(content) + "</small> "
            if kind in ("sense-groups", "sense-group"):
                tag = node["tag"] = "div"
            # Keep a small, safe subset of typography. Dictionary CSS must not
            # inject attributes, override the theme or stretch the popup.
            safe_style = {}
            for name, values in (("fontStyle", ("italic", "normal")),
                                 ("fontWeight", ("bold", "normal", "400", "700"))):
                if style.get(name) in values:
                    safe_style[name] = style[name]
            size = style.get("fontSize", "")
            if isinstance(size, str) and re.fullmatch(r"0?\.[7-9]em", size):
                safe_style["fontSize"] = size
            if tag in ("div", "p", "details", "summary"):
                node["tag"] = "div"
                safe_style.update(marginTop="1px", marginBottom="1px")
            node["style"] = safe_style
            # No source-controlled attributes reach the converter.
            node["data"] = {}
            return super()._node_to_html(node)
        return super()._node_to_html(node)

    def glosses(self, definitions):
        parts = []
        for definition in definitions:
            if isinstance(definition, str):
                content = definition.strip()
            elif isinstance(definition, dict) and definition.get("type") in ("text", "structured-content"):
                content = definition.get("text" if definition["type"] == "text" else "content")
            else:
                continue
            rendered = self._node_to_html(content)
            if rendered:
                parts.append(rendered)
        return parts


def _metadata(entries):
    frequencies, inflections = OrderedDict(), OrderedDict()
    for entry in entries:
        for frequency in entry.frequencies:
            label = frequency.label or (f"{frequency.rank:g}" if frequency.rank is not None else "")
            if (frequency.rank is not None and frequency.mode == "rank-based"
                    and re.fullmatch(r"[\d,.]+", label)):
                label = f"#{label}"
            frequencies.setdefault((frequency.source, label), None)
        for step in entry.inflection:
            label = (re.sub(r"\([^)]*\)", "", str(step)) if entry.language == "ja" else str(step)).strip()
            if label and not label.startswith("stem-"):
                inflections.setdefault(label, None)
    parts = []
    if frequencies:
        muted = surface_colors(config.color_background, config.color_foreground)["muted"]
        parts.extend(f'<a href="frequency:{quote(source + ": " + label)}" style="color:{muted}">{escape(label)}</a>'
                     for source, label in frequencies)
    if inflections:
        parts.append(escape(" · ".join(inflections)))
    return '<p class="metadata"><small>' + " · ".join(parts) + '</small></p>' if parts else ""


def _source_name(source):
    return re.sub(r"\s*\[\d{4}[^\]]*\]", "", source).replace("Jitendex.org", "Jitendex").strip()


def render_result(result, expanded=(), kanji_expanded=False, preview=False):
    """Share lexical headings while preserving the configured dictionary order."""
    muted = surface_colors(config.color_background, config.color_foreground)["muted"]
    groups, sources = OrderedDict(), list(dict.fromkeys(entry.source for entry in result.entries))
    for entry in result.entries:
        if preview and (entry.source != sources[0] or groups and (entry.term, entry.reading) not in groups):
            continue
        groups.setdefault((entry.term, entry.reading), OrderedDict()).setdefault(entry.source, []).append(entry)
    parts = [f'<style>body {{color:{config.color_foreground};}} '
             f'a,h2 {{color:{config.color_highlight_word};text-decoration:none;}} '
             f'h2 {{font-size:{config.font_size_header}px;font-weight:normal;margin:3px 0;}} '
             'p {margin:2px 0;} ol,ul {margin:2px 0 4px 8px;padding:0;} '
             'li {margin:1px 0;} hr {margin:6px 0;} '
             f'.metadata {{margin:1px 0 3px;color:{muted};}} .source {{margin:5px 0 2px;color:{muted};}}</style>']
    if result.translation:
        parts.append(f'<p>{escape(result.text).replace(chr(10), "<br>")}</p><hr>')
        parts.append(f'<p>{escape(result.translation).replace(chr(10), "<br>")}</p>')
        if result.entries:
            parts.append("<hr>")
    anchored = set()
    for group_index, ((term, reading), dictionaries) in enumerate(groups.items()):
        if group_index:
            parts.append("<hr>")
        display_reading = f"[{reading}]" if result.source == "ja" else reading
        reading_html = (f' <span style="color:{config.color_highlight_reading};font-size:'
                        f'{max(12, config.font_size_header - 3)}px">{escape(display_reading)}</span>'
                        if reading and reading != term else "")
        parts.append(f'<h2>{escape(term)}{reading_html}</h2>')
        parts.append(_metadata(entry for entries in dictionaries.values() for entry in entries))
        if preview and result.source == "tr":
            alternatives = tuple(dict.fromkeys(f"{other.term} · {' · '.join(other.inflection)}"
                                 for other in result.entries if other.term != term and other.inflection))[:3]
            if alternatives:
                parts.append('<p class="metadata"><small>' + escape(" OR ".join(alternatives)) + '</small></p>')
        for source in sources:
            if source not in dictionaries:
                continue
            index, entries = sources.index(source), dictionaries[source]
            full, more = source in expanded and not preview, len(entries) > 2
            generic_source = source in ("Turkish Bilingual", "Turkish Monolingual", "Turkish Etymology")
            converter = _GlossConverter(expanded=full, limit=180 if preview else 360, preview=preview,
                                        generic_source=generic_source)
            definitions = []
            for entry in entries if full else entries[:2]:
                more = more or len(entry.definitions) > 3
                definitions.extend(converter.glosses(entry.definitions if full else entry.definitions[:3]))
            more = more or converter.clipped
            toggle = (f' <a href="expand:{index}" title="{"Collapse" if full else "Expand"}">'
                      f'{"−" if full else "+"}</a>'
                      if more or full else "")
            if source not in anchored:
                parts.append(f'<a name="dictionary-{index}"></a>')
                anchored.add(source)
            if not preview:
                label = converter.first_source or _source_name(source)
                parts.append(f'<p class="source"><small><span title="{escape(source, quote=True)}">'
                             f'{escape(label)}</span>{toggle}</small></p>')
            if len(definitions) > 1:
                parts.append("<ol>" + "".join(f"<li>{gloss}</li>" for gloss in definitions) + "</ol>")
            else:
                parts.append("".join(f"<div>{gloss}</div>" for gloss in definitions))
    if result.suggestions:
        parts.append('<p>Did you mean: ' + " · ".join(
            f'<a href="suggest:{index}">{escape(str(word))}</a>'
            for index, word in enumerate(result.suggestions)) + "</p>")
    if result.message:
        parts.append(f"<p>{escape(result.message)}</p>")
    if result.kanji and not preview:
        from meikipop.gui.kanji_panel import render_kanji
        parts.append('<a name="kanji"></a>' + render_kanji(result.kanji, compact_only=True))
    if not result.entries and not result.translation and not result.message and result.text:
        parts.append("<p>No entry found.</p>")
    return "".join(parts)


class LocalDictionaryBrowser(DictionaryBrowser):
    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    def loadResource(self, resource_type, name):
        # Dictionary content is text; embedded local/network resources are unnecessary.
        return None


class QuickLookupWindow(QDialog):
    mode_changed = pyqtSignal(str)
    ocr_enabled_changed = pyqtSignal(bool)
    scan_settings_changed = pyqtSignal()
    hotkey_requested = pyqtSignal()
    selection_requested = pyqtSignal()
    clipboard_requested = pyqtSignal()

    def __init__(self, directory=None, engine_factory=None, settings=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        if QApplication.platformName() == "xcb":
            self.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint)
        self.directory = directory
        self.settings = settings or QSettings("Meikipop", "QuickLookup")
        from meikipop.gui.profile_appearance import load_appearance
        load_appearance(self.settings, self.settings.value("profile", self.settings.value("source", "ja")))
        self.revision = 0
        self._result = None
        self._context = ""
        self._peek = False
        self._history = []
        self._new_chain = True
        self._expanded = set()
        self._kanji_expanded = False
        self._pin_anchor_click = False
        self._keys = None
        self._shutting_down = False
        self._drag_position = None
        self._setup = None
        self._engine_factory = engine_factory
        self.translation_worker = None
        self._pending_context_translation = None
        self._translation_busy = False
        self._last_request_translate = False
        self.audio = None
        self.tray_geometry = None
        self._manual_at_cursor = False
        self._opening_search = False
        self._previous_foreground = None
        self._passive_text = False
        self._selection_passive = False
        self._selection_for_search = False
        self.setWindowTitle("Meikipop")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(340, 190)
        self.resize(480, 340)
        self._normal_size = QSize(480, 340)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        outer.addWidget(self.frame)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        self.actions_row = QWidget()
        toolbar = QHBoxLayout(self.actions_row)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(2)
        self.back = self._action("back", "Back")
        self.back.setEnabled(False)
        self.back.clicked.connect(self.go_back)
        toolbar.addWidget(self.back)
        self.title = QLabel("")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.linkActivated.connect(self._history_jump)
        self.title.setMinimumWidth(0)
        self.title.installEventFilter(self)
        toolbar.addWidget(self.title, 1)
        self.scan_toggle = QCheckBox(self)
        self.scan_toggle.setToolTip("Screen lookup with your configured scan key")
        self.scan_toggle.toggled.connect(self.ocr_enabled_changed)
        self.scan_toggle.hide()
        self.pin = self._action("pin", "Pin")
        self.pin.setCheckable(True)
        self.pin.setParent(self)
        self.pin.hide()
        self.pin.setToolTip("Keep this result open and resize it")
        self.pin.toggled.connect(self._pin_changed)
        self.copy_button = self._action("copy", "Copy sentence")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_sentence)
        self.settings_button = self._action("settings", "Settings")
        self.settings_menu = QMenu(self.settings_button)
        self.settings_menu.addAction("Settings", self.open_settings)
        self.settings_button.setMenu(self.settings_menu)
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.settings_button.setParent(self)
        self.settings_button.hide()
        close = self._action("close", "Close")
        close.clicked.connect(self.hide)
        self.dismiss_button = close
        self.mode_row = QWidget()
        controls = QHBoxLayout(self.mode_row)
        controls.setContentsMargins(0, 0, 0, 0)
        self.source = QComboBox()
        self.source.setAccessibleName("Language profile")
        self.source.setToolTip("Language profile for OCR and dictionaries")
        self.foreign = QComboBox()
        self.foreign.setAccessibleName("Translation pair")
        self.foreign.setToolTip("Translate in either direction within this pair")
        self.source.setMinimumContentsLength(8)
        self.foreign.setMinimumContentsLength(7)
        self.target_label = QLabel("↔")
        self.update_languages(())
        initial_profile = self.settings.value("profile", self.settings.value("source", "ja"))
        if initial_profile in ("auto", "en"):
            initial_profile = self.settings.value("foreign", "ja")
        self.source.setCurrentIndex(max(0, self.source.findData(initial_profile)))
        self.foreign.setCurrentIndex(max(0, self.foreign.findData(self.settings.value(f"profiles/{initial_profile}/target", "en"))))
        self.translate = self._action("translate", "Translate")
        self.translate.setEnabled(False)
        self.translate.clicked.connect(lambda: self.submit(translate=True, context=bool(self._peek and self._context)))
        self.translate_sentence = self.translate
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setAccessibleName("Search text")
        self.search.setClearButtonEnabled(True)
        self.search.setMaxLength(2000)
        self.search.textChanged.connect(self._edited)
        self.search.returnPressed.connect(self.submit)
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        header_layout.addWidget(self.search, 1)
        header_layout.addWidget(self.translate)
        self.audio_button = self._action("audio", "Play pronunciation")
        self.audio_button.setFixedWidth(36)
        self.audio_button.setEnabled(False)
        self.audio_button.clicked.connect(self.play_audio)
        self.audio_menu = QMenu(self.audio_button)
        self.read_word = self.audio_menu.addAction("Read word", self.play_audio)
        self.read_sentence = self.audio_menu.addAction("Read sentence", lambda: self.play_audio(sentence=True))
        self.read_translation = self.audio_menu.addAction("Read translation", lambda: self.play_audio(translation=True))
        self.audio_button.setMenu(self.audio_menu)
        self.audio_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        header_layout.addWidget(self.audio_button)
        layout.addWidget(self.header)
        controls.addWidget(self.source)
        controls.addWidget(self.target_label)
        controls.addWidget(self.foreign)
        controls.addStretch()
        layout.addWidget(self.mode_row)
        self.context_label = QLabel()
        self.context_label.setWordWrap(True)
        self.context_label.setVisible(False)
        self.context_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.context_label.setParent(self)
        self.browser = LocalDictionaryBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setAccessibleName("Dictionary results")
        self.browser.document().setIndentWidth(10)
        self.browser.anchorClicked.connect(self._link)
        self.browser.word_selected.connect(self.lookup_word)
        layout.addWidget(self.browser, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(close)
        layout.addWidget(self.actions_row)
        self.actions_row.hide()
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.submit)
        self.source.currentIndexChanged.connect(self._mode_changed)
        self.foreign.currentIndexChanged.connect(self._mode_changed)
        self.worker = LookupWorker(directory, engine_factory)
        self.worker.completed.connect(self.deliver)
        self.worker.failed.connect(self._failed)
        self.worker.languages.connect(self.update_languages)
        self.worker.start()
        self.hotkey_requested.connect(self.request_lookup)
        from meikipop.gui.selection import SelectionCapture
        self.selection = SelectionCapture(self)
        self.selection.completed.connect(self._selected_text_ready)
        self.selection.unavailable.connect(self._selection_unavailable)
        self.selection_requested.connect(self.request_selection)
        self.clipboard_requested.connect(lambda: self.lookup_selected(QApplication.clipboard().text()))
        self.copy_shortcut = QShortcut(QKeySequence(
            "Meta+Shift+C" if sys.platform == "darwin" else "Ctrl+Shift+C"), self)
        self.copy_shortcut.activated.connect(self.copy_sentence)
        self.back_shortcut = QShortcut(QKeySequence.StandardKey.Back, self)
        self.back_shortcut.activated.connect(self.go_back)
        self.apply_style()
        self._update_target_visibility()
        self.browser.clear()
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

    def _action(self, name, description):
        button = QToolButton()
        button.setProperty("action_name", name)
        button.setIcon(action_icon(name, config.color_foreground))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(25, 25)
        button.setAccessibleName(description)
        button.setToolTip(description)
        return button

    @property
    def is_pinned(self):
        return self.pin.isChecked()

    @property
    def preferred_foreign(self):
        mode = self.source.currentData()
        return mode if mode not in ("auto", "en", None) else self.settings.value("profile", "ja")

    def apply_style(self):
        colors = surface_colors(config.color_background, config.color_foreground)
        self.frame.setStyleSheet(frame_stylesheet(config.color_background, config.color_foreground,
                                                  config.background_opacity, config.font_family) + f'''
            QLineEdit,QComboBox,QTextBrowser {{background:transparent;color:{config.color_foreground};
                border:0;padding:3px;selection-background-color:{config.color_highlight_word};
                selection-color:{config.color_background};}}
            QLineEdit {{border-bottom:1px solid {colors['border']};}}
            QComboBox QAbstractItemView {{background:{config.color_background};color:{config.color_foreground};}}
            QPushButton,QToolButton {{background:transparent;color:{config.color_foreground};
                border:0;border-radius:4px;padding:3px 5px;}}
            QPushButton:hover,QToolButton:hover,QToolButton:checked {{background:{colors['hover']};}}
            QPushButton:disabled,QToolButton:disabled {{color:{colors['muted']};}}
            QMenu {{background:{config.color_background};color:{config.color_foreground};
                border:1px solid {colors['border']};padding:4px;}}
            QMenu::item:selected {{background:{colors['hover']};}}
            QCheckBox {{color:{config.color_foreground};spacing:4px;}}
            QScrollBar:vertical {{background:transparent;width:6px;margin:2px 0;}}
            QScrollBar::handle:vertical {{background:{colors['scroll']};min-height:24px;border-radius:3px;}}
            QScrollBar::handle:vertical:hover {{background:{colors['muted']};}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
            QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
        ''')
        font = QFont(config.font_family)
        font.setPixelSize(config.font_size_definitions)
        self.browser.setFont(font)
        self.search.setFont(font)
        for button in self.findChildren(QToolButton):
            name = button.property("action_name")
            if name:
                button.setIcon(action_icon(name, config.color_foreground))

    def reload_appearance(self):
        from meikipop.gui.profile_appearance import load_appearance
        load_appearance(self.settings, self.preferred_foreign)
        self.apply_style()
        self._render()

    def compact_preview(self):
        return self.settings.value(f"profiles/{self.preferred_foreign}/compact_preview",
                                   self.settings.value("compact_preview", True, type=bool), type=bool)

    def update_languages(self, languages):
        current_source = self.source.currentData() or self.settings.value("source", "auto")
        current_target = self.foreign.currentData() or "en"
        codes = list(dict.fromkeys(["ja", "tr", "en", *languages,
                                   *([current_source] if current_source != "auto" else []), current_target]))
        with QSignalBlocker(self.source), QSignalBlocker(self.foreign):
            self.source.clear()
            self.foreign.clear()
            for code in codes:
                if code != "en":
                    self.source.addItem(language_name(code), code)
                self.foreign.addItem(language_name(code), code)
            self.source.setCurrentIndex(max(0, self.source.findData(current_source)))
            self.foreign.setCurrentIndex(max(0, self.foreign.findData(current_target)))

    def set_mode(self, source):
        index = self.source.findData(source)
        if index < 0:
            self.source.addItem(language_name(source), source)
            index = self.source.count() - 1
        self.source.setCurrentIndex(index)

    def _update_target_visibility(self):
        self.foreign.setVisible(True)
        self.target_label.setVisible(True)

    def _mode_changed(self):
        mode = self.source.currentData()
        if self.sender() is self.source and mode not in ("auto", "en"):
            with QSignalBlocker(self.foreign):
                self.foreign.setCurrentIndex(max(0, self.foreign.findData(self.settings.value(f"profiles/{mode}/target", "en"))))
            self.settings.setValue("profile", mode)
        self._update_target_visibility()
        if self.foreign.currentData() == self.preferred_foreign:
            with QSignalBlocker(self.foreign):
                self.foreign.setCurrentIndex(self.foreign.findData("en"))
        self.settings.setValue("source", self.source.currentData())
        self.settings.setValue(f"profiles/{self.preferred_foreign}/target", self.foreign.currentData())
        self.mode_changed.emit(self.source.currentData())
        self.reload_appearance()
        self.scan_settings_changed.emit()
        self._edited()

    def _invalidate(self):
        self.revision += 1
        self.debounce.stop()
        self.worker.cancel()
        if self.translation_worker is not None:
            self.translation_worker.cancel()
        self._set_translation_busy(False)

    def _set_translation_busy(self, busy):
        self._translation_busy = busy
        self.translate.setEnabled(not busy and bool(self.search.text().strip() or self._context))
        self.translate.setToolTip("Translating…" if busy else "Translate sentence" if self._peek and self._context else "Translate")

    def _edited(self):
        self._invalidate()
        self._clear_context()
        text = self.search.text().strip()
        self.translate.setEnabled(bool(text))
        self.status.setText("Searching…" if text else "")
        self.status.hide()
        if text:
            self.debounce.start()
        else:
            self.browser.clear()

    def submit(self, translate=None, *, context=False):
        text = self._context if context else self.search.text().strip()
        self.debounce.stop()
        if not text:
            return
        if translate is None:
            translate = is_sentence(text)
        self._last_request_translate = bool(translate)
        self.revision += 1
        self._pending_context_translation = (self.revision, text) if context else None
        self._set_translation_busy(bool(translate))
        self.status.setText("Translating…" if translate else "Searching…")
        self.status.hide()
        worker = self.worker
        if translate:
            if self.translation_worker is None:
                # SQLite connections stay on each worker's own thread. A cold
                # model must not hold up ordinary dictionary lookup requests.
                self.translation_worker = LookupWorker(self.directory, self._engine_factory)
                self.translation_worker.completed.connect(self.deliver)
                self.translation_worker.failed.connect(self._failed)
                self.translation_worker.start()
            worker = self.translation_worker
        source = self._result.source if context and self._result else "auto"
        from meikipop.dictionary.translation import load_profile_settings
        try:
            translation_settings = load_profile_settings(self.settings, self.preferred_foreign) if translate else None
        except (ValueError, TypeError) as error:
            self._set_translation_busy(False)
            self.show_message(str(error))
            return
        worker.request(self.revision, text, source,
                       self.preferred_foreign, translate=bool(translate),
                       target=self.foreign.currentData() if translate else None,
                       pair=(self.preferred_foreign, self.foreign.currentData()),
                       translation_settings=translation_settings)

    def deliver(self, revision, result):
        if revision != self.revision or self._shutting_down:
            return
        self._set_translation_busy(False)
        partial_japanese = result.source == "ja" and 0 < result.matched_length < len(result.text)
        if (not self._peek and not self._last_request_translate and not result.translation
                and (not result.entries or partial_japanese)):
            self.submit(translate=True)
            return
        self._display(result)
        if self._pending_context_translation and self._pending_context_translation[0] == revision:
            self.set_context(self._pending_context_translation[1])
            self._pending_context_translation = None
        elif not self._peek:
            self.set_context(result.text)
        self.status.setText(f"{language_name(result.source)} → {language_name(result.target)}")
        self.status.hide()

    def _display(self, result, remember=True):
        same = self._result is not None and (self._result.text, self._result.source, self._result.target) == (
            result.text, result.source, result.target)
        previous_context = getattr(self, "_result_context", "")
        if remember and not self._new_chain and self._result is not None and not same:
            self._history.append((self._result, getattr(self, "_result_context", ""),
                                  self._result_profile, self._result_target, tuple(self._expanded),
                                  self.browser.verticalScrollBar().value()))
            self._history = self._history[-30:]
        self._new_chain = False
        self._result = result
        self._result_profile = self.preferred_foreign
        self._result_target = self.foreign.currentData()
        self._result_context = previous_context if same else ""
        self._expanded.clear()
        self._kanji_expanded = False
        self._render()
        self.back.setEnabled(bool(self._history))
        self.back.setVisible(bool(self._history))
        self._update_trail()
        self.audio_button.setEnabled(bool(result.entries or result.text))
        self.audio_button.setToolTip("Play pronunciation" if result.entries else "Read sentence")
        self.read_word.setVisible(bool(result.entries))
        self.read_sentence.setEnabled(bool(result.text))
        self.read_translation.setVisible(bool(result.translation))
        autoplay = audio_autoplay_mode(self.settings, self.preferred_foreign)
        if (result.entries or result.translation) and (autoplay == "lookup" or
                autoplay == "pin" and (not self._peek or self.is_pinned)):
            self.play_audio()

    def _render(self):
        if self._result is not None:
            compact = self.compact_preview()
            expanded = self._expanded
            if self._peek and not compact:
                expanded = {entry.source for entry in self._result.entries}
            self.browser.setHtml(render_result(self._result, expanded,
                                               self._kanji_expanded or self._peek and not compact,
                                               preview=self._peek and not self.is_pinned and compact))
            self.browser.setToolTip("")
            QTimer.singleShot(0, self._fit_preview)

    def _fit_preview(self):
        if self._shutting_down or not self._peek or self.is_pinned or not self.compact_preview():
            return
        self.setMinimumHeight(72)
        self.layout().activate()
        document = self.browser.document()
        document.setTextWidth(self.browser.viewport().width())
        chrome = self.height() - self.browser.viewport().height()
        desired = math.ceil(document.size().height()) + chrome + 2
        maximum = max(190, self.settings.value("preview_max_height", 340, type=int))
        self.resize(self.width(), min(maximum, max(self.minimumSizeHint().height(), desired)))
        if self.isVisible():
            self._place()

    def set_compact_preview(self, enabled):
        self.settings.setValue(f"profiles/{self.preferred_foreign}/compact_preview", bool(enabled))
        self._render()

    def _failed(self, revision, message):
        if revision in (-1, self.revision):
            self._set_translation_busy(False)
            self.show_message(message)

    def show_message(self, text):
        self.status.setText(str(text))
        self.status.setVisible(bool(text))

    def _link(self, url):
        if self._result is None:
            return
        if self._pin_anchor_click:
            self._pin_anchor_click = False
            return  # The first click already expanded the complete peek.
        if url.scheme() == "kanji" and url.path() == "toggle":
            self._kanji_expanded = not self._kanji_expanded
            self._render()
            self.browser.scrollToAnchor("kanji")
            return
        try:
            index = int(url.path())
        except ValueError:
            return
        if url.scheme() == "expand":
            sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
            if not 0 <= index < len(sources):
                return
            source = sources[index]
            if source in self._expanded:
                self._expanded.remove(source)
            else:
                self._expanded.add(source)
            self._render()
            self.browser.scrollToAnchor(f"dictionary-{index}")
        elif url.scheme() == "suggest" and 0 <= index < len(self._result.suggestions):
            self.lookup_word(str(self._result.suggestions[index]))

    def lookup_word(self, text):
        self._set_peek(False)
        self.search.setText(text)
        self.submit()

    def go_back(self):
        if not self._history:
            return
        self._invalidate()
        result, context, profile, target, expanded, scroll = self._history.pop()
        with QSignalBlocker(self.search), QSignalBlocker(self.source), QSignalBlocker(self.foreign):
            self.search.setText(result.text)
            if self.source.findData(profile) < 0:
                self.source.addItem(language_name(profile), profile)
            self.source.setCurrentIndex(self.source.findData(profile))
            self.foreign.setCurrentIndex(self.foreign.findData(target))
        self._update_target_visibility()
        self.mode_changed.emit(self.source.currentData())
        self._display(result, remember=False)
        self.set_context(context)
        self._expanded = set(expanded)
        self._render()
        self.browser.verticalScrollBar().setValue(scroll)
        self.translate.setEnabled(bool(result.text))
        self.status.setText(f"{language_name(result.source)} → {language_name(result.target)}")

    def _update_trail(self):
        if not self._history:
            self.title.clear()
            return
        labels = []
        start = max(0, len(self._history) - 2)
        if start:
            labels.append("…")
        for index in range(start, len(self._history)):
            text = self._history[index][0].text
            short = text[:12] + ("…" if len(text) > 12 else "")
            labels.append(f'<a href="{index}" style="color:{config.color_highlight_word}">{escape(short)}</a>')
        text = self._result.text
        labels.append(escape(text[:12] + ("…" if len(text) > 12 else "")))
        self.title.setText(" › ".join(labels))

    def _history_jump(self, index):
        index = int(index)
        if 0 <= index < len(self._history):
            self._history = self._history[:index + 1]
            self.go_back()

    def _place(self):
        point = QCursor.pos()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
            if not self._peek and not self._manual_at_cursor:
                tray = self.tray_geometry() if self.tray_geometry else None
                x = tray.center().x() if tray and not tray.isNull() else area.right()
                self.move(max(area.left(), min(x - self.width() // 2, area.right() - self.width())),
                          max(area.top(), area.bottom() - self.height() - 8))
            else:
                self.move(*popup_position(point.x(), point.y(), self.size(), area, config.popup_position_mode))

    def _set_peek(self, peek):
        if peek and not self._peek:
            self._normal_size = self.size()
        elif not peek and self._peek and not self.is_pinned:
            self.setMinimumHeight(190)
            self.resize(self._normal_size)
        self._peek = bool(peek)
        self.mode_row.setVisible(not self._peek)
        self.header.setVisible(not self._peek or self.is_pinned)
        self.search.setVisible(not self._peek)
        self.actions_row.setVisible(self.is_pinned or not self._peek)

    def open_search(self, text="", *, at_cursor=False, passive=False):
        self.remember_foreground()
        self._history.clear()
        self._new_chain = True
        self.title.clear()
        self.back.hide()
        self._passive_text = passive
        self._opening_search = True
        self._manual_at_cursor = at_cursor
        self.pin.setChecked(False)
        self._set_peek(False)
        self._render()
        self._clear_context()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, self._passive_text)
        if not self.is_pinned or not self.isVisible():
            self._place()
        self.show()
        self.raise_()
        if not self._passive_text:
            self.activateWindow()
        self.search.setText(text)
        self.search.setFocus()
        self.search.selectAll()
        def focus():
            from meikipop.utils.window_focus import focus_search
            if self.isVisible() and not self._passive_text:
                focus_search(self)
            self._opening_search = False
        QTimer.singleShot(0, focus)
        if text:
            self.submit()

    def lookup_selected(self, text, *, passive=False):
        if text.strip():
            self.open_search(text.strip()[:2000], at_cursor=True, passive=passive)

    def request_selection(self):
        self._selection_for_search = False
        self._selection_passive = False
        self.selection.start(wait_for_modifiers=True)

    def request_lookup(self):
        self._lookup_clipboard = QApplication.clipboard().text()[:2000]
        if QApplication.activeWindow() is not None:
            focused = QApplication.focusWidget()
            text = focused.selectedText() if isinstance(focused, QLineEdit) else (
                self.browser.textCursor().selectedText() if focused in (self.browser, self.browser.viewport()) else "")
            self.open_search(text or self._lookup_clipboard)
            return
        if self.selection.pending:
            return
        self._selection_for_search = True
        self.selection.start(wait_for_modifiers=True)

    def _selected_text_ready(self, text):
        if self._selection_for_search:
            self._selection_for_search = False
            self.open_search(text)
        else:
            self.lookup_selected(text, passive=self._selection_passive)

    def _selection_unavailable(self, same_application):
        requested, self._selection_for_search = self._selection_for_search, False
        if requested and same_application:
            self.open_search(self._lookup_clipboard)

    def play_audio(self, *, sentence=False, translation=False):
        if self._result is None:
            return
        if self.audio is None:
            from meikipop.gui.lookup_audio import LookupAudio
            self.audio = LookupAudio(self)
            self.audio.failed.connect(self.show_message)
        result = self._result
        if translation:
            text, language = result.translation, result.target
        elif sentence or not result.entries:
            text, language = (self._context or result.text) if sentence else result.text, result.source
        else:
            self.audio.play(result.entries[0], self.revision, self.settings, profile=self.preferred_foreign)
            return
        self.audio.play_text(text, language, self.revision, self.settings, profile=self.preferred_foreign)

    def show_entries(self, entries, text="", source="ja", peek=False, kanji=()):
        if peek and self.is_pinned:
            return False
        entries = tuple(entries or ())
        if (peek and self._peek and self._result is not None and self._result.text == text
                and self._result.source == source and self._result.entries == entries and self.isVisible()):
            return True
        self._invalidate()
        self._history.clear()
        self._new_chain = True
        entries = tuple(entries or ())
        target = self.foreign.currentData() if source == "en" else "en"
        result = SearchResult(text, source, target, entries, kanji=tuple(kanji))
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self.translate.setEnabled(bool(text))
        self._set_peek(peek)
        self._display(result)
        self.set_context("")
        self.status.setText("")
        self.status.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, bool(peek))
        if not self.is_pinned:
            self._place()
        self.show()
        if not peek:
            self.raise_()
        return True

    def set_context(self, text, start=0, end=None):
        self._context = str(text or "").strip()
        self._result_context = self._context
        self.copy_button.setEnabled(bool(self._context))
        self.copy_button.setToolTip("Copy sentence\n\n" + self._context if self._context else "Copy sentence")
        self.context_label.setToolTip(self._context)
        preview = self._context[:180] + ("…" if len(self._context) > 180 else "")
        self.context_label.setTextFormat(Qt.TextFormat.PlainText)
        self.context_label.setText(preview)
        self.context_label.hide()
        self.copy_button.setVisible(bool(self._context))
        self._set_translation_busy(self._translation_busy)

    def _clear_context(self):
        previous = getattr(self, "_result_context", "")
        self.set_context("")
        self._result_context = previous

    def copy_sentence(self):
        if self._context:
            QApplication.clipboard().setText(self._context)
            self.copy_button.setToolTip("Copied\n\n" + self._context)

    def _pin_changed(self, checked):
        if checked:
            self.remember_foreground()
        self.pin.setToolTip("Unpin" if checked else "Pin")
        self.setSizeGripEnabled(checked)
        if self._peek:
            if checked:
                self.setMinimumHeight(190)
                self.resize(self._normal_size)
            else:
                self._normal_size = self.size()
        if checked:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            self.activateWindow()
            self.browser.setFocus(Qt.FocusReason.MouseFocusReason)
            if self._peek and self._result is not None:
                self._expanded.update(entry.source for entry in self._result.entries)
                self._kanji_expanded = True
        self.context_label.hide()
        self.actions_row.setVisible(checked or not self._peek)
        self.header.setVisible(checked or not self._peek)
        self._render()

        if checked and self._peek and audio_autoplay_mode(self.settings, self.preferred_foreign) == "pin":
            self.play_audio()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip and watched is not self.copy_button:
            QToolTip.hideText()
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            self._passive_text = False
        if (event.type() == QEvent.Type.MouseButtonPress and self._peek and not self.is_pinned
                and watched not in (self.dismiss_button, self.pin)):
            self._pin_anchor_click = watched is self.browser.viewport()
            self.pin.setChecked(True)
        elif event.type() == QEvent.Type.MouseButtonRelease and self._pin_anchor_click:
            QTimer.singleShot(0, lambda: setattr(self, "_pin_anchor_click", False))
        if watched is self.title:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_position = event.globalPosition().toPoint() - self.pos()
            elif event.type() == QEvent.Type.MouseMove and self._drag_position is not None:
                self.move(event.globalPosition().toPoint() - self._drag_position)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_position = None
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            QTimer.singleShot(0, self._dismiss_if_inactive)

    def _dismiss_if_inactive(self):
        if self._opening_search or self._passive_text:
            return
        setup_open = self._setup is not None and self._setup.isVisible()
        if (not self._peek or self.is_pinned) and not self.isActiveWindow() and not setup_open \
                and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
            self.hide()

    def hideEvent(self, event):
        if hasattr(self, "worker"):
            self._invalidate()
        self.pin.setChecked(False)
        super().hideEvent(event)

    def remember_foreground(self):
        if QApplication.platformName() != "offscreen":
            from meikipop.utils.window_focus import foreground_window
            handle = foreground_window()
            if handle and handle != int(self.winId()):
                self._previous_foreground = handle

    def hide(self):
        if QApplication.platformName() != "offscreen":
            from meikipop.utils.window_focus import foreground_window, restore_foreground
            if foreground_window() == int(self.winId()):
                restore_foreground(self._previous_foreground)
        super().hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def open_settings(self):
        from meikipop.gui.dictionary_manager import SetupDialog
        if self._setup is None:
            self._setup = SetupDialog(self.directory, self.settings, self.apply_shortcut, self)
            self._setup.dictionaries_changed.connect(self.refresh_library)
        self._setup.show()
        self._setup.raise_()
        self._setup.activateWindow()

    def refresh_library(self):
        self.worker.refresh()
        if self.translation_worker is not None:
            self.translation_worker.refresh()
        self._edited()

    def apply_shortcut(self, value, preset=None):
        from meikipop.gui.text_shortcuts import TextHotKeys, validate_shortcuts
        bindings = {value: self.hotkey_requested.emit} if value else {}
        validate_shortcuts([value])
        replacement = TextHotKeys(bindings) if bindings else None
        if replacement:
            replacement.start()
        previous, self._keys = self._keys, replacement
        if previous:
            previous.stop()
        self.settings.setValue("hotkey", value)
        if preset is not None:
            self.settings.setValue("hotkey_preset", preset)

    def restore_shortcut(self, explicit=None):
        default = "<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d"
        binding = explicit if explicit is not None else self.settings.value("hotkey", default)
        self.apply_shortcut(binding)

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        self.selection.cancel()
        if self.audio:
            self.audio.shutdown()
        self.debounce.stop()
        self.worker.shutdown()
        if self.translation_worker is not None:
            self.translation_worker.shutdown()
        if self._setup is not None:
            self._setup.cancel_operation()
        if self._keys:
            self._keys.stop()
            self._keys = None


def shortcut_preset():
    return "Meta+Shift+D" if sys.platform == "darwin" else "Ctrl+Shift+D"


def audio_autoplay_mode(settings, profile):
    legacy = settings.value(f"profiles/{profile}/audio_autoplay",
                            config.audio_autoplay_enabled if profile == "ja" else False, type=bool)
    return settings.value(f"profiles/{profile}/audio_autoplay_mode", "lookup" if legacy else "off")
