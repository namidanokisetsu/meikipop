"""Reuse the Japanese Yomitan converter with Turkish navigation and compact previews."""
from html import escape
from urllib.parse import quote, unquote, urlparse, parse_qs

from meikipop.scripts.import_yomitan_dict_html import StructuredContentConverter


class TurkishContentConverter(StructuredContentConverter):
    def __init__(self, expanded=False, examples=True):
        super().__init__(use_ruby=False)
        self.expanded, self.examples = expanded, examples

    def _node_to_html(self, node):
        if isinstance(node, dict):
            kind = node.get("data", {}).get("content", "")
            if kind == "backlink" or (kind == "preamble" and not self.expanded):
                return ""
            if "example" in kind and not self.examples:
                return ""
            node = dict(node)
            # Source CSS is intended for a browser and may override the reader's theme.
            node.pop("style", None)
            if kind == "glosses" and not self.expanded and isinstance(node.get("content"), list):
                node["content"] = node["content"][:3]
        return super()._node_to_html(node)

    def _anchor_to_html(self, node):
        parsed = urlparse(node.get("href", ""))
        word = None
        if parsed.netloc == "en.wiktionary.org" and parsed.path.startswith("/wiki/"):
            word = unquote(parsed.path[6:]).replace("_", " ")
        elif not parsed.scheme and not parsed.netloc:
            word = parse_qs(parsed.query).get("query", [None])[0]
        label = self._node_to_html(node.get("content"))
        return f'<a href="word:{quote(word, safe="")}">{label}</a>' if word else label


def render_wiktionary(entries, expanded, examples):
    if not entries:
        return ""
    converter = TurkishContentConverter(expanded, examples)
    html = ["<p><small><b>Wiktionary</b></small></p>"]
    for entry in entries:
        html.append(f'<h2>{escape(entry["word"])}</h2><p><small>{escape(entry["pos"])}</small></p>')
        html.extend(converter.extract_glosses(entry["definitions"]))
    if not expanded:
        html.append('<table width="100%"><tr><td align="center"><a href="more:">Show more ▾</a></td></tr></table>')
    return "".join(html)
