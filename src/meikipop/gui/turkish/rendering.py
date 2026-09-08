"""Compact Turkish dictionary content."""
from html import escape
from urllib.parse import quote

from meikipop.config.config import config


PREVIEW_LIMIT = 5


def _show_more_link(expanded, needed):
    if not needed:
        return ""
    label = "Show less ▴" if expanded else "Show more ▾"
    return f'<table class="expand"><tr><td align="center"><a class="control" href="more:">{label}</a></td></tr></table>'


def _tdk_example_html(example):
    author = f' <span class="attribution">· {escape(example["author"])}</span>' if example.get("author") else ""
    return f'<p class="example"><i>{escape(example["text"])}</i>{author}</p>'


def render_result(result, show_more=False, examples=True, wordnet_expanded=False, word_color=None, header_size=None, source_order=None):
    word_color = word_color or config.color_highlight_word
    header_size = header_size or config.font_size_header
    html = [f'<style>'
            f'a {{color:{word_color}; text-decoration:none;}} '
            f'p {{margin:2px 0;}} '
            f'h2 {{font-size:{header_size}px; font-weight:normal; color:{word_color}; margin:2px 0;}} '
            f'ol {{margin:2px 0 3px 12px; padding:0;}} '
            f'li {{margin:0 0 3px 0; padding:0;}} '
            f'.source {{color:{config.color_foreground};}} '
            f'.metadata {{color:{config.color_foreground}; opacity:0.7;}} '
            f'.metadata {{font-size:small;}} '
            f'.attribution {{color:{config.color_foreground}; opacity:0.65; font-size:0.9em;}} '
            f'.example {{'
            f'color:{config.color_foreground}; opacity:0.78; font-size:inherit; font-style:italic; '
            f'line-height:1.15em; margin:2px 0 0;}} '
            f'.term {{color:{config.color_foreground};}} '
            f'.expand {{width:100%; margin:3px 0 0;}} '
            f'.control,.headword {{color:{word_color};}} '
            f'.wiktionary-examples {{margin:2px 0 0;}} '
            f'.wiktionary-example-en {{opacity:0.68;}} '
            f'</style>']
    from .wiktionary_rendering import filter_wiktionary_entries, render_wiktionary
    wiktionary = filter_wiktionary_entries(result.wiktionary)
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
    if not result.entries and not result.wordnet and not wiktionary and not result.suggestions:
        html.append("<p>No entry found.</p>")
    if result.suggestions:
        html.append("<p><b>Did you mean?</b></p><ul>")
        for i, suggestion in enumerate(result.suggestions):
            html.append(f'<li><a href="suggestion:{i}">{escape(suggestion.headword)}</a>'
                        "</li>")
        html.append("</ul>")
    prefix, html = html, []
    if result.entries:
        html.append('<p class="source"><small><b>TDK</b></small></p>')
    tdk_needs_more = False
    for entry in result.entries:
        html.append(f'<h2><a class="headword" href="pin:">{escape(entry["headword"])}</a></h2>')
        html.append("<ol>")
        senses = entry["senses"] if show_more else entry["senses"][:PREVIEW_LIMIT]
        for sense in senses:
            tags = ", ".join(sense.get("labels", ()))
            tag_html = f'<span class="metadata"><i>{escape(tags)}</i></span> ' if (config.show_pos or config.show_tags) and tags else ""
            html.append(f"<li>{tag_html}{escape(sense['text'])}")
            if examples:
                for example in sense.get("examples", ()):
                    html.append(_tdk_example_html(example))
            html.append("</li>")
        html.append("</ol>")
        tdk_needs_more = tdk_needs_more or len(entry["senses"]) > PREVIEW_LIMIT or bool(entry.get("relations"))
        if entry.get("relations"):
            if show_more:
                html.append("<p><b>Related expressions</b></p>")
                for i, rel in enumerate(entry.get("relations", ())):
                    html.append(f'<p><a class="term" href="related:{entry["id"]}:{i}">{escape(rel["phrase"])}</a></p>')
    html.append(_show_more_link(show_more, tdk_needs_more))
    tdk, html = "".join(html), []
    if result.wordnet and (result.entries or wiktionary) and not wordnet_expanded:
        html.append('<p><a href="section:wordnet">KeNet ▸</a></p>')
    elif result.wordnet:
        html.append('<hr><a name="wordnet"></a><p class="source"><small><b>KeNet</b></small></p>')
    if result.wordnet and (wordnet_expanded or not (result.entries or wiktionary)):
        groups = result.wordnet if show_more else result.wordnet[:PREVIEW_LIMIT]
        for group in groups:
            html.append(f'<p><b>{escape(group["definition"])}</b> <span class="metadata">{escape(group["pos"])}</span></p>')
            matched = {m["spelling"] for m in group.get("matched_members", ())}
            synonyms = list(dict.fromkeys(m["spelling"] for m in group["members"] if m["spelling"] not in matched))
            if synonyms:
                html.append('<p class="terms">' + " · ".join(
                    f'<a class="term" href="word:{quote(w, safe="")}">{escape(w)}</a>'
                    for w in (synonyms if show_more else synonyms[:4])) + "</p>")
            if examples and group.get("example"):
                sentences = [sentence.strip() for sentence in group['example'].split('|') if sentence.strip()]
                for sentence in sentences:
                    html.append(f'<p class="example"><i>{escape(sentence)}</i></p>')
            relations = group["relations"] if show_more else []
            labels = {"HYPERNYM": "Broader", "HYPONYM": "Narrower", "ANTONYM": "Antonyms", "DERIVATION_RELATED": "Related words"}
            for kind in dict.fromkeys(r["kind"] for r in relations):
                members = list(dict.fromkeys(r["spelling"] for r in relations if r["kind"] == kind))
                html.append(f'<p><small>{escape(labels.get(kind, kind.replace("_", " ").title()))}:</small> ')
                html.append(" · ".join(f'<a class="term" href="word:{quote(w, safe="")}">{escape(w)}</a>' for w in (members if show_more else members[:5])) + "</p>")
        needs_more = len(result.wordnet) > PREVIEW_LIMIT or any(group.get("relations") for group in result.wordnet)
        html.append(_show_more_link(show_more, needs_more))
    sections = {"TDK": tdk, "Wiktionary": render_wiktionary(wiktionary, show_more, examples), "KeNet": "".join(html)}
    order = dictionary_order(source_order)
    return "".join(prefix) + "<hr>".join(sections[name] for name in order if sections[name])


def dictionary_order(value=None):
    names = ("TDK", "Wiktionary", "KeNet")
    value = value if isinstance(value, (list, tuple)) else []
    return list(dict.fromkeys([name for name in value if name in names] + list(names)))

