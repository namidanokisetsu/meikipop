"""Compact, shared dictionary surface with a latest-request background worker."""
from collections import OrderedDict
from dataclasses import replace
from html import escape
from urllib.parse import quote
import re
import math
import sys
import threading
import unicodedata

from PyQt6.QtCore import QObject, QEvent, QLocale, QSettings, QSignalBlocker, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QFontMetricsF, QKeySequence, QShortcut, QTextLayout, QTextOption
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from meikipop.config.config import config
from meikipop.dictionary.search import SearchEngine, SearchResult
from meikipop.gui.popup_style import expanded_geometry, frame_stylesheet, popup_position, surface_colors
from meikipop.gui.action_icons import action_icon
from meikipop.gui.ruby import RubyBrowser, ruby_html
from meikipop.language.profiles import configured_profiles, default_partner
from meikipop.scripts.import_yomitan_dict_html import StructuredContentConverter
from meikipop.utils.timing import mark


LANGUAGE_NAMES = {
    "ja": "日本語", "tr": "Türkçe", "en": "English", "de": "Deutsch",
    "fr": "Français", "es": "Español", "ru": "Русский", "zh": "中文",
    "ko": "한국어", "ar": "العربية", "it": "Italiano", "pt": "Português",
    "uk": "Українська", "nl": "Nederlands", "pl": "Polski",
}
for _locale in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript, QLocale.Country.AnyCountry):
    _code = _locale.name().split("_")[0]
    if re.fullmatch(r"[a-z]{2,3}", _code):
        LANGUAGE_NAMES.setdefault(_code, QLocale.languageToString(_locale.language()))
from meikipop.language.support import AVAILABLE_LANGUAGES, EXTRA_NAMES
LANGUAGE_NAMES.update(EXTRA_NAMES)
LANGUAGE_NAMES = {code: LANGUAGE_NAMES.get(code, code) for code in sorted(AVAILABLE_LANGUAGES)}
LANGUAGE_NAMES.update({"zh-hant": "中文（繁體）", "zh-tw": "中文（台灣）", "zh-hk": "中文（香港）"})


def language_name(code):
    return LANGUAGE_NAMES.get(code, code)


def is_sentence(text):
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    return len(words) > 2 or bool(re.search(r"[。！？!?\n]|\.(?:\s|$)", text.strip())) or "、" in text


class LookupWorker(QObject):
    completed = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)
    languages = pyqtSignal(object)
    progress = pyqtSignal(int, object)
    translation_state = pyqtSignal(int, str)

    def __init__(self, directory=None, engine_factory=None):
        super().__init__()
        self._factory = engine_factory or (lambda: SearchEngine(directory))
        self._condition = threading.Condition()
        self._pending = None
        self._active_cancel = None
        self._refresh = True
        self._stopped = False
        self._engine = None
        self._thread = threading.Thread(target=self._run, name="dictionary-search", daemon=True)

    def start(self):
        self._thread.start()

    def request(self, revision, text, source, foreign, translate=False, target=None, pair=None, translation_settings=None,
                morphology=False, context=None):
        self.cancel()
        mark("dispatch", revision, translation=translate)
        with self._condition:
            self._pending = (revision, text, source, foreign, translate, target, pair, translation_settings, morphology,
                             context, threading.Event())
            self._condition.notify()

    def cancel(self):
        with self._condition:
            if self._pending is not None:
                self._pending[-1].set()
            self._pending = None
            if self._active_cancel is not None:
                self._active_cancel.set()
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
                    self._active_cancel = pending[-1] if pending else None
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
                        revision, text, source, foreign, translate, target, pair, translation_settings, morphology, context, cancelled = pending
                        mark("dequeue", revision)
                        options = {"target": target} if target else {}
                        if pair:
                            options.update(pair=pair, translation_settings=translation_settings)
                        if morphology:
                            options["morphology"] = True
                        if context is not None:
                            options["context"] = context
                        if isinstance(engine, SearchEngine):
                            options.update(cancelled=cancelled, request_id=revision,
                                           translation_progress=lambda result: self._emit(self.progress, revision, result),
                                           translation_state=lambda value: self._emit(self.translation_state, revision, value))
                        result = engine.search(text, source=source, foreign=foreign, translate=translate, **options)
                        mark("lookup_done", revision)
                        self._emit(self.completed, revision, result)
                except Exception as error:
                    self._emit(self.failed, pending[0] if pending else -1, str(error))
        finally:
            if engine is not None:
                engine.close()


class _GlossConverter(StructuredContentConverter):
    """Prune structured previews before conversion, retaining lists and emphasis."""
    def __init__(self, expanded=False, limit=360, preview=False, generic_source=False, term="",
                 details_expanded=(), detail_prefix="", definitions=(), definition_furigana=False):
        super().__init__()
        self.definition_furigana = definition_furigana
        self.colors = surface_colors(config.color_background, config.color_foreground)
        self.expanded = expanded
        self.preview = preview
        self.generic_source = generic_source
        self.term = term
        self.first_source = ""
        self._preview_source_complete = False
        self.remaining = limit
        self.clipped = False
        self.details_expanded = details_expanded
        self._detail_keys = {}
        def index_details(node):
            if isinstance(node, (list, tuple)):
                for child in node:
                    index_details(child)
            elif isinstance(node, dict):
                if node.get("tag") == "details":
                    self._detail_keys[id(node)] = f"{detail_prefix}:{len(self._detail_keys)}"
                index_details(node.get("content"))
        index_details(definitions)

    def _details_to_html(self, node):
        if self.preview:
            self.clipped = True
            return ""
        key = self._detail_keys[id(node)]
        children = node.get("content", [])
        children = children if isinstance(children, list) else [children]
        summary = next((child for child in children if isinstance(child, dict)
                        and child.get("tag") == "summary"), None)
        opened = key in self.details_expanded
        expanded, remaining = self.expanded, self.remaining
        self.expanded, self.remaining = True, None
        try:
            label = (self._node_to_html(summary.get("content")) if summary else "") or "More"
            body = self._node_to_html([child for child in children if child is not summary]) if opened else ""
        finally:
            self.expanded, self.remaining = expanded, remaining
        return (f'<div><a name="details-{key}"></a><a href="details:{key}" '
                f'title="{"Collapse" if opened else "Expand"}"><small>'
                f'{"▾" if opened else "▸"} {label}</small></a></div>{body}')

    def _ruby_to_html(self, content):
        parts, base = [], []
        nodes = content if isinstance(content, list) else [content]
        for child in nodes:
            tag = child.get("tag") if isinstance(child, dict) else None
            if tag == "rp":
                continue
            if tag == "rt":
                reading = self._node_to_html(child.get("content"))
                text = "".join(base)
                parts.append((ruby_html(text, reading) if self.definition_furigana else
                              f'{text} [{reading}]') if text and reading else text)
                base = []
            else:
                base.append(self._node_to_html(child))
        return "".join(parts + base)

    def _node_to_html(self, node):
        if self._preview_source_complete:
            return ""
        if isinstance(node, str):
            if not self.expanded and self.remaining is not None:
                text = node[:self.remaining]
                self.remaining -= len(text)
                if len(text) < len(node):
                    self.clipped = True
                    text += "…" if text else ""
                node = text
            return super()._node_to_html(node).replace('\n', '<br>') if node.strip() else node
        if isinstance(node, list):
            parts = []
            for child in node:
                if not self.expanded and self.remaining is not None and self.remaining <= 0:
                    self.clipped = True
                    break
                parts.append(self._node_to_html(child))
            return "".join(parts)
        if isinstance(node, dict):
            if node.get("tag") == "details":
                return self._details_to_html(node)
            node = dict(node)
            tag, content = node.get("tag", ""), node.get("content")
            data = node.get("data", {})
            kind = str(data.get("content", "")) if isinstance(data, dict) else ""
            if kind == "backlink":
                return ""
            style = node.get("style", {})
            style = style if isinstance(style, dict) else {}
            heading_text = content[0] if isinstance(content, list) and len(content) == 1 else content
            # Turkdict repeats the headword for each homonym inside a source.
            # The shared lexical heading already identifies these sense groups.
            if (self.generic_source and tag == "div" and heading_text == self.term
                    and style.get("fontWeight") == "bold" and style.get("marginTop") == "0.3em"):
                return ""
            source_heading = (isinstance(heading_text, str) and heading_text.strip() in
                              ("Tureng", "Wiktionary", "TDK", "KeNet", "Etymology")
                              and (tag in ("b", "strong") or style.get("fontWeight") in ("bold", "700")))
            if source_heading and self.generic_source:
                if not self.first_source:
                    self.first_source = heading_text.strip()
                    return ""
                if self.preview:
                    self._preview_source_complete = True
                    self.clipped = True
                    return ""
                return f'<p class="source"><small>{escape(heading_text.strip())}</small></p>'
            # Turkdict's exporter retains this presentation signature for
            # examples, translations and sense context, but no CSS class name.
            turkdict_example = (tag == "div" and style.get("fontSize") == "0.9em"
                                and style.get("marginTop") == "0.1em")
            if not self.expanded:
                if self.preview and kind in ("forms", "attribution", "extra-info"):
                    self.clipped = True
                    return ""
                if "example" in kind.lower() or turkdict_example:
                    self.clipped = True
                    return ""
                # Turkdict exports numbered senses as divs rather than list items.
                numbered_senses = (self.preview and isinstance(content, list) and bool(content) and all(
                    isinstance(child, dict) and child.get("tag") == "div"
                    and isinstance(child.get("content"), list) and child["content"]
                    and isinstance(child["content"][0], str)
                    and re.match(r"\d+\.\s", child["content"][0]) for child in content))
                if (tag in ("ol", "ul") or kind == "glosses" or numbered_senses) and isinstance(content, list):
                    senses = [child for child in content if not isinstance(child, str) or child.strip()]
                    maximum = 3 if self.preview else 2
                    if len(senses) > maximum:
                        node["content"] = senses[:maximum]
                        self.clipped = True
            if kind == "glossary":
                children = node.get("content")
                children = children if isinstance(children, list) else [children]
                return "; ".join(filter(None, (self._node_to_html(
                    child.get("content") if isinstance(child, dict) and child.get("tag") == "li" else child)
                    for child in children)))
            source_class = data.get("class", "") if isinstance(data, dict) else ""
            if source_class == "tag" or kind == "tag":
                label = self._node_to_html(content)
                return f'<span style="color:{self.colors["muted"]}"><small>[{label}]</small></span> ' if label else ""
            if kind == "tags":
                return self._node_to_html(content)
            if tag in ("td", "th"):
                labels = {"form-pri": "common", "form-valid": "valid", "form-rare": "rare",
                          "form-out": "obsolete", "form-irr": "irregular"}
                if source_class in labels:
                    node["content"] = labels[source_class]
            if kind in ("sense-groups", "sense-group"):
                tag = node["tag"] = "div"
            # Keep a small, safe subset of typography. Dictionary CSS must not
            # inject attributes, override the theme or stretch the popup.
            safe_style = {}
            for name, values in (("fontStyle", ("italic", "normal")),
                                 ("fontWeight", ("bold", "normal", "400", "700"))):
                if style.get(name) in values:
                    safe_style[name] = style[name]
            if kind in ("bold-text", "example-keyword"):
                safe_style["fontWeight"] = "bold"
            if tag in ("td", "th"):
                safe_style.update(borderStyle="solid", borderWidth="1px", borderColor=self.colors["border"],
                                  padding="4px", color=config.color_foreground)
                if tag == "th":
                    safe_style["backgroundColor"] = self.colors["hover"]
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


def _metadata(entries, combine_frequencies=True):
    frequencies, inflections = OrderedDict(), OrderedDict()
    raw_frequencies = []
    for entry in entries:
        raw_frequencies.extend(entry.frequencies)
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
        if combine_frequencies:
            from meikipop.dictionary.metadata import harmonic_rank
            rank = harmonic_rank(raw_frequencies)
            if rank is not None:
                detail = "; ".join(source + ": " + label for source, label in frequencies)
                parts.append(f'<a href="frequency:{quote(detail)}" style="color:{muted}">#{max(1, round(rank)):,}</a>')
        else:
            parts.extend(f'<a href="frequency:{quote(source + ": " + label)}" style="color:{muted}">{escape(label)}</a>'
                         for source, label in frequencies)
    if inflections:
        parts.append(escape(" · ".join(inflections)))
    return '<p class="metadata"><small>' + " · ".join(parts) + '</small></p>' if parts else ""


def _source_name(source):
    return re.sub(r"\s*\[\d{4}[^\]]*\]", "", source).replace("Jitendex.org", "Jitendex").strip()


def _compact_context(text, font, width):
    text = " ".join(text.split())
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    if line.isValid():
        line.setLineWidth(max(1, width))
    length = line.textLength() if line.isValid() else 0
    layout.endLayout()
    # Qt text offsets count UTF-16 units, including emoji and astral kanji.
    encoded = text.encode("utf-16-le")
    first = encoded[:length * 2].decode("utf-16-le").rstrip()
    rest = encoded[length * 2:].decode("utf-16-le").lstrip()
    if not rest:
        return first
    return first + "\n" + QFontMetricsF(font).elidedText(rest, Qt.TextElideMode.ElideRight, max(1, width))


def render_result(result, expanded=(), kanji_expanded=False, preview=False, overlay_actions=False, show_source=True,
                  headword_furigana=False, combine_frequencies=True, source_text=None, details_expanded=(),
                  definition_furigana=False, show_pitch=True):
    """Share lexical headings while preserving the configured dictionary order."""
    muted = surface_colors(config.color_background, config.color_foreground)["muted"]
    clearance = 96 if overlay_actions is True else int(overlay_actions)
    groups, sources = OrderedDict(), list(dict.fromkeys(entry.source for entry in result.entries))
    for entry in result.entries:
        if preview and (entry.source != sources[0] or groups and (entry.term, entry.reading) not in groups):
            continue
        groups.setdefault((entry.term, entry.reading), OrderedDict()).setdefault(entry.source, []).append(entry)
    parts = [f'<style>body {{color:{config.color_foreground};}} '
             f'a,h2 {{color:{config.color_highlight_word};text-decoration:none;}} '
             f'h2 {{font-size:{config.font_size_header}px;font-weight:normal;margin:3px {clearance}px 3px 0;}} '
             'p {margin:2px 0;} ol,ul {margin:2px 0 4px 8px;padding:0;} '
             'li {margin:1px 0;} hr {margin:6px 0;} '
             f'.metadata {{margin:1px 0 3px;color:{muted};}} .source {{margin:5px 0 2px;color:{muted};}}</style>']
    if source_text is None:
        source_text = result.text if result.translation else ""
    if show_source and source_text:
        parts.append(f'<p style="margin:0 {clearance}px 4px 0;color:{muted}"><small>'
                     f'{escape(source_text).replace(chr(10), "<br>")}</small></p>')
        if result.translation:
            parts.append("<hr>")
    if result.translation:
        parts.append(f'<p>{escape(result.translation).replace(chr(10), "<br>")}</p>')
        if result.entries:
            parts.append("<hr>")
    anchored = set()
    for group_index, ((term, reading), dictionaries) in enumerate(groups.items()):
        if group_index:
            parts.append("<hr>")
        display_term = term
        if (result.source == "ru" and reading and unicodedata.normalize("NFC", reading.replace("\u0301", ""))
                == unicodedata.normalize("NFC", term)):
            display_term, reading = reading, ""
        display_reading = f"[{reading}]" if result.source == "ja" else reading
        reading_html = (f' <span style="color:{config.color_highlight_reading};font-size:'
                        f'{max(12, config.font_size_header - 3)}px">{escape(display_reading)}</span>'
                        if reading and reading != term else "")
        if result.source == "ja" and headword_furigana and reading and reading != term:
            parts.append(f'<h2>{ruby_html(escape(term), escape(reading), config.color_highlight_word)}</h2>')
        else:
            parts.append(f'<h2>{escape(display_term)}{reading_html}</h2>')
        parts.append(_metadata((entry for entries in dictionaries.values() for entry in entries), combine_frequencies))
        if show_pitch and result.source == "ja":
            from meikipop.dictionary.pitch import render_pitches
            parts.append(render_pitches(pitch for entries in dictionaries.values() for entry in entries
                                        for pitch in entry.pitches))
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
            converter = _GlossConverter(expanded=full, limit=None if preview else 360, preview=preview,
                                        generic_source=generic_source, term=term,
                                        details_expanded=details_expanded, detail_prefix=f"{group_index}:{index}",
                                        definition_furigana=definition_furigana,
                                        definitions=tuple(definition for entry in entries for definition in entry.definitions))
            definitions = []
            for entry in entries if full else entries[:2]:
                more = more or len(entry.definitions) > 3
                definitions.extend(converter.glosses(entry.definitions if full else entry.definitions[:3]))
            more = more or converter.clipped
            toggle = (f'<a href="expand:{index}" title="{"Collapse" if full else "Expand"}">'
                      f'&nbsp;{"−" if full else "+"}&nbsp;</a>'
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


class LocalDictionaryBrowser(RubyBrowser):
    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    def loadResource(self, resource_type, name):
        # Dictionary content is text; embedded local/network resources are unnecessary.
        return None


class QuickLookupWindow(QDialog):
    dictionaries_changed = pyqtSignal()
    mode_changed = pyqtSignal(str)
    ocr_enabled_changed = pyqtSignal(bool)
    scan_settings_changed = pyqtSignal()
    hotkey_requested = pyqtSignal()
    selection_requested = pyqtSignal()
    clipboard_requested = pyqtSignal()

    def __init__(self, directory=None, engine_factory=None, settings=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        if sys.platform == "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        if QApplication.platformName() == "xcb":
            self.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint)
        self.directory = directory
        self.settings = settings or QSettings("Meikipop", "QuickLookup")
        from meikipop.gui.interaction_preferences import migrate
        migrate(self.settings)
        from meikipop.gui.profile_appearance import load_appearance
        load_appearance(self.settings, self.settings.value("profile", self.settings.value("source", "ja")))
        self.revision = 0
        self._result = None
        self._display_revision = None
        self._pending_revision = None
        self._paint_revision = None
        self._document_revision = None
        self._render_identity = None
        self._fit_identity = None
        self._needs_place = False
        self._context = ""
        self._peek = False
        self._history = []
        self._new_chain = True
        self._expanded = set()
        self._details_expanded = set()
        self._kanji_expanded = False
        self._pin_anchor_click = False
        self._keys = None
        self._shutting_down = False
        self._drag_position = None
        self._drag_start = None
        self._dragging = False
        self._resize_start = None
        self._engage_press = None
        self._setup = None
        self._engine_factory = engine_factory
        self.translation_worker = None
        self._pending_context = None
        self._translation_busy = False
        self._last_request_translate = False
        self._sentence_lookup = False
        self._translation_base = None
        self._translation_previous = None
        self._partial_translation = False
        self._translation_chunk = None
        self._translation_model_state = ""
        self._remember_request = False
        self.audio = None
        self._anki_dialog = None
        self._autoplayed = None
        self._scan_hold_active = False
        self._selection_lookup = False
        self.tray_geometry = None
        self._manual_at_cursor = False
        self._opening_search = False
        self._previous_foreground = None
        self._passive_text = False
        self._selection_passive = False
        self._selection_for_search = False
        self._capture_visibility = False
        self.setWindowTitle("Meikipop")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(340, 190)
        self.resize(480, 340)
        self._normal_size = QSize(480, 340)
        self._lookup_anchor = None
        self._result_screenshot = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        outer.addWidget(self.frame)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
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
        if initial_profile == "auto" or initial_profile == "en" and not self.settings.contains("profile"):
            initial_profile = self.settings.value("foreign", "ja")
        self.source.setCurrentIndex(max(0, self.source.findData(initial_profile)))
        self.foreign.setCurrentIndex(max(0, self.foreign.findData(self.settings.value(f"profiles/{initial_profile}/target", default_partner(initial_profile)))))
        self.translate = self._action("translate", "Translate")
        self.translate.setEnabled(False)
        self.translate.clicked.connect(self._translate_clicked)
        self.translate_sentence = self.translate
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setAccessibleName("Search text")
        self.search.textEdited.connect(lambda _: setattr(self, "_selection_lookup", False))
        self.search.setClearButtonEnabled(True)
        self.search.setMaxLength(2000)
        self.search.textChanged.connect(self._edited)
        self.search.returnPressed.connect(lambda: self.submit(selection=True))
        self.search.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search.customContextMenuRequested.connect(self._input_menu)
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        header_layout.addWidget(self.search, 1)
        self.audio_actions = QWidget()
        action_layout = QHBoxLayout(self.audio_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(2)
        action_layout.addWidget(self.translate)
        self.anki_button = QPushButton("Add to Anki")
        self.anki_button.clicked.connect(self.add_to_anki)
        self.sentence_audio_button = self._action("audio_sentence", "Read sentence")
        self.sentence_audio_button.clicked.connect(lambda: self.play_audio(sentence=True))
        self.sentence_audio_button.setEnabled(False)
        action_layout.addWidget(self.sentence_audio_button)
        self.audio_button = self._action("audio", "Play pronunciation")
        self.audio_button.setEnabled(False)
        self.audio_button.clicked.connect(self.play_audio)
        self.audio_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.audio_button.customContextMenuRequested.connect(self.audio_source_menu)
        action_layout.addWidget(self.audio_button)
        header_layout.addWidget(self.audio_actions)
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
        self.browser = LocalDictionaryBrowser(selection_lookup=self.settings.value(
            f"profiles/{initial_profile}/selection_lookup", False, bool))
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
        toolbar.insertWidget(0, self.anki_button)
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(close)
        layout.addWidget(self.actions_row)
        self.actions_row.hide()
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.submit)
        self.busy_delay = QTimer(self)
        self.busy_delay.setSingleShot(True)
        self.busy_delay.setInterval(175)
        self.busy_delay.timeout.connect(self._show_busy)
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.timeout.connect(lambda: self._fit_preview())
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self._render)
        self.stream_timer = QTimer(self)
        self.stream_timer.setSingleShot(True)
        self.stream_timer.setInterval(80)
        self.stream_timer.timeout.connect(self._flush_translation)
        self.source.currentIndexChanged.connect(self._mode_changed)
        self.foreign.currentIndexChanged.connect(self._mode_changed)
        self.worker = LookupWorker(directory, engine_factory)
        self.worker.completed.connect(self.deliver)
        self.worker.failed.connect(self._failed)
        self.worker.languages.connect(self.update_languages)
        self.worker.start()
        self.hotkey_requested.connect(self.toggle_lookup)
        from meikipop.gui.selection import SelectionCapture
        self.selection = SelectionCapture(self)
        self.selection.completed.connect(self._selected_text_ready)
        self.selection.unavailable.connect(self._selection_unavailable)
        self.selection_requested.connect(self.request_selection)
        self.clipboard_requested.connect(lambda: self.lookup_selected(QApplication.clipboard().text()))
        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self.copy_shortcut.activated.connect(self.copy_sentence)
        self.back_shortcut = QShortcut(QKeySequence.StandardKey.Back, self)
        self.back_shortcut.activated.connect(self.go_back)
        self.anki_shortcut = QShortcut(self)
        self.anki_shortcut.activated.connect(self.add_to_anki)
        self.update_anki()
        self.apply_style()
        self._update_target_visibility()
        self.browser.clear()
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
            widget.setMouseTracking(True)
        self.setMouseTracking(True)
        self.installEventFilter(self)

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
    def interaction_state(self):
        from meikipop.gui.lookup_session import popup_mode
        return popup_mode(visible=self.isVisible(), preview=self._peek,
                          pinned=self.is_pinned, passive=self._passive_text)

    @property
    def preferred_foreign(self):
        mode = self.source.currentData()
        if mode == "en" and not self.settings.contains("profiles/en/target"):
            return self.settings.value("profile", "ja")
        return mode if mode not in ("auto", None) else self.settings.value("profile", "ja")

    def apply_style(self):
        colors = surface_colors(config.color_background, config.color_foreground)
        self.frame.setStyleSheet(frame_stylesheet(config.color_background, config.color_foreground,
                                                  config.background_opacity, config.font_family) + f'''
            QLineEdit,QComboBox,QTextBrowser {{background:transparent;color:{config.color_foreground};
                border:0;padding:3px;selection-background-color:{config.color_highlight_word};
                selection-color:{config.color_background};}}
            QLineEdit {{border-bottom:1px solid {colors['border']};}}
            QTextBrowser {{border-radius:0;padding:0;}}
            QComboBox QAbstractItemView {{background:{config.color_background};color:{config.color_foreground};}}
            QPushButton,QToolButton {{background:transparent;color:{config.color_foreground};
                border:0;border-radius:4px;padding:3px 5px;}}
            QPushButton:hover,QToolButton:hover,QToolButton:checked {{background:{colors['hover']};}}
            QPushButton:disabled,QToolButton:disabled {{color:{colors['muted']};}}
            QMenu {{background:{config.color_background};color:{config.color_foreground};
                border:1px solid {colors['border']};padding:4px;}}
            QMenu::item:selected {{background:{colors['hover']};}}
            QCheckBox {{color:{config.color_foreground};spacing:4px;}}
            QScrollBar:vertical {{background:transparent;width:9px;margin:0;}}
            QScrollBar::handle:vertical {{background:{colors['scroll']};min-height:20px;border-radius:1px;margin:0 3px;}}
            QScrollBar::handle:vertical:hover {{background:{colors['muted']};}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
            QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
            QScrollBar:horizontal {{background:transparent;height:3px;margin:0;}}
            QScrollBar::handle:horizontal {{background:{colors['scroll']};min-width:20px;border-radius:1px;}}
            QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {{width:0;}}
            QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal {{background:transparent;}}
        ''')
        font = QFont(config.font_family) if config.font_family else QFont()
        font.setPixelSize(config.font_size_definitions)
        self.browser.setFont(font)
        self.search.setFont(font)
        for button in self.findChildren(QToolButton):
            name = button.property("action_name")
            if name:
                button.setIcon(action_icon(name, config.color_foreground))

    def reload_appearance(self, render=True):
        from meikipop.gui.profile_appearance import load_appearance
        load_appearance(self.settings, self.preferred_foreign)
        self.apply_style()
        if render:
            self._render()

    def compact_preview(self):
        return self.settings.value(f"profiles/{self.preferred_foreign}/compact_preview",
                                   self.settings.value("compact_preview", True, type=bool), type=bool)

    def update_languages(self, languages):
        if "en" in languages and not self.settings.contains("profiles/en/target"):
            self.settings.setValue("profiles/en/target", "ja")
        current_source = self.source.currentData() or self.settings.value("profile", self.settings.value("source", "ja"))
        current_target = self.foreign.currentData() or "en"
        codes = list(dict.fromkeys([*configured_profiles(self.settings), *languages,
                                   *([current_source] if current_source != "auto" else [])]))
        with QSignalBlocker(self.source), QSignalBlocker(self.foreign):
            self.source.clear()
            self.foreign.clear()
            for code in codes:
                self.source.addItem(language_name(code), code)
            for code in dict.fromkeys([*LANGUAGE_NAMES, *codes]):
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
        if self.sender() is self.source and mode != "auto" and (mode != "en" or self.settings.contains("profiles/en/target")):
            with QSignalBlocker(self.foreign):
                self.foreign.setCurrentIndex(max(0, self.foreign.findData(self.settings.value(f"profiles/{mode}/target", default_partner(mode)))))
            self.settings.setValue("profile", mode)
        self._update_target_visibility()
        if self.foreign.currentData() == self.preferred_foreign:
            with QSignalBlocker(self.foreign):
                self.foreign.setCurrentIndex(self.foreign.findData(default_partner(mode)))
        self.settings.setValue("source", self.source.currentData())
        self.settings.setValue(f"profiles/{self.preferred_foreign}/target", self.foreign.currentData())
        self.browser.selection_lookup = self.settings.value(f"profiles/{self.preferred_foreign}/selection_lookup", False, bool)
        self.mode_changed.emit(self.source.currentData())
        self.reload_appearance()
        if self._setup is not None:
            self._setup.sync_profile(self.preferred_foreign)
        self.scan_settings_changed.emit()
        self._edited()

    def _invalidate(self):
        self.revision += 1
        self._pending_context = None
        self.stream_timer.stop()
        self._translation_chunk = None
        if self._partial_translation:
            self._partial_translation = False
            self._result = self._translation_previous
            if self._result is not None:
                self._render()
            else:
                self.browser.clear()
                self._render_identity = None
                self._document_revision = None
        self._pending_revision = None
        self.busy_delay.stop()
        self._remember_request = False
        self.debounce.stop()
        self.worker.cancel()
        if self.translation_worker is not None:
            self.translation_worker.cancel()
        if self.audio:
            self.audio.cancel()
        self._set_translation_busy(False)

    def _show_busy(self):
        if self._pending_revision == self.revision:
            self.translate.setIcon(action_icon("close", config.color_foreground))
            self.translate.setToolTip("Cancel translation" if self._translation_busy else "Cancel lookup")
            self.translate.setAccessibleName(self.translate.toolTip())
            if self._translation_busy and self._translation_model_state:
                self.translate.setToolTip(self.translate.toolTip() + "\n" + self._translation_model_state)
            self.translate.setEnabled(True)

    def _clear_actions(self):
        self.update_anki()
        self.audio_button.setEnabled(False)
        self.sentence_audio_button.setEnabled(False)
        self._clear_context()

    def _translate_clicked(self):
        if self._translation_busy or self._pending_revision is not None and not self.busy_delay.isActive():
            self._invalidate()
            self._restore_actions()
        else:
            self.submit(translate=True, context=bool(self._context))

    def _restore_actions(self):
        current = (self._result is not None and getattr(self, "_result_profile", None) == self.preferred_foreign
                   and (self._peek or self._result_input == self.search.text().strip()))
        self._display_revision = self.revision if current else None
        self.audio_button.setEnabled(bool(current and self._result.entries))
        self.sentence_audio_button.setEnabled(bool(current and self._result.text))
        if current:
            self.set_context(getattr(self, "_result_context", ""))

    def _set_translation_busy(self, busy):
        self._translation_busy = busy
        self.translate.setEnabled(bool(self.search.text().strip() or self._context))
        self.translate.setIcon(action_icon("translate", config.color_foreground))
        name = "Cancel translation" if busy else "Translate sentence" if self._peek and self._context else "Translate"
        model = self._result.translation_model if not busy and self._result is not None and self._display_revision == self.revision else ""
        self.translate.setToolTip(name + ("\n" + model if model else ""))
        self.translate.setAccessibleName(name)

    def _edited(self):
        self._invalidate()
        self._display_revision = None
        self._clear_actions()
        text = self.search.text().strip()
        self.translate.setEnabled(bool(text))
        self.status.setText("Searching…" if text else "")
        self.status.hide()
        if text:
            self.debounce.start()
        else:
            self._result = None
            self._result_context = ""
            self._render_identity = None
            self._document_revision = None
            self.browser.clear()

    def submit(self, translate=None, *, context=False, remember=False, selection=False):
        input_text = self.search.text().strip()
        selected = self.search.selectedText().strip() if selection else ""
        selected = selected if selected != input_text else ""
        sentence = self._context if context else input_text if selected else None
        text = self._context if context else selected or input_text
        lookup_context = None
        if selected:
            raw = self.search.text()
            # QLineEdit uses UTF-16 positions; analysis uses Python character offsets.
            before = raw.encode("utf-16-le")[:self.search.selectionStart() * 2].decode("utf-16-le")
            start = len(before) - (len(raw) - len(raw.lstrip()))
            selection_text = self.search.selectedText()
            start += len(selection_text) - len(selection_text.lstrip())
            lookup_context = (input_text, start, start + len(selected))
        self.debounce.stop()
        if not text:
            return
        self._sentence_lookup = translate is None and not selected
        if translate is None:
            translate = self._sentence_lookup and is_sentence(text)
        self._invalidate()
        self._last_request_translate = bool(translate)
        self._translation_model_state = ""
        self._translation_previous = self._result
        self._translation_base = self._result if translate and self._result is not None and (
            self._result.text == text or context) else None
        self._remember_request = remember or context or bool(selected)
        self._restore_actions()
        self._pending_revision = self.revision
        self.busy_delay.start()
        self._pending_context = (self.revision, sentence) if sentence else None
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
                self.translation_worker.progress.connect(self._translation_progress)
                self.translation_worker.translation_state.connect(self._translation_state_changed)
                self.translation_worker.start()
            worker = self.translation_worker
        source = self._result.source if context and self._result else "auto"
        target = None
        if translate:
            prefix = f"profiles/{self.preferred_foreign}/translation_"
            selected_source = self.settings.value(prefix + "source", "auto")
            selected_target = self.settings.value(prefix + "target", "auto")
            if selected_source != "auto":
                source = selected_source
            if selected_target != "auto":
                target = selected_target
        from meikipop.dictionary.translation import load_profile_settings
        try:
            translation_settings = load_profile_settings(self.settings, self.preferred_foreign) if translate else None
        except (ValueError, TypeError) as error:
            self._failed(self.revision, str(error))
            return
        worker.request(self.revision, text, source,
                       self.preferred_foreign, translate=bool(translate),
                       target=target,
                       pair=(self.preferred_foreign, self.foreign.currentData()),
                       translation_settings=translation_settings,
                       context=lookup_context if not translate else None,
                       morphology=not translate and self.preferred_foreign != "ja" and
                       self.settings.value(f"profiles/{self.preferred_foreign}/morphology", False, bool))

    def deliver(self, revision, result):
        if revision != self.revision or self._shutting_down:
            mark("discard", revision, reason="obsolete_lookup")
            return
        mark("accepted", revision)
        self._pending_revision = None
        self.stream_timer.stop()
        self._translation_chunk = None
        if self._partial_translation:
            self._result = self._translation_previous
        self._partial_translation = False
        self.busy_delay.stop()
        self._set_translation_busy(False)
        partial_japanese = result.source == "ja" and 0 < result.matched_length < len(result.text)
        sentence_fallback = self._sentence_lookup and partial_japanese
        if (not self._peek and not self._last_request_translate and not result.translation
                and (not result.entries or sentence_fallback or partial_japanese and self.settings.value(
                    f"profiles/{self.preferred_foreign}/auto_translate_miss", False, bool))):
            remember = self._remember_request
            context = self._pending_context[1] if self._pending_context else result.text
            self._display(result, remember=remember)
            self.set_context(context)
            self.submit(translate=True, context=True, remember=False)
            return
        if self._last_request_translate and self._translation_base is not None:
            base = self._translation_base
            screenshot = self._result_screenshot
            if result.translation:
                result = replace(result, entries=base.entries, suggestions=base.suggestions,
                                 kanji=base.kanji, matched_length=base.matched_length)
            else:
                result = replace(base, message=result.message)
        self._display(result, remember=self._remember_request)
        if self._last_request_translate and self._translation_base is not None:
            self._result_screenshot = screenshot
        if self._pending_context and self._pending_context[0] == revision:
            self.set_context(self._pending_context[1])
            self._pending_context = None
        elif not self._peek:
            self.set_context(result.text)
        self.status.setText(f"{language_name(result.source)} → {language_name(result.target)}")
        self.status.hide()

    def _translation_state_changed(self, revision, state):
        if revision == self.revision and self._translation_busy:
            self._translation_model_state = state
            self.translate.setToolTip("Cancel translation\n" + state)

    def _translation_progress(self, revision, result):
        if revision != self.revision or self._shutting_down or not self._translation_busy:
            mark("discard", revision, reason="obsolete_chunk")
            return
        self._translation_chunk = result
        if not self.stream_timer.isActive():
            self.stream_timer.start()

    def _flush_translation(self):
        result, self._translation_chunk = self._translation_chunk, None
        if result is None or not self._translation_busy:
            return
        if self.browser.selecting:
            self._translation_chunk = result
            self.stream_timer.start()
            return
        bar = self.browser.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        base = self._translation_base
        if base is not None:
            result = replace(result, entries=base.entries, suggestions=base.suggestions, kanji=base.kanji)
        self._result = result
        self._partial_translation = True
        self._render()
        if at_end:
            bar.setValue(bar.maximum())

    def _display(self, result, remember=True, expanded=(), details_expanded=None):
        same = self._result is not None and (self._result.text, self._result.source, self._result.target) == (
            result.text, result.source, result.target)
        previous_context = getattr(self, "_result_context", "")
        if remember and not self._new_chain and self._result is not None and not same:
            self._history.append((self._result, getattr(self, "_result_context", ""),
                                  self._result_profile, self._result_target, tuple(self._expanded),
                                  self.browser.verticalScrollBar().value(), tuple(self._details_expanded),
                                  self._result_input, self._result_screenshot))
            self._history = self._history[-30:]
        if details_expanded is not None:
            self._details_expanded = set(details_expanded)
        elif self._new_chain or self._result is None or result.entries != self._result.entries:
            self._details_expanded.clear()
        self._new_chain = False
        self._result = result
        self._display_revision = self.revision
        self._result_profile = self.preferred_foreign
        self._result_target = self.foreign.currentData()
        self._result_context = previous_context if same else ""
        if not same:
            self._result_screenshot = None
        self._result_input = self.search.text().strip()
        self._expanded = set(expanded)
        self._kanji_expanded = False
        self._render()
        self.back.setEnabled(bool(self._history))
        self.back.setVisible(bool(self._history))
        self._update_trail()
        self.audio_button.setEnabled(bool(result.entries))
        self.update_anki()
        self.sentence_audio_button.setEnabled(bool(result.text))
        autoplay = audio_autoplay_mode(self.settings, self.preferred_foreign)
        if (self._peek or self._selection_lookup) and (result.entries or result.translation) and autoplay == "lookup":
            self._autoplay()

    def _render(self):
        if self._result is not None:
            if self.browser.selecting:
                self.render_timer.start(50)
                return
            compact = self.compact_preview()
            expanded = self._expanded
            if self._peek and not compact:
                expanded = {entry.source for entry in self._result.entries}
            show_source, source_text = self._peek, None
            if self._peek and self.is_pinned:
                show_source = self.settings.value(f"profiles/{self.preferred_foreign}/pinned_sentence", True, bool)
                source_text = self._result_context or (self._result.text if self._result.translation else "")
                if show_source and source_text:
                    width = (self.browser.viewport().width() - self.audio_actions.sizeHint().width()
                             - 8 - 2 * self.browser.document().documentMargin())
                    source_text = _compact_context(source_text, self.browser.font(), width)
            self._place_actions()
            from meikipop.gui.profile_appearance import DEFAULTS
            identity = (repr(self._result), self.preferred_foreign, tuple(sorted(expanded)),
                        tuple(sorted(self._details_expanded)),
                        self._kanji_expanded, self._peek, self.is_pinned, compact,
                        tuple(getattr(config, key) for key in DEFAULTS), self.devicePixelRatioF(),
                        self.audio_actions.sizeHint().width(), show_source, source_text if show_source else None,
                        self.settings.value("profiles/ja/headword_furigana", False, bool),
                        self.settings.value("profiles/ja/definition_furigana", True, bool),
                        self.settings.value("profiles/ja/show_pitch", True, bool),
                        self.settings.value(f"profiles/{self.preferred_foreign}/combine_frequencies", True, bool))
            if identity == self._render_identity:
                mark("render_reused", self.revision)
                return
            scroll = self.browser.verticalScrollBar().value()
            anchor = self.browser.cursorForPosition(self.browser.viewport().rect().topLeft())
            block_text, offset = anchor.block().text(), self.browser.cursorRect(anchor).top()
            mark("html_begin", self.revision)
            self.browser.setHtml(render_result(self._result, expanded,
                                               self._kanji_expanded or self._peek and not compact,
                                               preview=self._peek and not self.is_pinned and compact,
                                               overlay_actions=(self.audio_actions.sizeHint().width() + 8) if self._peek and self.is_pinned else 0,
                                               show_source=show_source, source_text=source_text,
                                               details_expanded=self._details_expanded,
                                               headword_furigana=self.settings.value("profiles/ja/headword_furigana", False, bool),
                                               definition_furigana=self.settings.value("profiles/ja/definition_furigana", True, bool),
                                               show_pitch=self.settings.value("profiles/ja/show_pitch", True, bool),
                                               combine_frequencies=self.settings.value(f"profiles/{self.preferred_foreign}/combine_frequencies", True, bool)))
            self._render_identity = identity
            self._document_revision = self.revision
            mark("document_ready", self.revision)
            if scroll:
                block = self.browser.document().begin()
                while block.isValid() and block.text() != block_text:
                    block = block.next()
                if block.isValid() and block_text:
                    from PyQt6.QtGui import QTextCursor
                    scroll = (self.browser.verticalScrollBar().value()
                              + self.browser.cursorRect(QTextCursor(block)).top() - offset)
                self.browser.verticalScrollBar().setValue(scroll)
            self.browser.setToolTip("")
            self.fit_timer.start(0)

    def _fit_preview(self):
        if self._shutting_down or not self._peek or self.is_pinned or not self.compact_preview():
            return
        identity = (self._render_identity, self.browser.viewport().width())
        if identity == self._fit_identity and not self._needs_place:
            return
        self._fit_identity = identity
        mark("fit", self.revision)
        self.setMinimumHeight(72)
        self.layout().activate()
        document = self.browser.document()
        document.setTextWidth(self.browser.viewport().width())
        chrome = self.height() - self.browser.viewport().height()
        desired = math.ceil(document.size().height()) + chrome + 2
        maximum = max(190, self.settings.value("preview_max_height", 340, type=int))
        if desired > maximum:
            limit = maximum - chrome - 2
            bottoms = []
            block = document.begin()
            while block.isValid():
                top = document.documentLayout().blockBoundingRect(block).top()
                text_layout = block.layout()
                for index in range(text_layout.lineCount()):
                    line = text_layout.lineAt(index)
                    bottom = math.ceil(top + line.y() + line.height())
                    if bottom <= limit:
                        bottoms.append(bottom)
                block = block.next()
            if bottoms:
                desired = max(bottoms) + chrome
        height = min(maximum, max(self.minimumSizeHint().height(), desired))
        if self.height() != height:
            mark("geometry", self.revision)
            if self.isVisible() and not self._needs_place:
                self._resize_expanded(QSize(self.width(), height))
            else:
                self.resize(self.width(), height)
        if self.isVisible() and self._needs_place:
            self._place()
            self._needs_place = False

    def set_compact_preview(self, enabled):
        self.settings.setValue(f"profiles/{self.preferred_foreign}/compact_preview", bool(enabled))
        self._render()

    def _failed(self, revision, message):
        if revision in (-1, self.revision):
            if self._partial_translation:
                self._invalidate()
            self._pending_revision = None
            self.busy_delay.stop()
            self._set_translation_busy(False)
            self._restore_actions()
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
        if url.scheme() == "details" and re.fullmatch(r"\d+:\d+:\d+", url.path()):
            key = url.path()
            self._details_expanded.symmetric_difference_update((key,))
            self._render()
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
        self._display_revision = None
        self._clear_actions()
        self._set_peek(False)
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self.submit(remember=True)

    def _input_menu(self, point):
        menu = self.search.createStandardContextMenu()
        if self.search.hasSelectedText():
            menu.addSeparator()
            menu.addAction("Look up", lambda: self.submit(translate=False, selection=True))
        menu.exec(self.search.mapToGlobal(point))
        menu.deleteLater()

    def go_back(self):
        if not self._history:
            return
        self._invalidate()
        previous = self._history.pop()
        result, context, profile, target, expanded, scroll = previous[:6]
        with QSignalBlocker(self.search), QSignalBlocker(self.source), QSignalBlocker(self.foreign):
            self.search.setText(previous[7] if len(previous) > 7 else result.text)
            if self.source.findData(profile) < 0:
                self.source.addItem(language_name(profile), profile)
            self.source.setCurrentIndex(self.source.findData(profile))
            self.foreign.setCurrentIndex(self.foreign.findData(target))
        self._update_target_visibility()
        self.mode_changed.emit(self.source.currentData())
        self.settings.setValue("profile", profile)
        self.settings.setValue("source", self.source.currentData())
        self.settings.setValue(f"profiles/{profile}/target", target)
        self.reload_appearance(render=False)
        if self._setup is not None:
            self._setup.sync_profile(profile)
        self.scan_settings_changed.emit()
        self._display(result, remember=False, expanded=expanded,
                      details_expanded=previous[6] if len(previous) > 6 else ())
        self.set_context(context)
        self._result_screenshot = previous[8] if len(previous) > 8 else None
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
        mark("place", self.revision)
        point = QCursor.pos()
        if self._peek:
            self._lookup_anchor = point
        tray = self.tray_geometry() if not self._peek and not self._manual_at_cursor and self.tray_geometry else None
        if tray and not tray.isNull():
            point = tray.center()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
            if not self._peek and not self._manual_at_cursor:
                x = tray.center().x() if tray and not tray.isNull() else area.right()
                y = area.bottom() - self.height() - 8
                if sys.platform == "darwin":
                    y = area.top() + 8
                    if tray and not tray.isNull():
                        y = max(y, tray.bottom() + 8)
                    y = min(y, area.bottom() - self.height())
                self.move(max(area.left(), min(x - self.width() // 2, area.right() - self.width())),
                          max(area.top(), y))
            else:
                self.move(*popup_position(point.x(), point.y(), self.size(), area, config.popup_position_mode))

    def _set_peek(self, peek):
        if peek and not self._peek:
            self._normal_size = self.size()
        elif not peek and self._peek and not self.is_pinned:
            self.setMinimumHeight(190)
            self._resize_expanded()
        self._peek = bool(peek)
        self.setSizeGripEnabled(self.is_pinned or not self._peek)
        self._place_actions()
        self.search.setVisible(not self._peek)
        self.actions_row.setVisible(self.is_pinned or not self._peek)

    def _resize_expanded(self, requested=None):
        requested = requested or self._normal_size
        previous = self.geometry()
        screen = QApplication.screenAt(previous.center()) or QApplication.primaryScreen()
        if screen is None:
            self.resize(requested)
            return
        self.setGeometry(expanded_geometry(previous, requested, screen.availableGeometry(),
                                           self._lookup_anchor if self._peek else None))

    def _place_actions(self):
        if self._shutting_down:
            return
        self.mode_row.hide()
        self.header.setVisible(not self._peek)
        if self._peek:
            viewport = self.browser.viewport()
            if self.audio_actions.parentWidget() is not viewport:
                self.audio_actions.setParent(viewport)
            self.audio_actions.adjustSize()
            self.audio_actions.move(max(0, viewport.width() - self.audio_actions.width() - 4), 0)
            self.audio_actions.setVisible(self.is_pinned)
            self.audio_actions.raise_()
        else:
            if self.audio_actions.parentWidget() is not self.header:
                self.header.layout().addWidget(self.audio_actions)
            self.audio_actions.show()

    def open_search(self, text="", *, at_cursor=False, passive=False, selection=False):
        self.remember_foreground()
        self._history.clear()
        self._new_chain = True
        self.title.clear()
        self.back.hide()
        self._passive_text = passive
        self._selection_lookup = selection
        self._opening_search = True
        self._manual_at_cursor = at_cursor
        self.pin.setChecked(False)
        self._set_peek(False)
        self._clear_context()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, self._passive_text)
        if not self.is_pinned or not self.isVisible():
            self._place()
        self.show()
        self.raise_()
        if not self._passive_text:
            self.activateWindow()
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self._edited()
        self.search.setFocus()
        self.search.selectAll()
        def finish_opening():
            self._opening_search = False
        def focus():
            from meikipop.utils.window_focus import focus_search
            if self.isVisible() and not self._passive_text:
                focus_search(self)
            if (sys.platform == "darwin" and QApplication.platformName() != "offscreen"
                    and self.isVisible() and not self.isActiveWindow()):
                # AppKit activation is asynchronous; an earlier focus-loss
                # event must not dismiss Search before activation arrives.
                QTimer.singleShot(300, finish_opening)
            else:
                finish_opening()
        QTimer.singleShot(0, focus)
        if text:
            self.submit()

    def lookup_selected(self, text, *, passive=False):
        if text.strip():
            self.open_search(text.strip()[:2000], at_cursor=True, passive=passive, selection=True)

    def toggle_lookup(self):
        from PyQt6.QtWidgets import QKeySequenceEdit
        if isinstance(QApplication.focusWidget(), QKeySequenceEdit):
            return
        if (self.isVisible() and self.search.hasFocus() and self.search.hasSelectedText()
                and self.search.selectedText().strip() != self.search.text().strip()):
            self.submit(translate=False, selection=True)
        elif self.isVisible() and self.browser.selected_text():
            self.browser.lookup_selection()
        elif self.isVisible():
            self.selection.cancel()
            self.hide()
        elif self.selection.pending:
            self.selection.cancel()
            self._selection_for_search = False
        else:
            self.request_lookup()

    def request_selection(self):
        self._selection_for_search = False
        self._selection_passive = False
        self.selection.start(wait_for_modifiers=True)

    def request_lookup(self):
        self._lookup_clipboard = QApplication.clipboard().text()[:2000]
        if QApplication.activeWindow() is not None:
            focused = QApplication.focusWidget()
            text = focused.selectedText() if isinstance(focused, QLineEdit) else (
                self.browser.selected_text() if focused in (self.browser, self.browser.viewport()) else "")
            self.open_search(text or self._lookup_clipboard)
            return
        if self.selection.pending:
            return
        self._selection_for_search = True
        self.selection.start(wait_for_modifiers=True, copy_timeout=.05)

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

    def scan_hold_changed(self, active):
        self._scan_hold_active = active
        self._autoplayed = set() if active else None

    def _audio_key(self):
        result = self._result
        if result.entries:
            entry = result.entries[0]
            return entry.language, entry.term, entry.reading or ""
        return result.source, result.text, ""

    def _autoplay(self):
        if self._result is None:
            return
        key = self._audio_key()
        if self._autoplayed is not None:
            if key in self._autoplayed:
                return
            self._autoplayed.add(key)
        self.play_audio()

    def audio_source_menu(self, point):
        if self._result is None or not self._result.entries:
            return
        from meikipop.audio.sources import database_path, source_label, source_order
        language = self._result.entries[0].language
        menu = QMenu(self.audio_button)
        menu.addAction("Use source priority", self.play_audio)
        menu.addSeparator()
        for source in source_order(self.settings, language):
            action = menu.addAction(source_label(source), lambda checked=False, source=source: self.play_audio(source=source))
            action.setEnabled(source in ("tts", "online") or bool(database_path(self.settings, language)))
        clip = getattr(self.audio, "current_clip", None)
        if clip and clip.page_url.startswith("https://commons.wikimedia.org/"):
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            menu.addSeparator()
            credit = menu.addAction("Recording source…", lambda: QDesktopServices.openUrl(QUrl(clip.page_url)))
            credit.setToolTip(clip.attribution)
            menu.setToolTipsVisible(True)
        menu.addSeparator()
        menu.addAction("Audio settings…", self.open_audio_settings)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(self.audio_button.mapToGlobal(point))

    def open_audio_settings(self):
        self.open_settings()
        self._setup.show_audio()

    def update_anki(self):
        enabled = self.settings.value(f"profiles/{self.preferred_foreign}/anki/enabled", False, bool)
        ready = enabled and self._result is not None and bool(self._result.entries) and self._display_revision == self.revision
        self.anki_button.setVisible(enabled)
        self.anki_button.setEnabled(ready)
        if hasattr(self, "anki_shortcut"):
            binding = self.settings.value(f"profiles/{self.preferred_foreign}/anki/shortcut", "")
            self.anki_shortcut.setKey(QKeySequence(binding))
            self.anki_shortcut.setEnabled(ready and bool(binding))

    def add_to_anki(self):
        from meikipop.anki import load_settings
        from meikipop.gui.anki import AnkiExportDialog
        options = load_settings(self.settings, self.preferred_foreign)
        if not options.enabled or self._display_revision != self.revision or not self._result or not self._result.entries:
            return
        if self._anki_dialog is not None and self._anki_dialog.isVisible():
            self._anki_dialog.raise_()
            self._anki_dialog.activateWindow()
            return
        if not options.deck or not options.model or not options.fields:
            self.open_settings()
            self._setup.show_anki()
            return
        if self._anki_dialog is not None:
            self._anki_dialog.deleteLater()
        self._anki_dialog = AnkiExportDialog(self._result.entries, self._result_context,
                                             self.browser.selected_text(), options, self,
                                             translation=self._result.translation,
                                             screenshot=self._result_screenshot,
                                             directory=self.directory,
                                             audio_clip=getattr(self.audio, "current_clip", None))
        self._anki_dialog.show()

    def play_audio(self, *, sentence=False, translation=False, source=None):
        if self._result is None or self._display_revision != self.revision:
            return
        if not sentence and not translation and self._autoplayed is not None:
            self._autoplayed.add(self._audio_key())
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
            options = {"source": source} if source else {}
            self.audio.play(result.entries[0], self.revision, self.settings, profile=self.preferred_foreign, **options)
            return
        self.audio.play_text(text, language, self.revision, self.settings, profile=self.preferred_foreign)

    def show_entries(self, entries, text="", source="ja", peek=False, kanji=()):
        if peek and self.is_pinned:
            return False
        entries = tuple(entries or ())
        if (peek and self._peek and self._result is not None and self._result.text == text
                and self._result.source == source and self._result.entries == entries
                and self._result.kanji == tuple(kanji) and self.isVisible()):
            if self._autoplayed is not None and audio_autoplay_mode(self.settings, self.preferred_foreign) == "lookup":
                self._autoplay()
            return True
        self._invalidate()
        self._result_screenshot = None
        self._history.clear()
        self._new_chain = True
        entries = tuple(entries or ())
        partner = self.foreign.currentData()
        target = self.preferred_foreign if source == partner else partner
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
        if peek and self.compact_preview():
            self._needs_place = True
            self.fit_timer.start(0)
        elif not self.is_pinned:
            self._place()
        self.show()
        if not peek:
            self.raise_()
        return True

    def set_context(self, text, start=0, end=None):
        previous = getattr(self, "_result_context", "")
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
        if self._peek and self.is_pinned and previous != self._context:
            self._render()

    def _clear_context(self):
        previous = getattr(self, "_result_context", "")
        self.set_context("")
        self._result_context = previous

    def copy_sentence(self):
        if self._context:
            QApplication.clipboard().setText(self._context)
            self.hide()

    def _pin_changed(self, checked):
        if checked:
            self.remember_foreground()
        self.pin.setToolTip("Unpin" if checked else "Pin")
        self.setSizeGripEnabled(checked or not self._peek)
        if self._peek:
            if checked:
                self.setMinimumHeight(190)
                self._resize_expanded()
            else:
                self._normal_size = self.size()
        if checked:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            if sys.platform == "darwin" and QApplication.platformName() != "offscreen":
                from meikipop.utils.window_focus import activate_application
                self._opening_search = True
                activate_application()
                QTimer.singleShot(300, lambda: setattr(self, "_opening_search", False))
            self.activateWindow()
            self.browser.setFocus(Qt.FocusReason.MouseFocusReason)
            if self._peek and self._result is not None:
                self._expanded.update(entry.source for entry in self._result.entries)
                self._kanji_expanded = True
        self.context_label.hide()
        self.actions_row.setVisible(checked or not self._peek)
        self._place_actions()
        self._render()

        if checked and self._peek and audio_autoplay_mode(self.settings, self.preferred_foreign) == "pin":
            self._autoplay()

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Paint and hasattr(self, "browser")
                and watched is self.browser.viewport() and self._document_revision is not None
                and self._paint_revision != self._document_revision):
            self._paint_revision = self._document_revision
            mark("paint", self._document_revision)
        if event.type() == QEvent.Type.Resize and hasattr(self, "browser") and watched is self.browser.viewport():
            self._place_actions()
            if self._peek and self.is_pinned and hasattr(self, "render_timer"):
                self.render_timer.start(0)
        if event.type() == QEvent.Type.ToolTip and not isinstance(watched, QToolButton):
            QToolTip.hideText()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self._passive_text:
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
                self.activateWindow()
            self._passive_text = False
        if (event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton
                and self._peek and not self.is_pinned
                and watched not in (self.dismiss_button, self.pin)):
            if watched is self.browser.viewport():
                self._engage_press = event.globalPosition().toPoint()
            else:
                self.pin.setChecked(True)
        elif event.type() == QEvent.Type.MouseButtonRelease and self._engage_press is not None:
            distance = (event.globalPosition().toPoint() - self._engage_press).manhattanLength()
            self._engage_press = None
            if distance < QApplication.startDragDistance() and not self.browser.selected_text():
                self.browser.selecting = False
                self._pin_anchor_click = bool(self.browser.anchorAt(event.position().toPoint()))
                self.pin.setChecked(True)
                QTimer.singleShot(0, lambda: setattr(self, "_pin_anchor_click", False))
        elif event.type() == QEvent.Type.MouseButtonRelease and self._pin_anchor_click:
            QTimer.singleShot(0, lambda: setattr(self, "_pin_anchor_click", False))
        if watched is self.title:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_position = event.globalPosition().toPoint() - self.pos()
                self._drag_start = event.globalPosition().toPoint()
                self._dragging = False
            elif event.type() == QEvent.Type.MouseMove and self._drag_position is not None:
                point = event.globalPosition().toPoint()
                if not self._dragging and (point - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                    self._dragging = True
                    if self.windowHandle() and self.windowHandle().startSystemMove():
                        return True
                if self._dragging:
                    screen = QApplication.screenAt(point) or QApplication.primaryScreen()
                    area = screen.availableGeometry()
                    position = point - self._drag_position
                    self.move(max(area.left(), min(position.x(), area.right()-self.width()+1)),
                              max(area.top(), min(position.y(), area.bottom()-self.height()+1)))
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_position = None
                if self._dragging:
                    self._dragging = False
                    return True
        if self._edge_event(event):
            return True
        return super().eventFilter(watched, event)

    def _edge_event(self, event):
        if self._peek and not self.is_pinned or event.type() not in (
                QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            return False
        point = event.globalPosition().toPoint()
        local = self.mapFromGlobal(point)
        edges = Qt.Edge(0)
        if local.x() < 5:
            edges |= Qt.Edge.LeftEdge
        elif local.x() >= self.width() - 5:
            edges |= Qt.Edge.RightEdge
        if local.y() < 5:
            edges |= Qt.Edge.TopEdge
        elif local.y() >= self.height() - 5:
            edges |= Qt.Edge.BottomEdge
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        diagonal = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if horizontal and vertical and diagonal else
                       Qt.CursorShape.SizeBDiagCursor if horizontal and vertical else
                       Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor if vertical else
                       Qt.CursorShape.ArrowCursor)
        if event.type() == QEvent.Type.MouseButtonPress and edges and event.button() == Qt.MouseButton.LeftButton:
            if not self.windowHandle() or not self.windowHandle().startSystemResize(edges):
                self._resize_start = (point, self.geometry(), edges)
            return True
        if self._resize_start:
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._resize_start = None
            elif event.type() == QEvent.Type.MouseMove:
                origin, rect, edges = self._resize_start
                rect = type(rect)(rect)
                delta = point - origin
                area = (QApplication.screenAt(point) or QApplication.primaryScreen()).availableGeometry()
                if edges & Qt.Edge.LeftEdge:
                    rect.setLeft(max(area.left(), min(rect.right()-self.minimumWidth()+1, rect.left()+delta.x())))
                if edges & Qt.Edge.RightEdge:
                    rect.setRight(min(area.right(), max(rect.left()+self.minimumWidth()-1, rect.right()+delta.x())))
                if edges & Qt.Edge.TopEdge:
                    rect.setTop(max(area.top(), min(rect.bottom()-self.minimumHeight()+1, rect.top()+delta.y())))
                if edges & Qt.Edge.BottomEdge:
                    rect.setBottom(min(area.bottom(), max(rect.top()+self.minimumHeight()-1, rect.bottom()+delta.y())))
                self.setGeometry(rect)
            return True
        return False

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            QTimer.singleShot(0, self._dismiss_if_inactive)

    def _dismiss_if_inactive(self):
        if self._opening_search or self._passive_text:
            return
        if self.geometry().contains(QCursor.pos()):
            return
        setup_open = self._setup is not None and self._setup.isVisible()
        # A macOS source pin click also reaches the source application, which
        # can retain focus. Explicit outside clicks still dismiss pinned OCR.
        if (not self._peek or (self.is_pinned and sys.platform != "darwin")) and not self.isActiveWindow() and not setup_open \
                and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
            self.hide()

    def showEvent(self, event):
        from meikipop.utils.window_focus import configure_macos_popup
        configure_macos_popup(self)
        super().showEvent(event)

    def hideEvent(self, event):
        if self._capture_visibility:
            super().hideEvent(event)
            return
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
        if not self._capture_visibility and QApplication.platformName() != "offscreen":
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
        self._setup.sync_profile(self.preferred_foreign)
        self._setup.showNormal()
        self._setup.raise_()
        from meikipop.utils.window_focus import activate_application
        activate_application()
        self._setup.activateWindow()

    def refresh_library(self):
        self._render_identity = None
        self.worker.refresh()
        if self.translation_worker is not None:
            self.translation_worker.refresh()
        self._edited()
        self.dictionaries_changed.emit()

    def apply_shortcut(self, value, preset=None):
        from meikipop.gui.text_shortcuts import TextHotKeys, validate_shortcuts
        from meikipop.utils.macos import InputMonitoringPermissionError
        bindings = {value: self.hotkey_requested.emit} if value else {}
        validate_shortcuts([value])
        replacement = TextHotKeys(bindings) if bindings else None
        warning = ""
        if replacement:
            try:
                replacement.start()
            except InputMonitoringPermissionError as error:
                warning = str(error)
                replacement = None
                self.show_message(warning)
        previous, self._keys = self._keys, replacement
        if previous:
            previous.stop()
            previous.join(timeout=2)
        self.settings.setValue("hotkey", value)
        if preset is not None:
            self.settings.setValue("hotkey_preset", preset)
        return warning

    def restore_shortcut(self, explicit=None):
        default = "<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d"
        binding = explicit if explicit is not None else self.settings.value("hotkey", default)
        self.apply_shortcut(binding)

    def shutdown(self):
        if self._shutting_down:
            return
        onboarding = getattr(self, "_language_setup", None)
        if onboarding is not None:
            onboarding.cancelled.set()
        self._shutting_down = True
        self.selection.cancel()
        if self.audio:
            self.audio.shutdown()
        self.debounce.stop()
        for timer in (self.busy_delay, self.fit_timer, self.render_timer, self.stream_timer):
            timer.stop()
        self._translation_chunk = None
        self.worker.shutdown()
        if self.translation_worker is not None:
            self.translation_worker.shutdown()
        if self._setup is not None:
            self._setup.cancel_operation()
            self._setup.audio_sources.shutdown()
        if self._keys:
            self._keys.stop()
            self._keys = None


def shortcut_preset():
    return "Ctrl+Shift+D"


def audio_autoplay_mode(settings, profile):
    legacy = settings.value(f"profiles/{profile}/audio_autoplay",
                            config.audio_autoplay_enabled if profile == "ja" else False, type=bool)
    return settings.value(f"profiles/{profile}/audio_autoplay_mode", "lookup" if legacy else "off")
