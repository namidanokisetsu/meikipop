"""Compact Turkish dictionary content."""
from html import escape
from urllib.parse import quote

from meikipop.config.config import config


def render_result(result, show_more=False, examples=True, wordnet_expanded=False, word_color=None, header_size=None, source_order=None):
    word_color = word_color or config.color_highlight_word
    header_size = header_size or config.font_size_header
    html = [f'<style>a {{color: {word_color}; text-decoration:none;}} '
            f'p {{margin:3px 0;}} h2 {{font-size:{header_size}px; font-weight:normal; '
            f'color:{word_color}; margin:2px 0;}} li {{margin-bottom:3px;}}</style>']
    if len(result.tokens) > 1:
        html.append('<p>')
        offset = 0
        for i, token in enumerate(result.tokens):
            html.append(escape(result.text[offset:token.start]).replace("\n", "<br>"))
            label = escape(result.text[token.start:token.end])
            if i == result.target:
                label = f"<b>{label}</b>"
            html.append(f'<a href="token:{i}">{label}</a>')
            offset = token.end
        html.append(escape(result.text[offset:]).replace("\n", "<br>") + "</p><hr>")
    if not result.entries and not result.wordnet and not result.wiktionary and not result.suggestions:
        html.append("<p>No entry found.</p>")
    if result.suggestions:
        html.append("<p><b>Did you mean?</b></p><ul>")
        for i, suggestion in enumerate(result.suggestions):
            html.append(f'<li><a href="suggestion:{i}">{escape(suggestion.headword)}</a>'
                        "</li>")
        html.append("</ul>")
    prefix, html = html, []
    if result.entries:
        html.append("<p><small><b>TDK</b></small></p>")
    for entry in result.entries:
        html.append(f'<h2><a href="pin:">{escape(entry["headword"])}</a></h2>')
        html.append("<ol style='margin-top:3px; margin-bottom:4px; margin-left:12px;'>")
        for sense in entry["senses"] if show_more else entry["senses"][:3]:
            tags = ", ".join(sense["labels"])
            tag_html = f"<i>{escape(tags)}</i> " if config.show_pos or config.show_tags else ""
            html.append(f"<li>{tag_html}{escape(sense['text'])}")
            if examples:
                for example in sense["examples"][:1]:
                    author = " · " + escape(example["author"]) if example["author"] else ""
                    html.append(f"<p><i>{escape(example['text'])}{author}</i></p>")
            html.append("</li>")
        html.append("</ol>")
        if not show_more and (len(entry["senses"]) > 3 or entry["relations"]):
            html.append('<table width="100%"><tr><td align="center"><a href="more:">Show more ▾</a></td></tr></table>')
        if entry["relations"]:
            if show_more:
                html.append("<p><b>Related expressions</b></p>")
                for i, rel in enumerate(entry["relations"]):
                    html.append(f'<p><a href="related:{entry["id"]}:{i}">{escape(rel["phrase"])}</a></p>')
    tdk, html = "".join(html), []
    if result.wordnet and (result.entries or result.wiktionary) and not wordnet_expanded:
        html.append('<p><a href="section:wordnet">KeNet ▸</a></p>')
    elif result.wordnet:
        html.append('<hr><a name="wordnet"></a><p><small><b>KeNet</b></small></p>')
    if result.wordnet and (wordnet_expanded or not (result.entries or result.wiktionary)):
        for group in result.wordnet if show_more else result.wordnet[:3]:
            html.append(f"<p><b>{escape(group['definition'])}</b> <small>{escape(group['pos'])}</small></p>")
            matched = {m["spelling"] for m in group.get("matched_members", ())}
            synonyms = list(dict.fromkeys(m["spelling"] for m in group["members"] if m["spelling"] not in matched))
            html.append(" · ".join(f'<a href="word:{quote(w, safe="")}">{escape(w)}</a>' for w in (synonyms if show_more else synonyms[:4])))
            if examples and group.get("example"):
                sentences = [sentence.strip() for sentence in group['example'].split('|') if sentence.strip()]
                for sentence in sentences if show_more else sentences[:1]:
                    html.append(f"<p>{escape(sentence)}</p>")
            relations = group["relations"] if show_more else []
            labels = {"HYPERNYM": "Broader", "HYPONYM": "Narrower", "ANTONYM": "Antonyms", "DERIVATION_RELATED": "Related words"}
            for kind in dict.fromkeys(r["kind"] for r in relations):
                members = list(dict.fromkeys(r["spelling"] for r in relations if r["kind"] == kind))
                html.append(f'<p><small>{escape(labels.get(kind, kind.replace("_", " ").title()))}:</small> ')
                html.append(" · ".join(f'<a href="word:{quote(w, safe="")}">{escape(w)}</a>' for w in (members if show_more else members[:5])) + "</p>")
        if not show_more:
            html.append('<table width="100%"><tr><td align="center"><a href="more:">Show more ▾</a></td></tr></table>')
    from .wiktionary_rendering import render_wiktionary
    sections = {"TDK": tdk, "Wiktionary": render_wiktionary(result.wiktionary, show_more, examples), "KeNet": "".join(html)}
    order = dictionary_order(source_order)
    return "".join(prefix) + "<hr>".join(sections[name] for name in order if sections[name])


def dictionary_order(value=None):
    names = ("TDK", "Wiktionary", "KeNet")
    value = value if isinstance(value, (list, tuple)) else []
    return list(dict.fromkeys([name for name in value if name in names] + list(names)))

