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

from PyQt6.QtCore import QObject, QEvent, QLocale, QPointF, QSettings, QSignalBlocker, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QFontMetricsF, QImage, QKeySequence, QShortcut, QTextBlockFormat, QTextCursor, QTextDocument, QTextFormat, QTextLayout, QTextOption
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QSizePolicy, QSplitter, QStackedWidget, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from meikipop.config.config import config
from meikipop.dictionary.search import SearchEngine, SearchResult
from meikipop.gui.popup_style import expanded_geometry, frame_stylesheet, popup_position, surface_colors
from meikipop.gui.action_icons import action_icon
from meikipop.gui.ruby import RubyBrowser, TAG_PREFIX, ruby_html
from meikipop.gui.gloss_content import normalize_definitions
from meikipop.language.profiles import configured_profiles, default_partner, visible_profiles
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
                morphology=False, context=None, exact_only=False):
        self.cancel()
        mark("dispatch", revision, translation=translate)
        with self._condition:
            self._pending = (revision, text, source, foreign, translate, target, pair, translation_settings, morphology,
                             context, exact_only, threading.Event())
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
                        revision, text, source, foreign, translate, target, pair, translation_settings, morphology, context, exact_only, cancelled = pending
                        mark("dequeue", revision)
                        options = {"target": target} if target else {}
                        if pair:
                            options.update(pair=pair, translation_settings=translation_settings)
                        if morphology:
                            options["morphology"] = True
                        if context is not None:
                            options["context"] = context
                        if exact_only:
                            options["exact_only"] = True
                        if isinstance(engine, SearchEngine):
                            options.update(cancelled=cancelled, request_id=revision,
                                           translation_progress=lambda result: self._emit(self.progress, revision, result),
                                           translation_state=lambda value: self._emit(self.translation_state, revision, value))
                            if source in ("ja", "auto"):
                                options["max_lookup_length"] = config.max_lookup_length
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
    _tag_labels = {
        "noun (common) (futsuumeishi)": "noun",
        "noun or participle which takes the aux. verb suru": "suru",
        "transitive verb": "transitive", "intransitive verb": "intransitive",
        "female given name or forename": "female name", "female given name": "female name",
        "male given name or forename": "male name", "male given name": "male name",
        "given name or forename, gender not specified": "given name",
        "family or surname": "surname", "place name": "place",
        "adjective (keiyoushi)": "i-adjective",
        "adjectival nouns or quasi-adjectives (keiyodoshi)": "na-adjective",
        "adverb (fukushi)": "adverb", "expressions (phrases, clauses, etc.)": "expression",
        "other surface forms and readings": "forms", "unclassified": "unclassified",
    }

    @staticmethod
    def _is_tag(node):
        data = node.get("data") if isinstance(node, dict) else None
        return (isinstance(data, dict) and data.get("content") != "forms-label"
                and (data.get("class") == "tag" or data.get("content") == "tag"))

    def _tags_to_html(self, nodes):
        if not self.grammar:
            return ""
        labels, descriptions = [], []
        for node in nodes:
            html = super()._node_to_html(node.get("content"))
            document = QTextDocument()
            document.setHtml(html)
            description = document.toPlainText().strip()
            if description:
                descriptions.append(description)
                if not re.fullmatch(r"JMdict Sense #\d+", description, re.IGNORECASE):
                    labels.append(self._tag_labels.get(description, description))
        if not labels:
            return ""
        description = " · ".join(dict.fromkeys(descriptions))
        label = " · ".join(dict.fromkeys(labels))
        return (f'<div class="metadata"><a href="{TAG_PREFIX}{quote(description, safe="")}" '
                f'style="color:{self.colors["muted"]};text-decoration:none">'
                f'<small>[{escape(label)}]</small></a></div>')

    def __init__(self, expanded=False, limit=360, preview=False, generic_source=False, term="",
                 details_expanded=(), detail_prefix="", definitions=(), definition_furigana=False, preview_definitions=1,
                 grammar=True):
        super().__init__()
        self.preview_definitions = preview_definitions
        self.definition_furigana = definition_furigana
        self.grammar = grammar
        self.colors = surface_colors(config.color_background, config.color_foreground)
        self.expanded = expanded
        self.preview = preview
        self.generic_source = generic_source
        self.term = term
        self.first_source = ""
        self._preview_source_complete = False
        self.remaining = limit
        self.clipped = False
        self.supplements = []
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
            node = re.sub(r"\n[ \t]*\n+", "\n", node)
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
            index = 0
            while index < len(node):
                child = node[index]
                if not self.expanded and self.remaining is not None and self.remaining <= 0:
                    self.clipped = True
                    break
                tags = []
                while index < len(node) and self._is_tag(node[index]):
                    tags.append(node[index])
                    index += 1
                if tags:
                    parts.append(self._tags_to_html(tags))
                else:
                    parts.append(self._node_to_html(child))
                    index += 1
            return "".join(parts)
        if isinstance(node, dict):
            if self._is_tag(node):
                return self._tags_to_html((node,))
            tag = node.get("tag")
            data = node.get("data")
            if (tag in ("span", "ruby") and not node.get("style")
                    and (not isinstance(data, dict) or not (data.get("class") or data.get("content")))):
                return (self._ruby_to_html(node.get("content")) if tag == "ruby"
                        else self._node_to_html(node.get("content")))
            if node.get("tag") == "details":
                return self._details_to_html(node)
            node = dict(node)
            tag, content = node.get("tag", ""), node.get("content")
            data = node.get("data", {})
            kind = str(data.get("content", "")) if isinstance(data, dict) else ""
            semantic_kind = re.sub(r"[-_]", "", kind).lower()
            if kind == "backlink" or semantic_kind == "formslabel":
                return ""
            if semantic_kind in ("forms", "formstable", "formslist"):
                self.clipped = True
                if self.expanded:
                    supplement = dict(node, data={})
                    self.supplements.append(("Forms", self._node_to_html(supplement)))
                return ""
            if semantic_kind == "attribution":
                return ""
            if not self.expanded and semantic_kind in ("explanation", "extrainfo"):
                self.clipped = True
                return ""
            if kind == "section-heading":
                if not self.expanded:
                    return ""
                return f'<p style="margin:6px 0 2px;font-weight:bold">{self._node_to_html(content)}</p>'
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
                marked_senses = (isinstance(content, list) and bool(content) and all(
                    isinstance(child, dict) and isinstance(child.get("data"), dict)
                    and "meaning" in child["data"] for child in content))
                if ((tag in ("ol", "ul") and kind != "glossary") or kind == "glosses" or numbered_senses or marked_senses) and isinstance(content, list):
                    senses = [child for child in content if (not isinstance(child, str) or child.strip())
                              and not (isinstance(child, dict) and isinstance(child.get("data"), dict)
                                       and child["data"].get("content") == "section-heading")]
                    maximum = self.preview_definitions if self.preview else 0
                    if maximum and len(senses) > maximum:
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
                return self._tags_to_html((node,))
            if kind == "tags":
                return self._node_to_html(content)
            if tag in ("td", "th"):
                labels = {"form-pri": "common", "form-valid": "valid", "form-rare": "rare",
                          "form-out": "obsolete", "form-irr": "irregular"}
                if source_class in labels:
                    node["content"] = labels[source_class]
            if kind in ("sense-groups", "sense-group"):
                tag = node["tag"] = "div"
            if kind == "sense-group" and isinstance(content, list):
                # Keep leading POS tags beside the first sense, not on an empty-height line.
                children = list(content)
                for index, child in enumerate(children):
                    if not isinstance(child, dict):
                        break
                    child_data = child.get("data", {})
                    if not isinstance(child_data, dict):
                        break
                    if child_data.get("content") == "sense" and index:
                        children[index] = dict(child, tag="span")
                        break
                    if child_data.get("class") != "tag" and child_data.get("content") != "tag":
                        break
                node["content"] = children
            # Keep a small, safe subset of typography. Dictionary CSS must not
            # inject attributes, override the theme or stretch the popup.
            safe_style = {}
            if tag == "ol" and isinstance(content, list) and len(content) > 9:
                safe_style["marginLeft"] = "20px"
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
            elif isinstance(definition, dict) and definition.get("type") == "image":
                content = dict(definition, tag="img")
            elif isinstance(definition, dict) and definition.get("type") in ("text", "structured-content"):
                content = definition.get("text" if definition["type"] == "text" else "content")
            else:
                continue
            rendered = self._node_to_html(content)
            if rendered and (re.sub(r"<[^>]*>", "", rendered).strip() or '<img ' in rendered):
                parts.append(rendered)
        return parts


def _metadata(entries, combine_frequencies=True, show_frequencies=True, pitch="", inline=False, show_inflections=True):
    size = max(10, min(config.font_size_definitions - 1, config.font_size_header - 4))
    font_style = f"font-size:{size}px;" if inline else ""
    frequencies, inflections = OrderedDict(), OrderedDict()
    raw_frequencies = []
    for entry in entries:
        raw_frequencies.extend(entry.frequencies if show_frequencies else ())
        for frequency in entry.frequencies if show_frequencies else ():
            label = frequency.label or (f"{frequency.rank:g}" if frequency.rank is not None else "")
            if (frequency.rank is not None and frequency.mode == "rank-based"
                    and re.fullmatch(r"[\d,.]+", label)):
                label = f"#{label}"
            frequencies.setdefault((frequency.source, label), None)
        for step in entry.inflection:
            label = (re.sub(r"\([^)]*\)", "", str(step)) if entry.language == "ja" else str(step)).strip()
            if label and not label.startswith("stem-"):
                inflections.setdefault(label, entry.language)
    parts = [pitch] if pitch else []
    if frequencies:
        muted = surface_colors(config.color_background, config.color_foreground)["muted"]
        if combine_frequencies:
            from meikipop.dictionary.metadata import harmonic_rank
            rank = harmonic_rank(raw_frequencies)
            if rank is not None:
                detail = "; ".join(source + ": " + label for source, label in frequencies)
                parts.append(f'<a href="frequency:{quote(detail)}" style="{font_style}color:{muted}">#{max(1, round(rank)):,}</a>')
        else:
            by_source = OrderedDict()
            for source, label in frequencies:
                by_source.setdefault(source, []).append(label)
            parts.extend(f'<a href="frequency:{quote(source + ": " + ", ".join(labels))}" '
                         f'style="{font_style}color:{muted}">'
                         f'{escape(_source_name(source))} {escape("/".join(labels))}</a>'
                         for source, labels in by_source.items())
    if inflections and not inline and show_inflections:
        description = " · ".join(inflections)
        label = description
        if len(description) > 120 and set(inflections.values()) == {"tr"}:
            compact = []
            for step in inflections:
                variants = (step[1:-1] if step.startswith("(") and step.endswith(")") else step).split(" OR ")
                compact.append(variants[0] + (f" (+{len(variants) - 1})" if len(variants) > 1 else ""))
            label = " · ".join(compact)
            if len(label) > 120:
                label = label[:117].rsplit(" ", 1)[0].rstrip(" ·") + "…"
            muted = surface_colors(config.color_background, config.color_foreground)["muted"]
            parts.append(f'<a href="{TAG_PREFIX}{quote(description, safe="")}" '
                         f'style="color:{muted};text-decoration:none">{escape(label)}</a>')
        else:
            parts.append(escape(label))
    if inline:
        muted = surface_colors(config.color_background, config.color_foreground)["muted"]
        return (f'<span style="font-size:{size}px;font-weight:normal;color:{muted}">'
                + " ".join(parts) + '</span>') if parts else ""
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


def _dictionary_section_key(term, reading, source):
    return "section:" + repr((term, reading, source))


def render_result(result, expanded=(), preview=False, overlay_actions=False, show_source=True,
                  headword_furigana=False, combine_frequencies=True, source_text=None, details_expanded=(),
                  definition_furigana=False, collapsed=(), kanji_details=(),
                  preview_frequency=True, preview_pitch=True, preview_definitions=1,
                  pinned_frequency=True, pinned_pitch=True, grammar=None, separate_headwords=False,
                  headword_actions=0):
    """Share lexical headings while preserving the configured dictionary order."""
    preview_definitions = max(0, min(50, preview_definitions))
    maximum = preview_definitions if preview else 0
    grammar_tags = not preview if grammar is None else grammar
    show_inflections = grammar is not False
    muted = surface_colors(config.color_background, config.color_foreground)["muted"]
    clearance = 96 if overlay_actions is True else int(overlay_actions)
    if source_text is None:
        source_text = result.text if result.translation else ""
    heading_clearance = max(headword_actions, 0 if show_source and source_text else clearance)
    groups, sources = OrderedDict(), list(dict.fromkeys(entry.source for entry in result.entries))
    for entry in result.entries:
        if preview and (entry.source != sources[0] or groups and (entry.term, entry.reading) not in groups):
            continue
        groups.setdefault((entry.term, entry.reading), OrderedDict()).setdefault(entry.source, []).append(entry)
    parts = [f'<style>body {{color:{config.color_foreground};}} '
             f'a,h2 {{color:{config.color_highlight_word};text-decoration:none;}} '
             f'h2 {{font-size:{config.font_size_header}px;font-weight:normal;margin:0 {heading_clearance}px 0 0;}} '
             'p {margin:2px 0;} ol,ul {margin:2px 0 4px 8px;padding:0;} '
             'li {margin:1px 0;} hr {margin:6px 0;} '
             f'.metadata {{margin:0;color:{muted};}} .source {{margin:4px 0 1px;color:{muted};}}</style>']
    if show_source and source_text:
        parts.append(f'<p style="margin:0 {clearance}px 4px 0;font-size:{config.font_size_sentence}px">'
                     f'<a href="sentence:translate" title="Translate sentence" style="color:{muted}">'
                     f'{escape(source_text).replace(chr(10), "<br>")}</a></p>')
        if result.translation:
            parts.append("<hr>")
    if result.translation:
        parts.append(f'<p><a name="scroll-section-translation"></a>'
                     f'{escape(result.translation).replace(chr(10), "<br>")}</p>')
        if result.entries:
            parts.append("<hr>")
    anchored = set()
    for group_index, ((term, reading), dictionaries) in enumerate(groups.items()):
        if group_index and separate_headwords:
            parts.append("<hr>")
        first_source = next(source for source in sources if source in dictionaries)
        section = f'<a name="scroll-section-{group_index}-{sources.index(first_source)}"></a>'
        parts.append(section)
        display_term = term
        if (result.source == "ru" and reading and unicodedata.normalize("NFC", reading.replace("\u0301", ""))
                == unicodedata.normalize("NFC", term)):
            display_term, reading = reading, ""
        display_reading = f"[{reading}]" if result.source == "ja" else reading
        kanji = {entry.character for entry in result.kanji}
        display_term_html = "".join(
            f'<a href="headkanji:{group_index}:{quote(character, safe="")}" title="Kanji" '
            f'style="color:{config.color_highlight_word}">{escape(character)}</a>'
            if character in kanji and not preview else escape(character) for character in display_term)
        group_entries = tuple(entry for entries in dictionaries.values() for entry in entries)
        pitches = (tuple(pitch for entry in group_entries for pitch in entry.pitches)
                   if result.source == "ja" and (preview_pitch if preview else pinned_pitch) else ())
        pitch = ""
        if pitches:
            from meikipop.dictionary.pitch import render_pitches
            pitch = render_pitches(pitches, inline=True, separator=" ",
                                   font_size=max(10, min(config.font_size_definitions - 1, config.font_size_header - 4)))
        metadata = _metadata(group_entries, combine_frequencies, show_frequencies=preview_frequency if preview else pinned_frequency,
                             pitch=pitch, inline=True)
        metadata = " " + metadata if metadata else ""
        reading_html = (f' <span style="color:{config.color_highlight_reading};font-size:'
                        f'{max(12, config.font_size_header - 3)}px">{escape(display_reading)}</span>'
                        if reading and reading != term and not any(pitch.reading == reading for pitch in pitches) else "")
        if result.source == "ja" and headword_furigana and reading and reading != term:
            parts.append(f'<h2><a name="scroll-headword-{group_index}"></a>'
                         f'{ruby_html(escape(term), escape(reading), config.color_highlight_word, kanji=kanji if not preview else (), kanji_group=group_index)}{metadata}</h2>')
        else:
            parts.append(f'<h2><a name="scroll-headword-{group_index}"></a>{display_term_html}{reading_html}{metadata}</h2>')
        parts.append(_metadata(group_entries, show_frequencies=False, show_inflections=show_inflections))
        for source in sources:
            if source not in dictionaries:
                continue
            index, entries = sources.index(source), dictionaries[source]
            section_key = _dictionary_section_key(term, reading, source)
            full = not maximum or (source in expanded or section_key in expanded) and not preview
            more = bool(maximum and len(entries) > maximum)
            hidden = (source in collapsed or section_key in collapsed) and not preview
            generic_source = source in ("Turkish Bilingual", "Turkish Monolingual", "Turkish Etymology")
            normalized = [normalize_definitions(entry.definitions, source) for entry in entries]
            limit = 240 if result.source == "ja" and not full else None
            converter = _GlossConverter(expanded=full, limit=limit,
                                        preview=preview, preview_definitions=preview_definitions,
                                        generic_source=generic_source, term=term,
                                        details_expanded=details_expanded, detail_prefix=f"{group_index}:{index}",
                                        definition_furigana=definition_furigana,
                                        grammar=grammar_tags,
                                        definitions=tuple(definition for definitions in normalized for definition in definitions))
            definitions = []
            visible_entries = () if hidden else (normalized if full else normalized[:maximum])
            for entry_definitions in visible_entries:
                more = more or bool(maximum and len(entry_definitions) > maximum)
                definitions.extend(converter.glosses(entry_definitions if full else entry_definitions[:maximum]))
            if not full:
                more = more or len(definitions) > maximum
                definitions = definitions[:maximum]
            more = more or converter.clipped
            if source not in anchored:
                parts.append(f'<a name="dictionary-{index}"></a>')
                anchored.add(source)
            if not preview:
                label = converter.first_source or _source_name(source)
                section = (f'<a name="scroll-section-{group_index}-{index}"></a>'
                           if source != first_source else "")
                parts.append(f'<p class="source">{section}<a href="collapse:{group_index}:{index}" '
                             f'title="{"Expand" if hidden else "Collapse"}" style="color:{muted}">'
                             f'<small>{"▸" if hidden else "▾"}  {escape(label)}</small></a></p>')
            if len(definitions) > 1:
                opening = '<ol style="margin-left:20px">' if len(definitions) > 9 else "<ol>"
                parts.append(opening + "".join(f"<li>{gloss}</li>" for gloss in definitions) + "</ol>")
            else:
                parts.append("".join(f"<div>{gloss}</div>" for gloss in definitions))
            for label, supplement in converter.supplements:
                if label:
                    parts.append(f'<p class="source"><small>{label}</small></p>')
                parts.append(supplement)
            if more and not full and not hidden and not preview:
                parts.append(f'<p class="metadata"><a href="expand:{group_index}:{index}" style="text-decoration:underline">More</a></p>')
    if result.analyses and not result.entries:
        from meikipop.language.turkish_analyzer import grammar_labels
        lemmas = OrderedDict()
        for reading in result.analyses:
            lemmas.setdefault(reading.lemma, []).append(reading)
        for lemma, readings in lemmas.items():
            parts.append(f'<h2>{escape(lemma)}</h2>')
            if show_inflections:
                parts.append(f'<p class="metadata">{escape(" · ".join(grammar_labels(readings)))}</p>')
    if result.suggestions:
        parts.append('<p>Did you mean: ' + " · ".join(
            f'<a href="suggest:{index}">{escape(str(word))}</a>'
            for index, word in enumerate(result.suggestions)) + "</p>")
    unmatched_text = result.text.strip() if not (result.entries or result.translation or result.kanji or result.analyses) else ""
    if unmatched_text and not (show_source and source_text):
        parts.append(f'<p>{escape(unmatched_text).replace(chr(10), "<br>")}</p>')
    if result.message and not (unmatched_text and result.message == "No entry found."):
        parts.append(f"<p>{escape(result.message)}</p>")
    if result.kanji and not preview:
        from meikipop.gui.kanji_panel import render_kanji
        parts.append('<a name="kanji"></a>'
                     + render_kanji(result.kanji, compact_only=True))
    if not result.entries and not result.translation and not result.kanji and not result.message and result.text:
        if not unmatched_text:
            parts.append("<p>No entry found.</p>")
    return "".join(parts)


class LocalDictionaryBrowser(RubyBrowser):
    scrolled = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.document().setDocumentMargin(0)
        from meikipop.gui.section_scroll import SectionScroller
        self.section_scroll = SectionScroller(self)

    def setHtml(self, html):
        document = self.document()
        updates = self.updatesEnabled()
        # An ancestor may already suppress painting; do not disable this child explicitly.
        if updates:
            self.setUpdatesEnabled(False)
        try:
            with QSignalBlocker(document), QSignalBlocker(self.verticalScrollBar()):
                document.setLayoutEnabled(False)
                try:
                    self._set_html(html)
                finally:
                    document.setLayoutEnabled(True)
            self.section_scroll._document_changed()
        finally:
            if updates:
                self.setUpdatesEnabled(True)

    def _set_html(self, html):
        super().setHtml(html)
        def heading_format(fmt):
            fmt.clearProperty(QTextFormat.Property.FontSizeAdjustment)
            size = fmt.property(QTextFormat.Property.FontPixelSize)
            if size:
                font = fmt.font()
                font.setPixelSize(int(size))
                fmt.setFont(font)
            return fmt

        block = self.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel():
                # Qt retains h2's relative enlargement alongside our explicit size.
                cursor = QTextCursor(block)
                cursor.setBlockCharFormat(heading_format(block.charFormat()))
                runs = []
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    runs.append((fragment.position(), fragment.length(), fragment.charFormat()))
                    iterator += 1
                for start, length, fmt in runs:
                    cursor.setPosition(start)
                    cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
                    cursor.setCharFormat(heading_format(fmt))
            block = block.next()

        # Qt can leave trailing blocks unlaid after inline replacements and heading edits.
        self.document().markContentsDirty(0, self.document().characterCount())

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            point = QPointF(event.pos().x() + self.horizontalScrollBar().value(),
                            event.pos().y() + self.verticalScrollBar().value())
            position = self.document().documentLayout().hitTest(point, Qt.HitTestAccuracy.ExactHit)
            tooltip = ""
            if position >= 0:
                cursor = QTextCursor(self.document())
                cursor.setPosition(position)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                fmt = cursor.charFormat()
                if not fmt.isAnchor():
                    tooltip = fmt.toolTip()
            if tooltip:
                QToolTip.showText(event.globalPos(), "<p>" + escape(tooltip).replace("\n", "<br>") + "</p>", self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()

    def keyPressEvent(self, event):
        if not self.section_scroll.enabled and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            bar = self.verticalScrollBar()
            targets = {Qt.Key.Key_Up: bar.value() - bar.singleStep(),
                       Qt.Key.Key_Down: bar.value() + bar.singleStep(),
                       Qt.Key.Key_PageUp: bar.value() - bar.pageStep(),
                       Qt.Key.Key_PageDown: bar.value() + bar.pageStep(),
                       Qt.Key.Key_Home: 0, Qt.Key.Key_End: bar.maximum()}
            if event.key() in targets:
                bar.setValue(targets[event.key()])
                event.accept()
                return
        super().keyPressEvent(event)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if hasattr(self, "section_scroll"):
            self.section_scroll._update_header()
        self.scrolled.emit()

    def loadResource(self, resource_type, name):
        if resource_type == QTextDocument.ResourceType.ImageResource.value and getattr(self, "library_root", None):
            from meikipop.dictionary.media import resolve_image
            path = resolve_image(self.library_root, name.toString())
            if path:
                image = QImage(str(path))
                return image if not image.isNull() else None
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
        from meikipop.gui.profile_appearance import load_appearance
        load_appearance(self.settings, self.settings.value("profile", ""))
        self.revision = 0
        self._result = None
        self._display_revision = None
        self._pending_revision = None
        self._paint_revision = None
        self._document_revision = None
        self._render_identity = None
        self._fit_identity = None
        self._static_disclosure = False
        self._preserve_scroll = False
        self._needs_place = False
        self._context = ""
        self._peek = False
        self._history = []
        self._new_chain = True
        self._expanded = set()
        self._collapsed = set()
        self._details_expanded = set()
        self._kanji_details = set()
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
        self._anki_task = None
        self._anki_saved_revision = None
        self._anki_saved_note = None
        self._anki_saved_notes = {}
        self._anki_check_task = None
        self._anki_check_identity = None
        self._anki_existing_identity = None
        self._anki_existing_notes = {}
        self._headword_rows = {}
        self._headword_blocks = []
        self._anki_browse_task = None
        self._action_heading = None
        self._translation_view = False
        self._translation_return = None
        self._translation_text = ""
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
        self._reading_size_custom = False
        self._auto_fit_size = None
        self._preview_viewport_height = 0
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
        initial_profile = self.settings.value("profile", "")
        self.source.setCurrentIndex(max(0, self.source.findData(initial_profile)))
        self.update_translation_languages(self.settings.value(f"profiles/{initial_profile}/target", default_partner(initial_profile)))
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
        self.anki_button = self._action("anki", "Add to Anki")
        self.anki_button.clicked.connect(self.add_to_anki)
        action_layout.addWidget(self.anki_button)
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
        header_layout.addWidget(self.audio_actions, 0, Qt.AlignmentFlag.AlignRight)
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
        from meikipop.dictionary.library import default_library_path
        self.browser.library_root = directory or default_library_path()
        self.browser.section_scroll.set_enabled(self.settings.value(f"profiles/{initial_profile}/snap_scrolling", False, bool))
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setAccessibleName("Dictionary results")
        self.browser.document().setIndentWidth(10)
        self.link_timer = QTimer(self)
        self.link_timer.setSingleShot(True)
        self.link_timer.timeout.connect(self._activate_link)
        self._pending_link = None
        self.browser.anchorClicked.connect(self._queue_link)
        self.browser.word_selected.connect(self.lookup_word)
        from meikipop.gui.translation_view import TranslationView
        self.translation_browser = TranslationView()
        self.translation_browser.language_requested.connect(self._translation_language_menu)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.browser)
        self.content_stack.addWidget(self.translation_browser)
        self.kanji_splitter = QSplitter(Qt.Orientation.Vertical)
        self.kanji_splitter.setChildrenCollapsible(False)
        self.kanji_splitter.setHandleWidth(2)
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.content_stack.setMinimumHeight(self.browser.fontMetrics().height())
        self.kanji_splitter.addWidget(self.content_stack)
        layout.addWidget(self.kanji_splitter, 1)
        self.kanji_panel = QWidget()
        kanji_layout = QVBoxLayout(self.kanji_panel)
        kanji_layout.setContentsMargins(0, 0, 0, 0)
        kanji_layout.setSpacing(2)
        self.kanji_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        kanji_header = QHBoxLayout()
        kanji_header.addWidget(QLabel("Kanji"))
        kanji_header.addStretch()
        self.kanji_more = QToolButton()
        self.kanji_more.setText("More")
        self.kanji_more.setToolTip("Dictionary reference fields")
        self.kanji_more.setCheckable(True)
        self.kanji_more.toggled.connect(self._toggle_kanji_more)
        kanji_header.addWidget(self.kanji_more)
        self.kanji_close = self._action("close", "Close kanji")
        self.kanji_close.clicked.connect(self._close_kanji)
        kanji_header.addWidget(self.kanji_close)
        kanji_layout.addLayout(kanji_header)
        self.kanji_browser = RubyBrowser()
        self.kanji_browser.setAccessibleName("Kanji details")
        self.kanji_browser.setOpenLinks(False)
        self.kanji_browser.setOpenExternalLinks(False)
        self.kanji_browser.anchorClicked.connect(self._queue_link)
        kanji_layout.addWidget(self.kanji_browser, 1)
        self.kanji_splitter.addWidget(self.kanji_panel)
        self.kanji_splitter.setStretchFactor(0, 1)
        self.kanji_splitter.setStretchFactor(1, 1)
        self.kanji_splitter.handle(1).setToolTip("Resize kanji pane")
        self.kanji_splitter.splitterMoved.connect(self._save_kanji_split)
        self.kanji_panel.hide()
        self._kanji_html = ""
        self._kanji_extra_html = ""
        self._kanji_more_start = None
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        toolbar.addWidget(self.translate)
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(close)
        layout.addWidget(self.actions_row)
        self.actions_row.hide()
        self._popup_actions = dict(anki=self.anki_button, audio_sentence=self.sentence_audio_button,
                                   audio=self.audio_button, translate=self.translate, copy=self.copy_button,
                                   close=self.dismiss_button, back=self.back)
        self.browser.verticalScrollBar().valueChanged.connect(self._position_actions)
        self.browser.document().documentLayout().documentSizeChanged.connect(self._position_actions)
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
        return self.source.currentData() or ""

    def apply_style(self):
        colors = surface_colors(config.color_background, config.color_foreground)
        self.frame.setStyleSheet(frame_stylesheet(config.color_background, config.color_foreground,
                                                  config.background_opacity, config.font_family) + f'''
            QLineEdit,QComboBox,QTextBrowser {{background:transparent;color:{config.color_foreground};
                border:0;padding:3px;selection-background-color:{config.color_highlight_word};
                selection-color:{config.color_background};}}
            QLineEdit {{border-bottom:1px solid {colors['border']};}}
            QTextBrowser {{border-radius:0;padding:0;}}
            QStackedWidget {{background:transparent;border:0;border-radius:0;}}
            QSplitter {{background:transparent;border:0;border-radius:0;}}
            QSplitter::handle {{background:{colors['border']};}}
            QSplitter::handle:hover {{background:{colors['muted']};}}
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
        from meikipop.gui.typography import document_font
        font = document_font(config.font_family, config.font_size_definitions, self.preferred_foreign)
        self.browser.setFont(font)
        self.kanji_browser.setFont(font)
        self.translation_browser.setFont(document_font(config.font_family, config.font_size_sentence, self.preferred_foreign))
        self.search.setFont(font)
        for button in self.findChildren(QToolButton):
            name = button.property("action_name")
            if name:
                button.setIcon(action_icon(name, config.color_foreground))

    def reload_appearance(self, render=True):
        from meikipop.gui.profile_appearance import load_appearance
        load_appearance(self.settings, self.preferred_foreign)
        self.browser.section_scroll.set_enabled(self.settings.value(f"profiles/{self.preferred_foreign}/snap_scrolling", False, bool))
        self.apply_style()
        if render:
            before = tuple(button.isHidden() for button in self._popup_actions.values())
            self._place_actions()
            changed = before != tuple(button.isHidden() for button in self._popup_actions.values())
            self._render(static=changed, preserve_scroll=changed)

    def compact_preview(self):
        return self.settings.value(f"profiles/{self.preferred_foreign}/compact_preview", True, type=bool)

    def update_languages(self, languages=None):
        if languages is not None:
            self._imported_languages = tuple(languages)
        languages = getattr(self, "_imported_languages", ())
        codes = visible_profiles(self.settings, languages)
        if "en" in codes and not self.settings.contains("profiles/en/target"):
            self.settings.setValue("profiles/en/target", "ja")
        current_source = self.source.currentData() or self.settings.value("profile", "")
        with QSignalBlocker(self.source):
            self.source.clear()
            for code in codes:
                self.source.addItem(language_name(code), code)
            self.source.setCurrentIndex(max(0, self.source.findData(current_source)))
        self.update_translation_languages()

    def update_translation_languages(self, target=None):
        from meikipop.dictionary.translation import load_profile_settings, translation_language
        from meikipop.language.support import translation_languages
        profile = self.source.currentData() or self.settings.value("profile", "")
        try:
            provider = load_profile_settings(self.settings, profile).provider
        except ValueError:
            provider = "server"
        target = target or self.foreign.currentData() or self.settings.value(f"profiles/{profile}/target", default_partner(profile))
        if provider == "server":
            target = translation_language(target)
        codes = sorted(translation_languages(provider, getattr(self, "_imported_languages", ()),
                                             (*configured_profiles(self.settings), profile, target)) - {"", None})
        tooltip = "Language support depends on your server model" if provider == "custom" else ""
        with QSignalBlocker(self.foreign):
            self.foreign.clear()
            for code in dict.fromkeys([*codes, target]):
                self.foreign.addItem(language_name(code), code)
                item = self.foreign.model().item(self.foreign.count() - 1)
                item.setEnabled(code in codes)
                item.setToolTip(tooltip if code in codes else "The selected model does not support this language")
            self.foreign.setCurrentIndex(self.foreign.findData(target))
        self.foreign.setToolTip(tooltip or ("Translate in either direction within this pair" if target in codes
                                           else "The selected model does not support this language"))

    def translation_available(self):
        from meikipop.dictionary.translation import load_profile_settings
        from meikipop.language.support import translation_supported
        try:
            provider = load_profile_settings(self.settings, self.preferred_foreign).provider
            source = self.settings.value(f"profiles/{self.preferred_foreign}/translation_source", "auto")
            target = self.settings.value(f"profiles/{self.preferred_foreign}/translation_target", "auto")
            source = self.preferred_foreign if source == "auto" else source
            target = self.foreign.currentData() if target == "auto" else target
            return translation_supported(source, provider) and translation_supported(target, provider)
        except ValueError:
            return False

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
        if not mode:
            return
        if self.sender() is self.source:
            self.update_translation_languages(self.settings.value(f"profiles/{mode}/target", default_partner(mode)))
            self.settings.setValue("profile", mode)
        self._update_target_visibility()
        if self.foreign.currentData() == self.preferred_foreign:
            with QSignalBlocker(self.foreign):
                self.foreign.setCurrentIndex(self.foreign.findData(default_partner(mode)))
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
        for _, _, audio in self._headword_rows.values():
            audio.setEnabled(False)
        self.sentence_audio_button.setEnabled(False)
        self._clear_context()

    def _translate_clicked(self):
        if self._translation_busy or self._pending_revision is not None and not self.busy_delay.isActive():
            self._invalidate()
            self._restore_actions()
        else:
            self.submit(translate=True, context=bool(self._context))

    def _show_translation(self, text, source, target):
        if not self._translation_view:
            self._translation_return = {}
            for name in (
                "_result", "_result_context", "_result_screenshot", "_result_input",
                "_result_profile", "_result_target", "_expanded", "_details_expanded",
                "_collapsed", "_kanji_details"):
                if hasattr(self, name):
                    value = getattr(self, name)
                    self._translation_return[name] = value.copy() if isinstance(value, set) else value
        self._translation_view = True
        self._translation_text = text
        self._translation_content = SearchResult(text, source, target)
        self.fit_timer.stop()
        self.content_stack.setCurrentWidget(self.translation_browser)
        self._set_kanji_visible(False)
        self.back.setEnabled(True)
        self._update_trail()
        self._place_actions()
        self._render_translation()

    def _render_translation(self):
        result = self._translation_content
        self.translation_browser.set_content(result.text, result.translation,
                                             language_name(result.source), language_name(result.target))

    def _leave_translation(self):
        if not self._translation_view:
            return
        self._translation_view = False
        self._partial_translation = False
        for name, value in (self._translation_return or {}).items():
            setattr(self, name, value)
        self._translation_return = None
        self.content_stack.setCurrentWidget(self.browser)
        self._render_kanji_panel()
        self.back.setEnabled(bool(self._history))
        self._update_trail()
        self._place_actions()

    def _translation_language_menu(self, role):
        menu = QMenu(self.translation_browser)
        current = getattr(self._translation_content, role)
        other = self._translation_content.target if role == "source" else self._translation_content.source
        for index in range(self.foreign.count()):
            code = self.foreign.itemData(index)
            action = menu.addAction(language_name(code))
            action.setCheckable(True)
            action.setChecked(code == current)
            action.setEnabled(self.foreign.model().item(index).isEnabled() and code != other)
            action.triggered.connect(lambda _, code=code: self._set_translation_language(role, code))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(QCursor.pos())

    def _set_translation_language(self, role, code):
        if not self._translation_view or role not in ("source", "target"):
            return
        self.settings.setValue(f"profiles/{self.preferred_foreign}/translation_{role}", code)
        self.set_context(self._translation_text)
        self.submit(translate=True, context=True)

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
        available = self.translation_available()
        self.translate.setEnabled(bool(busy or available and (self.search.text().strip() or self._context)))
        self.translate.setIcon(action_icon("translate", config.color_foreground))
        name = "Cancel translation" if busy else "Translate sentence" if self._peek and self._context else "Translate"
        model = self._result.translation_model if not busy and self._result is not None and self._display_revision == self.revision else ""
        self.translate.setToolTip(name + ("\n" + model if model else "") if busy or available
                                  else "The selected model does not support this language pair")
        self.translate.setAccessibleName(name)

    def _edited(self):
        self._invalidate()
        self._leave_translation()
        self._display_revision = None
        self._clear_actions()
        text = self.search.text().strip()
        self.translate.setEnabled(bool(text) and self.translation_available())
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
            self._close_kanji()

    def submit(self, translate=None, *, context=False, remember=False, selection=False):
        if not translate:
            self._leave_translation()
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
        exact_only = self._sentence_lookup and is_sentence(text)
        if translate is None:
            translate = False
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
            display_source = source if source != "auto" else self._result.source if self._result else self.preferred_foreign
            display_target = target or (self.preferred_foreign if display_source == self.foreign.currentData()
                                        else self.foreign.currentData())
            self._show_translation(text, display_source, display_target)
        from meikipop.dictionary.translation import load_profile_settings
        try:
            translation_settings = load_profile_settings(self.settings, self.preferred_foreign) if translate else None
        except (ValueError, TypeError) as error:
            self._failed(self.revision, str(error))
            return
        from meikipop.language.morphology import model_available
        worker.request(self.revision, text, source,
                       self.preferred_foreign, translate=bool(translate),
                       target=target,
                       pair=(self.preferred_foreign, self.foreign.currentData()),
                       translation_settings=translation_settings,
                       context=lookup_context if not translate else None,
                       morphology=not translate and not exact_only and model_available(self.preferred_foreign),
                       exact_only=exact_only)

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
        if self._last_request_translate and self._translation_view:
            self._translation_content = result
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
        if not self._last_request_translate:
            self._autoplay_lookup()
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
        if self._translation_view:
            self._translation_content = result
        browser = self.translation_browser if self._translation_view else self.browser
        if browser.selecting:
            self._translation_chunk = result
            self.stream_timer.start()
            return
        bar = browser.verticalScrollBar()
        at_end = (bar.maximum() > 0 and bar.value() >= bar.maximum() - 2
                  and not browser.textCursor().hasSelection())
        base = self._translation_base
        if base is not None:
            result = replace(result, entries=base.entries, suggestions=base.suggestions, kanji=base.kanji)
        self._result = result
        self._partial_translation = True
        self._render(static=True)
        if at_end:
            bar.setValue(bar.maximum())

    def collapsed_dictionaries(self):
        return set(self.settings.value(f"profiles/{self.preferred_foreign}/collapsed_dictionaries", [], type=list))

    def set_dictionary_display(self, source, mode):
        if self._result is not None:
            sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
            if source in sources:
                keys = self._section_keys(sources.index(source))
                self._collapsed.difference_update(keys)
                self._expanded.difference_update(keys)
        self._collapsed.discard(source)
        self._expanded.discard(source)
        if mode == "collapsed":
            self._collapsed.add(source)
        elif mode == "expanded":
            self._expanded.add(source)
        self._render()

    def _section_keys(self, source_index):
        sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
        return {_dictionary_section_key(entry.term, entry.reading, entry.source)
                for entry in self._result.entries if entry.source == sources[source_index]}

    def _display(self, result, remember=True, expanded=None, details_expanded=None, collapsed=None, kanji_details=None):
        remember = remember and not self._translation_view
        same = self._result is not None and (self._result.text, self._result.source, self._result.target) == (
            result.text, result.source, result.target)
        previous_context = getattr(self, "_result_context", "")
        if remember and not self._new_chain and self._result is not None and not same:
            self._history.append((self._result, getattr(self, "_result_context", ""),
                                  self._result_profile, self._result_target, tuple(self._expanded),
                                  self.browser.verticalScrollBar().value(), tuple(self._details_expanded),
                                  self._result_input, self._result_screenshot, tuple(self._collapsed),
                                  tuple(self._kanji_details)))
            self._history = self._history[-30:]
        if details_expanded is not None:
            self._details_expanded = set(details_expanded)
        elif self._new_chain or self._result is None or result.entries != self._result.entries:
            self._details_expanded.clear()
        if collapsed is not None:
            self._collapsed = set(collapsed)
        elif self._new_chain or not same:
            self._collapsed = self.collapsed_dictionaries()
        if kanji_details is not None:
            self._kanji_details = set(tuple(kanji_details)[:1])
        elif self._new_chain or not same:
            self._kanji_details.clear()
        if expanded is not None:
            self._expanded = set(expanded)
        elif self._new_chain or not same:
            self._expanded = set(self.settings.value(
                f"profiles/{self.preferred_foreign}/expanded_dictionaries", [], type=list))
        self._new_chain = False
        self._result = result
        self._display_revision = self.revision
        self._result_profile = self.preferred_foreign
        self._result_target = self.foreign.currentData()
        self._result_context = previous_context if same else ""
        if not same:
            self._result_screenshot = None
        self._result_input = self.search.text().strip()
        self._render(static=same)
        self.back.setEnabled(bool(self._history) or self._translation_view)
        self._update_trail()
        self.audio_button.setEnabled(bool(result.entries))
        self.update_anki()
        self._place_actions()
        self.sentence_audio_button.setEnabled(bool(result.text))

    def _render(self, static=False, *, preserve_scroll=False):
        self._sync_headword_actions()
        self._render_kanji_panel()
        if self._translation_view:
            self._render_translation()
            return
        if self._result is not None:
            self._static_disclosure = self._static_disclosure or static
            self._preserve_scroll = self._preserve_scroll or preserve_scroll
            if self.browser.selecting:
                self.render_timer.start(50)
                return
            static, self._static_disclosure = self._static_disclosure, False
            preserve_scroll, self._preserve_scroll = self._preserve_scroll, False
            compact = self.compact_preview()
            prefix = f"profiles/{self.preferred_foreign}/"
            preview_options = dict(
                preview_frequency=self.settings.value(prefix + "preview_frequency", True, bool),
                preview_pitch=self.settings.value(prefix + "preview_pitch", True, bool),
                preview_definitions=self.settings.value(prefix + "preview_definitions", 1, int),
                pinned_frequency=self.settings.value(prefix + "pinned_frequency", True, bool),
                pinned_pitch=self.settings.value(prefix + "pinned_pitch", True, bool),
                grammar=self.settings.value(prefix + "preview_grammar", False, bool)
                if self._peek and not self.is_pinned else self.settings.value(prefix + "pinned_grammar", True, bool))
            separate_headwords = (not self.browser.section_scroll.enabled and
                                  len({(entry.term, entry.reading) for entry in self._result.entries}) > 1)
            self.browser.section_scroll.set_preview(self._peek and not self.is_pinned)
            expanded = self._expanded
            if self._peek and not self.is_pinned and not compact:
                expanded = {entry.source for entry in self._result.entries}
            self._place_actions()
            show_source, source_text = self._peek, None
            if self._peek and self.is_pinned:
                show_source = self.settings.value(f"profiles/{self.preferred_foreign}/pinned_sentence", False, bool)
                source_text = self._result_context or (self._result.text if self._result.translation else "")
                if show_source and source_text:
                    width = (self.browser.viewport().width() - 2 * self.browser.document().documentMargin()
                             - self._action_clearance())
                    from meikipop.gui.typography import document_font
                    sentence_font = document_font(config.font_family, config.font_size_sentence, self.preferred_foreign)
                    source_text = _compact_context(source_text, sentence_font, width)
            from meikipop.gui.profile_appearance import DEFAULTS
            identity = (repr(self._result), self.preferred_foreign, tuple(sorted(expanded)),
                        tuple(sorted(self._details_expanded)),
                        self._peek, self.is_pinned, compact, tuple(preview_options.values()),
                        tuple(getattr(config, key) for key in DEFAULTS), self.devicePixelRatioF(),
                        self.audio_actions.sizeHint().width(), show_source, source_text if show_source else None,
                        self.settings.value("profiles/ja/headword_furigana", False, bool),
                        self.settings.value("profiles/ja/definition_furigana", True, bool),
                        self.settings.value(f"profiles/{self.preferred_foreign}/combine_frequencies", True, bool),
                        tuple(sorted(self._collapsed)), separate_headwords, self._headword_clearance())
            if identity == self._render_identity:
                mark("render_reused", self.revision)
                return
            from meikipop.gui.section_scroll import ReadingPosition
            result_key = (self._result.text, self._result.source, self._result.target)
            position = (ReadingPosition(self.browser)
                        if getattr(self, "_rendered_result_key", None) == result_key else None)
            mark("html_begin", self.revision)
            dictionary_result = replace(self._result, translation="") if self._result.entries else self._result
            self.browser.setHtml(render_result(dictionary_result, expanded, **preview_options,
                                               overlay_actions=self._action_clearance(),
                                               headword_actions=self._headword_clearance(),
                                               preview=self._peek and not self.is_pinned and compact,
                                               show_source=show_source, source_text=source_text,
                                               details_expanded=self._details_expanded,
                                               headword_furigana=self.settings.value("profiles/ja/headword_furigana", False, bool),
                                               definition_furigana=self.settings.value("profiles/ja/definition_furigana", True, bool),
                                               collapsed=self._collapsed,
                                               separate_headwords=separate_headwords,
                                               combine_frequencies=self.settings.value(f"profiles/{self.preferred_foreign}/combine_frequencies", True, bool)))
            self._action_heading = None
            self._headword_blocks = []
            block = self.browser.document().begin()
            while block.isValid():
                if block.blockFormat().headingLevel() == 2:
                    self._headword_blocks.append(block)
                    if self._headword_rows:
                        fmt = block.blockFormat()
                        fmt.setLineHeight(max(row.sizeHint().height() for row, _, _ in self._headword_rows.values()),
                                          QTextBlockFormat.LineHeightTypes.MinimumHeight.value)
                        QTextCursor(block).setBlockFormat(fmt)
                if self._action_heading is None and (show_source and source_text or block.blockFormat().headingLevel() == 2):
                    self._action_heading = block
                    if self._action_clearance():
                        fmt = block.blockFormat()
                        fmt.setLineHeight(self.audio_actions.sizeHint().height(),
                                          QTextBlockFormat.LineHeightTypes.MinimumHeight.value)
                        QTextCursor(block).setBlockFormat(fmt)
                block = block.next()
            self._render_identity = identity
            self._rendered_result_key = result_key
            self._document_revision = self.revision
            mark("document_ready", self.revision)
            # Restore snap-page padding before restoring a position near the end.
            self.browser.section_scroll._refresh_header()
            if position is not None:
                position.restore(self.browser, preserve_scroll=preserve_scroll)
            self._position_actions()
            self.browser.setToolTip("")
            if static:
                self.fit_timer.stop()
                self._fit_identity = (self._render_identity, self.browser.viewport().width())
            else:
                self.fit_timer.start(0)

    def _fit_preview(self):
        if self._translation_view or not self.kanji_panel.isHidden():
            return
        preview = self._peek and not self.is_pinned and self.compact_preview()
        reading = (not self._peek or self.is_pinned) and not self._reading_size_custom and self._normal_size == QSize(480, 340)
        if self._shutting_down or not (preview or reading):
            return
        identity = (self._render_identity, self.browser.viewport().width())
        if identity == self._fit_identity and not self._needs_place:
            return
        self._fit_identity = identity
        mark("fit", self.revision)
        self.setMinimumHeight(72 if preview else 190)
        self.layout().activate()
        document = self.browser.document()
        document.setTextWidth(self.browser.viewport().width())
        chrome = self.height() - self.browser.viewport().height()
        natural_height = (document.size().height() - document.rootFrame().frameFormat().bottomMargin()
                          + document.documentMargin())
        scroller = self.browser.section_scroll
        if reading and scroller.enabled and len(scroller.boundaries()) > 1:
            natural_height = min(natural_height, scroller.boundaries()[1][0])
        desired = math.ceil(natural_height) + chrome + 2
        maximum = max(190, self.settings.value("preview_max_height", 340, type=int)) if preview else self._normal_size.height()
        if reading and self._peek:
            maximum = max(maximum, self._preview_viewport_height + chrome + 2)
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
        minimum = self._preview_viewport_height + chrome if reading and self._peek else 0
        height = min(maximum, max(self.minimumSizeHint().height(), desired, minimum))
        if self.height() != height:
            mark("geometry", self.revision)
            if self.isVisible() and not self._needs_place:
                self._resize_expanded(QSize(self.width(), height))
            else:
                self.resize(self.width(), height)
        if self.isVisible() and self._needs_place:
            self._place()
            self._needs_place = False
        self._auto_fit_size = self.size()

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

    def _queue_link(self, url):
        if self._pin_anchor_click:
            self._pin_anchor_click = False
            return
        self._pending_link = (QUrl(url), self.revision, self._render_identity)
        # QTextBrowser must finish mouse release before its document is replaced.
        self.link_timer.start(0)

    def _activate_link(self):
        pending, self._pending_link = self._pending_link, None
        if pending is not None and not self._shutting_down:
            url, revision, identity = pending
            if revision == self.revision and identity == self._render_identity:
                self._link(url)

    def _close_kanji(self):
        self._kanji_details.clear()
        self._render_kanji_panel()

    def _save_kanji_split(self, *_):
        sizes = self.kanji_splitter.sizes()
        if not self.kanji_panel.isHidden() and sum(sizes):
            self.settings.setValue("profiles/ja/kanji_height_ratio", sizes[1] / sum(sizes))

    def _set_kanji_visible(self, visible):
        if visible == (not self.kanji_panel.isHidden()):
            return
        from meikipop.gui.section_scroll import ReadingPosition
        position = ReadingPosition(self.browser)
        self.fit_timer.stop()
        self.kanji_panel.setVisible(visible)
        self.layout().activate()
        if visible:
            document = self.kanji_browser.document()
            document.setTextWidth(self.kanji_browser.viewport().width())
            layout = self.kanji_panel.layout()
            margins = layout.contentsMargins()
            browser_margins = self.kanji_browser.contentsMargins()
            pane_chrome = (layout.itemAt(0).sizeHint().height() + layout.spacing()
                           + margins.top() + margins.bottom()
                           + browser_margins.top() + browser_margins.bottom())
            available = self.kanji_splitter.contentsRect().height() - self.kanji_splitter.handleWidth()
            ratio = self.settings.value("profiles/ja/kanji_height_ratio", 0., float)
            pane_height = round(available * ratio) if 0 < ratio < 1 else (
                self._kanji_glyph_height() + pane_chrome)
            self.kanji_splitter.setSizes([max(self.content_stack.minimumHeight(), available - pane_height),
                                         min(pane_height, available - self.content_stack.minimumHeight())])
        position.restore(self.browser, preserve_scroll=True)

    def _kanji_glyph_height(self):
        document = self.kanji_browser.document()
        block = document.begin()
        while block.isValid():
            names = set(block.charFormat().anchorNames())
            fragment = block.begin()
            while not fragment.atEnd():
                names.update(fragment.fragment().charFormat().anchorNames())
                fragment += 1
            if any(name.startswith("kanji-detail-") for name in names):
                return math.ceil(document.documentLayout().blockBoundingRect(block).bottom()
                                 + document.documentMargin())
            block = block.next()
        return math.ceil(document.size().height())

    def _select_kanji(self, character):
        self._kanji_details = set() if character in self._kanji_details else {character}
        self.fit_timer.stop()
        self._render_kanji_panel()

    def _toggle_kanji_more(self, expanded):
        from meikipop.gui.section_scroll import ReadingPosition
        position = ReadingPosition(self.kanji_browser)
        cursor = QTextCursor(self.kanji_browser.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        if expanded:
            self._kanji_more_start = cursor.position()
            cursor.insertBlock()
            cursor.insertHtml(self._kanji_extra_html)
        elif self._kanji_more_start is not None:
            cursor.setPosition(self._kanji_more_start, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            self._kanji_more_start = None
        cursor.endEditBlock()
        self.kanji_more.setText("Less" if expanded else "More")
        position.restore(self.kanji_browser, preserve_scroll=True)

    def _render_kanji_panel(self):
        from meikipop.gui.kanji_panel import render_kanji_details, render_kanji_extra
        entries = tuple(entry for entry in self._result.kanji if entry.character in self._kanji_details) if self._result else ()
        visible = bool(entries) and not self._translation_view and not (self._peek and not self.is_pinned)
        html = render_kanji_details(entries) if visible else ""
        extra = render_kanji_extra(entries) if visible else ""
        if (html, extra) != (self._kanji_html, self._kanji_extra_html):
            with QSignalBlocker(self.kanji_more):
                self.kanji_more.setChecked(False)
            self.kanji_more.setText("More")
            self._kanji_more_start = None
            self.kanji_browser.setHtml(html)
            self._kanji_html = html
            self._kanji_extra_html = extra
        self.kanji_more.setVisible(bool(extra))
        self._set_kanji_visible(visible)

    def _link(self, url):
        if self._result is None:
            return
        if self._pin_anchor_click:
            self._pin_anchor_click = False
            return  # The first click already expanded the complete peek.
        if url.scheme() == "sentence" and url.path() == "translate":
            if not self._peek or self.is_pinned:
                self.submit(translate=True, context=bool(self._context))
            return
        if url.scheme() == "headkanji":
            group, separator, character = url.path().partition(":")
            if not separator:
                group, character = "0", group
            groups = list(dict.fromkeys((entry.term, entry.reading) for entry in self._result.entries))
            if (not group.isdigit() or int(group) >= len(groups) or character not in groups[int(group)][0]
                    or character not in {entry.character for entry in self._result.kanji}):
                return
            self._select_kanji(character)
            return
        if url.scheme() == "kanji" and url.path() in {entry.character for entry in self._result.kanji}:
            self._select_kanji(url.path())
            return
        if url.scheme() == "details" and re.fullmatch(r"\d+:\d+:\d+", url.path()):
            key = url.path()
            self._details_expanded.symmetric_difference_update((key,))
            self._render(static=True, preserve_scroll=True)
            return
        if url.scheme() in ("expand", "collapse") and re.fullmatch(r"\d+:\d+", url.path()):
            group_index, source_index = map(int, url.path().split(":"))
            sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
            if not 0 <= source_index < len(sources):
                return
            groups = list(dict.fromkeys((entry.term, entry.reading) for entry in self._result.entries))
            if not 0 <= group_index < len(groups):
                return
            key = _dictionary_section_key(*groups[group_index], sources[source_index])
            keys = self._section_keys(source_index)
            if key not in keys:
                return
            source = sources[source_index]
            for state in (self._expanded, self._collapsed):
                if source in state:
                    state.remove(source)
                    state.update(keys)
            if url.scheme() == "collapse":
                self._collapsed.symmetric_difference_update((key,))
            elif key in self._collapsed:
                self._collapsed.remove(key)
                self._expanded.add(key)
            elif key in self._expanded:
                self._expanded.remove(key)
                if source in self.collapsed_dictionaries():
                    self._collapsed.add(key)
            else:
                self._expanded.add(key)
            self._render(static=True, preserve_scroll=True)
            return
        try:
            index = int(url.path())
        except ValueError:
            return
        if url.scheme() in ("expand", "collapse"):
            sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
            if not 0 <= index < len(sources):
                return
            source = sources[index]
            if url.scheme() == "collapse":
                self._collapsed.symmetric_difference_update((source,))
            elif source in self._collapsed:
                self._collapsed.remove(source)
                self._expanded.add(source)
            elif source in self._expanded:
                self._expanded.remove(source)
                if source in self.collapsed_dictionaries():
                    self._collapsed.add(source)
            else:
                self._expanded.add(source)
            self._render(static=True, preserve_scroll=True)
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
        if self._translation_view:
            self._invalidate()
            self._leave_translation()
            self._restore_actions()
            self.update_anki()
            return
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
                      details_expanded=previous[6] if len(previous) > 6 else (),
                      collapsed=previous[9] if len(previous) > 9 else None,
                      kanji_details=previous[10] if len(previous) > 10 else ())
        self.set_context(context)
        self._result_screenshot = previous[8] if len(previous) > 8 else None
        self.browser.verticalScrollBar().setValue(scroll)
        self.translate.setEnabled(bool(result.text) and self.translation_available())
        self.status.setText(f"{language_name(result.source)} → {language_name(result.target)}")

    def _update_trail(self):
        if self._translation_view or not self._history:
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
        if peek and not self._peek and (self._reading_size_custom or self.size() != self._auto_fit_size):
            self._normal_size = self.size()
        elif not peek and self._peek and not self.is_pinned:
            self.setMinimumHeight(190)
            self._resize_expanded()
        self._peek = bool(peek)
        self.setSizeGripEnabled(self.is_pinned or not self._peek)
        for grip in self.findChildren(QWidget):
            if grip.inherits("QSizeGrip"):
                grip.installEventFilter(self)
        self._place_actions()
        self.search.setVisible(not self._peek)

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
        self._sync_headword_actions()
        self.mode_row.hide()
        for name, button in self._popup_actions.items():
            visible = self.settings.value(f"profiles/{self.preferred_foreign}/buttons/{name}", True, bool)
            if name == "anki":
                visible = visible and self.settings.value(f"profiles/{self.preferred_foreign}/anki/enabled", False, bool)
            if name == "back":
                visible = visible and (bool(self._history) or self._translation_view)
            if name in ("anki", "audio") and self._headword_rows:
                visible = False
            button.setVisible(visible)
        inline = self._inline_actions()
        container = self.browser.viewport() if inline else self.header
        if self.audio_actions.parentWidget() is not container:
            self.audio_actions.setParent(container)
            if not inline:
                self.header.layout().addWidget(self.audio_actions, 0, Qt.AlignmentFlag.AlignRight)
        self.search.setVisible(not self._peek and not self._translation_view)
        self.header.setVisible(not self._translation_view and (not self._peek or self.is_pinned and not inline))
        self.audio_actions.setVisible(not self._translation_view and (not self._peek or self.is_pinned) and
                                      any(not button.isHidden() for button in
                                          (self.anki_button, self.sentence_audio_button, self.audio_button)))
        self.actions_row.setVisible((not self._peek or self.is_pinned) and
                                    (bool(self.title.text()) or any(not button.isHidden() for button in
                                     (self.back, self.translate, self.copy_button, self.dismiss_button))))
        self._position_actions()

    def _inline_actions(self):
        return bool(not self._translation_view and self._peek and self.is_pinned and self._result and self._result.entries)

    def _action_clearance(self):
        if not self._inline_actions():
            return 0
        buttons = [button for button in (self.anki_button, self.sentence_audio_button, self.audio_button)
                   if not button.isHidden()]
        return sum(button.width() for button in buttons) + len(buttons) * self.audio_actions.layout().spacing()

    def _position_actions(self, *_):
        self._position_headword_actions()
        if not self._inline_actions() or self.audio_actions.parentWidget() is not self.browser.viewport():
            return
        block = self._action_heading
        if block is None or not block.isValid() or not self._action_clearance():
            self.audio_actions.hide()
            return
        viewport = self.browser.viewport()
        document = self.browser.document()
        offset = -self.browser.verticalScrollBar().value()
        sticky = self.browser.section_scroll.header
        if not sticky.isHidden():
            document = sticky.document()
            block = document.begin()
            offset = sticky.y()
        rect = document.documentLayout().blockBoundingRect(block)
        line = block.layout().lineAt(0) if block.layout().lineCount() else None
        # Qt includes minimum-line-height leading in y(), not in height().
        height = max(line.y() + line.height() if line is not None else rect.height(),
                     self.audio_actions.sizeHint().height())
        top = rect.top() + offset
        size = self.audio_actions.sizeHint()
        margin = self.browser.document().documentMargin()
        self.audio_actions.setGeometry(round(viewport.width() - margin - size.width()),
                                       round(top + (height - size.height()) / 2), size.width(), size.height())
        self.audio_actions.setVisible(top + height > 0 and top < viewport.height())
        self.audio_actions.raise_()

    def _headword_groups(self):
        groups = OrderedDict()
        for entry in self._result.entries if self._result else ():
            groups.setdefault((entry.term, entry.reading), []).append(entry)
        return groups

    def _sync_headword_actions(self):
        groups = self._headword_groups()
        if self._translation_view or self._peek and not self.is_pinned or len(groups) < 2:
            groups = {}
        for key in list(self._headword_rows):
            if key not in groups:
                row, _, _ = self._headword_rows.pop(key)
                row.hide()
                row.deleteLater()
        for key in groups:
            if key not in self._headword_rows:
                row = QWidget(self.browser.viewport())
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(self.audio_actions.layout().spacing())
                anki = self._action("anki", "Add to Anki")
                audio = self._action("audio", "Play pronunciation")
                anki.clicked.connect(lambda checked=False, key=key: self.add_to_anki(headword=key))
                audio.clicked.connect(lambda checked=False, key=key: self.play_audio(headword=key))
                audio.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                audio.customContextMenuRequested.connect(
                    lambda point, key=key, button=audio: self.audio_source_menu(point, headword=key, button=button))
                layout.addWidget(anki)
                layout.addWidget(audio)
                self._headword_rows[key] = row, anki, audio
            row, anki, audio = self._headword_rows[key]
            prefix = f"profiles/{self.preferred_foreign}/"
            anki.setVisible(self.settings.value(prefix + "anki/enabled", False, bool)
                            and self.settings.value(prefix + "buttons/anki", True, bool))
            audio.setVisible(self.settings.value(prefix + "buttons/audio", True, bool))
            audio.setEnabled(self._display_revision == self.revision)
            audio.setIcon(action_icon("audio", config.color_foreground))
        if self._headword_rows:
            self.anki_button.hide()
            self.audio_button.hide()

    def _headword_clearance(self):
        width = max((row.sizeHint().width() for row, anki, audio in self._headword_rows.values()
                     if not anki.isHidden() or not audio.isHidden()), default=0)
        return width + self._action_clearance() if width else 0

    def _position_headword_actions(self):
        if not self._headword_rows:
            return
        document = self.browser.document()
        headings = self._headword_blocks
        viewport = self.browser.viewport()
        scroller = self.browser.section_scroll
        for index, (row, anki, audio) in enumerate(self._headword_rows.values()):
            if (index >= len(headings) or not headings[index].isValid()
                    or anki.isHidden() and audio.isHidden()):
                row.hide()
                continue
            block = headings[index]
            rect = document.documentLayout().blockBoundingRect(block)
            top = rect.top() - self.browser.verticalScrollBar().value()
            if not scroller.header.isHidden() and scroller._heading == block.position():
                top = scroller.header.y()
            size = row.sizeHint()
            shared_width = self._action_clearance() if block == self._action_heading else 0
            line = block.layout().lineAt(0) if block.layout().lineCount() else None
            height = max(line.y() + line.height() if line else rect.height(), size.height())
            row.setGeometry(round(viewport.width() - document.documentMargin() - size.width() - shared_width),
                            round(top + (height - size.height()) / 2), size.width(), size.height())
            row.setVisible(top + height > 0 and top < viewport.height() and not self._translation_view)
            row.raise_()

    def open_search(self, text="", *, at_cursor=False, passive=False, selection=False):
        self._leave_translation()
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

    def scan_hold_changed(self, active):
        self._scan_hold_active = active
        self._autoplayed = set() if active else None

    def _audio_key(self, headword=None):
        result = self._result
        if result.entries:
            entries = self._headword_groups().get(headword, ()) if headword is not None else result.entries
            if not entries:
                return None
            entry = entries[0]
            return entry.language, entry.term, entry.reading or ""
        return result.source, result.text, ""

    def _autoplay_lookup(self):
        if (self._result is not None and self._result.entries
                and (self._peek or self._selection_lookup)
                and audio_autoplay_mode(self.settings, self.preferred_foreign) == "lookup"):
            self._autoplay()

    def _autoplay(self):
        if self._result is None:
            return
        key = self._audio_key()
        if self._autoplayed is not None:
            if key in self._autoplayed:
                return
            self._autoplayed.add(key)
        self.play_audio()

    def audio_source_menu(self, point, *, headword=None, button=None):
        if self._result is None or not self._result.entries:
            return
        from meikipop.audio.sources import database_path, source_label, source_order
        profile = self.preferred_foreign
        button = button or self.audio_button
        menu = QMenu(button)
        menu.addAction("Use source priority", lambda: self.play_audio(headword=headword))
        menu.addSeparator()
        for source in source_order(self.settings, profile):
            action = menu.addAction(source_label(source), lambda checked=False, source=source: self.play_audio(source=source, headword=headword))
            action.setEnabled(source in ("tts", "online") or bool(database_path(self.settings, profile)))
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
        menu.popup(button.mapToGlobal(point))

    def open_audio_settings(self):
        self.open_settings()
        self._setup.show_audio()

    def update_anki(self):
        from meikipop.anki import load_settings
        options = load_settings(self.settings, self.preferred_foreign)
        enabled = options.enabled
        groups = self._headword_groups()
        first = next(iter(groups), None)
        identity = (self.revision, options, tuple(groups))
        if (enabled and options.deck and options.model and options.fields and groups
                and self._display_revision == self.revision and not self._shutting_down
                and self._anki_check_task is None and self._anki_check_identity != identity):
            from meikipop.anki import AnkiClient
            from meikipop.gui.anki import AnkiTask
            self._anki_check_identity = identity
            words = tuple(dict.fromkeys(key[0] for key in groups))
            self._anki_check_task = AnkiTask(lambda: AnkiClient(options).existing_notes(words), identity, self)
            self._anki_check_task.finished.connect(self._anki_existing_finished)
            self._anki_check_task.thread.start()
        existing = self._anki_existing_notes if self._anki_existing_identity == identity else {}
        saved_words = self._anki_saved_notes if self._anki_saved_revision == self.revision else {}
        saved = first in saved_words or first in existing
        browse = first in saved_words or first in existing and options.duplicate_action == "prevent"
        ready = (enabled and self._result is not None and bool(self._result.entries)
                 and self._display_revision == self.revision and self._anki_task is None
                 and self._anki_browse_task is None)
        description = ("Adding to Anki…" if self._anki_task is not None else "Show in Anki" if browse else
                       "Add another note" if saved else "Add to Anki")
        icon = "anki_saved" if saved else "anki"
        self.anki_button.setProperty("action_name", icon)
        self.anki_button.setIcon(action_icon(icon, config.color_foreground))
        self.anki_button.setToolTip(description)
        self.anki_button.setAccessibleName(description)
        self.anki_button.setVisible(enabled and self.settings.value(
            f"profiles/{self.preferred_foreign}/buttons/anki", True, bool) and not self._headword_rows)
        self.anki_button.setEnabled(ready)
        for key, (_, button, _) in self._headword_rows.items():
            saved_word = key in saved_words or key in existing
            icon = "anki_saved" if saved_word else "anki"
            description = ("Show in Anki" if key in saved_words or key in existing and options.duplicate_action == "prevent"
                           else "Add another note" if saved_word else "Add to Anki")
            button.setProperty("action_name", icon)
            button.setIcon(action_icon(icon, config.color_foreground))
            button.setToolTip(description)
            button.setAccessibleName(description)
            button.setEnabled(ready)
        if hasattr(self, "anki_shortcut"):
            binding = self.settings.value(f"profiles/{self.preferred_foreign}/anki/shortcut", "")
            self.anki_shortcut.setKey(QKeySequence(binding))
            self.anki_shortcut.setEnabled(ready and not browse and bool(binding))

    def _anki_existing_finished(self, response):
        task, self._anki_check_task = self._anki_check_task, None
        task.deleteLater()
        if self._shutting_down:
            return
        identity, found, error = response
        from meikipop.anki import load_settings
        current = (self.revision, load_settings(self.settings, self.preferred_foreign), tuple(self._headword_groups()))
        if identity == current:
            self._anki_existing_identity = identity
            self._anki_existing_notes = {key: found[key[0]] for key in identity[2] if not error and key[0] in found}
        self.update_anki()

    def add_to_anki(self, *, headword=None):
        from meikipop.anki import AnkiClient, load_settings
        from meikipop.gui.anki import AnkiTask, export_note
        options = load_settings(self.settings, self.preferred_foreign)
        if not options.enabled or self._display_revision != self.revision or not self._result or not self._result.entries:
            return
        if self._anki_task is not None or self._anki_browse_task is not None:
            return
        groups = self._headword_groups()
        headword = headword if headword is not None else next(iter(groups))
        if headword not in groups:
            return
        query = ""
        if self._anki_saved_revision == self.revision and headword in self._anki_saved_notes:
            note_id, saved_options = self._anki_saved_notes[headword]
            query = f"nid:{note_id}"
        elif (self._anki_existing_identity == (self.revision, options, tuple(groups))
              and headword in self._anki_existing_notes and options.duplicate_action == "prevent"):
            saved_options = options
            query = "nid:" + ",".join(map(str, self._anki_existing_notes[headword]))
        if query:
            self._anki_browse_task = AnkiTask(
                lambda: AnkiClient(saved_options).call("guiBrowse", query=query),
                self.revision, self)
            self._anki_browse_task.finished.connect(self._anki_browse_finished)
            self.update_anki()
            self._anki_browse_task.thread.start()
            return
        if not options.deck or not options.model or not options.fields:
            self.open_settings()
            self._setup.show_anki()
            return
        entries, sentence = tuple(groups[headword]), self._result_context
        kanji = tuple(item for item in self._result.kanji if item.character in headword[0])
        selection, translation = self.browser.selected_text(), self._result.translation
        screenshot, directory = self._result_screenshot, self.directory
        audio_clip = getattr(self.audio, "current_clip", None)
        self._anki_task = AnkiTask(
            lambda: export_note(entries, sentence, selection, options, translation=translation,
                                screenshot=screenshot, directory=directory, audio_clip=audio_clip, kanji=kanji),
            (self.revision, headword, options), self)
        self._anki_task.finished.connect(self._anki_finished)
        self.show_message("")
        self.update_anki()
        self._anki_task.thread.start()

    def _anki_finished(self, response):
        task, self._anki_task = self._anki_task, None
        task.deleteLater()
        (revision, headword, options), note_id, error = response
        self._anki_check_identity = None
        if not error and revision == self.revision:
            if self._anki_saved_revision != revision:
                self._anki_saved_notes.clear()
            self._anki_saved_revision = revision
            self._anki_saved_note = (note_id, options)
            self._anki_saved_notes[headword] = (note_id, options)
        if error:
            self.show_message(error if self._display_revision == revision else f"{headword[0]}: {error}")
        self.update_anki()

    def _anki_browse_finished(self, response):
        self._anki_browse_task.deleteLater()
        self._anki_browse_task = None
        revision, _, error = response
        if self._display_revision == revision:
            self.show_message(error)
        self.update_anki()

    def play_audio(self, *, sentence=False, translation=False, source=None, headword=None):
        if self._result is None or self._display_revision != self.revision:
            return
        if not sentence and not translation and self._autoplayed is not None:
            self._autoplayed.add(self._audio_key(headword))
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
            entries = self._headword_groups().get(headword, ()) if headword is not None else result.entries
            if not entries:
                return
            options = {"source": source} if source else {}
            self.audio.play(entries[0], self.revision, self.settings, profile=self.preferred_foreign, **options)
            return
        self.audio.play_text(text, language, self.revision, self.settings, profile=self.preferred_foreign)

    def show_entries(self, entries, text="", source="ja", peek=False, kanji=(), analyses=(), suggestions=(), message=""):
        if peek and self.is_pinned:
            return False
        entries = tuple(entries or ())
        if (peek and self._peek and self._result is not None and self._result.text == text
                and self._result.source == source and self._result.entries == entries
                and self._result.analyses == tuple(analyses) and self._result.suggestions == tuple(suggestions)
                and self._result.message == message
                and self._result.kanji == tuple(kanji) and self.isVisible()):
            if self._autoplayed is not None and audio_autoplay_mode(self.settings, self.preferred_foreign) == "lookup":
                self._autoplay()
            return True
        self._invalidate()
        self._result_screenshot = None
        self._leave_translation()
        self._history.clear()
        self._new_chain = True
        entries = tuple(entries or ())
        partner = self.foreign.currentData()
        target = self.preferred_foreign if source == partner else partner
        result = SearchResult(text, source, target, entries, kanji=tuple(kanji), analyses=tuple(analyses),
                              suggestions=tuple(suggestions), message=message)
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self.translate.setEnabled(bool(text) and self.translation_available())
        self._set_peek(peek)
        self._display(result)
        self._autoplay_lookup()
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
        updates = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        self._pin_transition = True
        try:
            self._apply_pin(checked)
            self.fit_timer.stop()
            self._fit_preview()
        finally:
            self._pin_transition = False
            self.setUpdatesEnabled(updates)

        if checked and self._peek and audio_autoplay_mode(self.settings, self.preferred_foreign) == "pin":
            self._autoplay()

    def _apply_pin(self, checked):
        if checked:
            self.remember_foreground()
            if self._peek:
                self._preview_viewport_height = min(self.browser.viewport().height(),
                                                    math.ceil(self.browser.document().size().height()))
        self.pin.setToolTip("Unpin" if checked else "Pin")
        self.setSizeGripEnabled(checked or not self._peek)
        for grip in self.findChildren(QWidget):
            if grip.inherits("QSizeGrip"):
                grip.installEventFilter(self)
        if self._peek:
            if checked:
                if self._reading_size_custom or self._normal_size != QSize(480, 340):
                    self.setMinimumHeight(190)
                    self._resize_expanded()
            elif self._reading_size_custom or self.size() != self._auto_fit_size:
                self._normal_size = self.size()
        if checked:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            from meikipop.utils.window_focus import focus_pinned_popup
            self._opening_search = sys.platform == "darwin"
            focus_pinned_popup(self, self.browser)
            QTimer.singleShot(300, lambda: setattr(self, "_opening_search", False))
        self.context_label.hide()
        self._place_actions()
        self.layout().activate()
        self.render_timer.stop()
        self._render(preserve_scroll=True)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget)
                and watched.inherits("QSizeGrip")):
            self._reading_size_custom = True
        if (event.type() == QEvent.Type.KeyPress and watched is getattr(self, "search", None)
                and self.browser.section_scroll.enabled
                and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
                and self.browser.section_scroll.eventFilter(self.browser, event)):
            return True
        if (event.type() == QEvent.Type.Paint and hasattr(self, "browser")
                and watched is self.browser.viewport() and self._document_revision is not None
                and self._paint_revision != self._document_revision):
            self._paint_revision = self._document_revision
            mark("paint", self._document_revision)
        if event.type() == QEvent.Type.Resize and hasattr(self, "browser") and watched is self.browser.viewport():
            self._place_actions()
            if (self._peek and self.is_pinned and hasattr(self, "render_timer")
                    and not getattr(self, "_pin_transition", False)):
                self.render_timer.start(0)
        if (event.type() == QEvent.Type.ToolTip and watched is not self.browser.viewport()
                and not isinstance(watched, QToolButton)):
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
                self._pin_anchor_click = True
                self.pin.setChecked(True)
                QTimer.singleShot(0, lambda: setattr(self, "_pin_anchor_click", False))
                # Pinning changes the document under the pointer; this release
                # must not activate a link that appeared after the press.
                return True
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
            self._reading_size_custom = True
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

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if (self.settings.value("close_on_cursor_leave", False, bool) and self.isVisible()
                and not self._capture_visibility and not self.geometry().contains(QCursor.pos())
                and QApplication.mouseButtons() == Qt.MouseButton.NoButton
                and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None
                and not (self._setup is not None and self._setup.isVisible())):
            self.hide()

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
        binding = explicit if explicit is not None else self.settings.value("hotkey", "")
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
        for timer in (self.busy_delay, self.fit_timer, self.render_timer, self.stream_timer, self.link_timer):
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
    return settings.value(f"profiles/{profile}/audio_autoplay_mode", "pin")
