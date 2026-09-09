"""Reuse the Japanese Yomitan converter with Turkish navigation and compact previews."""
from html import escape
import re
from urllib.parse import quote, unquote, urlparse, parse_qs

from meikipop.scripts.import_yomitan_dict_html import StructuredContentConverter


PREVIEW_LIMIT = 5
NON_LEMMA_TAGS = {"non-lemma", "nonlemma"}
WIKTIONARY_METADATA = {
    "v": "verb",
    "n": "noun",
    "adj": "adjective",
    "adv": "adverb",
    "pron": "pronoun",
    "intj": "interjection",
    "conj": "conjunction",
    "prep": "preposition",
    "postp": "postposition",
    "det": "determiner",
    "num": "numeral",
    "name": "proper name",
    "phrase": "phrase",
    "vt": "transitive",
    "vi": "intransitive",
}


def _tokens(value):
    if isinstance(value, str):
        return tuple(value.split())
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def is_non_lemma(entry):
    values = _tokens(entry.get("pos", ())) + _tokens(entry.get("tags", ()))
    return any(str(value).lower() in NON_LEMMA_TAGS for value in values)


def filter_wiktionary_entries(entries):
    return tuple(entry for entry in entries if not is_non_lemma(entry))


def format_wiktionary_metadata(pos, tags=()):
    """Keep only common POS/grammar labels from structured source metadata."""
    labels = []
    for value in _tokens(pos) + _tokens(tags):
        label = WIKTIONARY_METADATA.get(str(value).lower())
        if label and label not in labels:
            labels.append(label)
    return " · ".join(labels)


def _node_kind(node):
    data = node.get("data", {}) if isinstance(node, dict) else {}
    return data.get("content", "") if isinstance(data, dict) else ""


def _structured_sense_count(node):
    if isinstance(node, list):
        return sum(_structured_sense_count(child) for child in node)
    if not isinstance(node, dict):
        return 0
    if _node_kind(node) == "glosses":
        content = node.get("content")
        return len(content) if isinstance(content, list) else int(bool(content))
    return _structured_sense_count(node.get("content"))


def sense_count(definitions):
    count = 0
    definitions = definitions if isinstance(definitions, (list, tuple)) else (definitions,)
    for definition in definitions:
        if isinstance(definition, str) and definition.strip():
            count += 1
        elif isinstance(definition, dict):
            if definition.get("type") == "text" and definition.get("text", "").strip():
                count += 1
            elif definition.get("type") == "structured-content":
                count += _structured_sense_count(definition.get("content")) or 1
    return count


class TurkishContentConverter(StructuredContentConverter):
    def __init__(self, expanded=False, examples=True):
        super().__init__(use_ruby=False)
        self.expanded, self.examples = expanded, examples

    def _node_to_html(self, node):
        if isinstance(node, dict):
            kind = _node_kind(node)
            if kind == "details-entry-examples":
                if not self.examples:
                    return ""
                content = node.get("content", ())
                content = content if isinstance(content, list) else [content]
                content = [child for child in content if _node_kind(child) != "summary-entry"]
                return f'<div class="wiktionary-examples">{self._node_to_html(content)}</div>'
            if kind == "summary-entry":
                text = node.get("content", "")
                if isinstance(text, str) and re.fullmatch(r"\s*(?:\d+\s+)?examples?\s*:?\s*", text, re.IGNORECASE):
                    return ""
            if kind == "extra-info":
                return self._node_to_html(node.get("content"))
            if kind == "example-sentence-a":
                node = dict(node)
                node.pop("style", None)
                return f'<div class="example wiktionary-example-tr">{super()._node_to_html(node)}</div>'
            if kind == "example-sentence-b":
                node = dict(node)
                node.pop("style", None)
                return f'<div class="example wiktionary-example-en">{super()._node_to_html(node)}</div>'
            if kind == "backlink" or (kind == "preamble" and not self.expanded):
                return ""
            if "example" in kind and not self.examples:
                return ""
            node = dict(node)
            # Source CSS is intended for a browser and may override the reader's theme.
            node.pop("style", None)
            if kind == "glosses" and not self.expanded and isinstance(node.get("content"), list):
                node["content"] = node["content"][:PREVIEW_LIMIT]
        return super()._node_to_html(node)

    def _anchor_to_html(self, node):
        parsed = urlparse(node.get("href", ""))
        word = None
        if parsed.netloc == "en.wiktionary.org" and parsed.path.startswith("/wiki/"):
            word = unquote(parsed.path[6:]).replace("_", " ")
        elif not parsed.scheme and not parsed.netloc:
            word = parse_qs(parsed.query).get("query", [None])[0]
        label = self._node_to_html(node.get("content"))
        return f'<a class="term" href="word:{quote(word, safe="")}">{label}</a>' if word else label


def render_wiktionary(entries, expanded, examples):
    entries = filter_wiktionary_entries(entries)
    if not entries:
        return ""
    converter = TurkishContentConverter(expanded, examples)
    html = ['<p class="source"><small><b>Wiktionary</b></small></p>']
    needs_more = False
    for entry in entries:
        definitions = entry.get("definitions", ())
        needs_more = needs_more or sense_count(definitions) > PREVIEW_LIMIT
        glosses = converter.extract_glosses(definitions)
        if not expanded:
            glosses = glosses[:PREVIEW_LIMIT]
        html.append(f'<h2 class="headword">{escape(entry.get("word", ""))}</h2>')
        metadata = format_wiktionary_metadata(entry.get("pos", ()), entry.get("tags", ()))
        if metadata:
            html.append(f'<p class="metadata">{escape(metadata)}</p>')
        html.extend(glosses)
    if needs_more:
        html.append(f'<a name="more-Wiktionary"></a><table class="expand"><tr><td align="center">'
                    f'<a class="control" href="more:Wiktionary">{"Show less ▴" if expanded else "Show more ▾"}</a>'
                    '</td></tr></table>')
    return "".join(html)
