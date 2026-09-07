"""Compact Turkish dictionary content."""
from html import escape
from urllib.parse import quote

from meikipop.config.config import config


def render_result(result, show_more=False, examples=True, wordnet_expanded=False, word_color=None, header_size=None):
    word_color = word_color or config.color_highlight_word
    header_size = header_size or config.font_size_header
    html = [f'<style>a {{color: {word_color}; text-decoration:none;}} '
            f'p {{margin:3px 0;}} h2 {{font-size:{header_size}px; font-weight:normal; '
            f'color:{word_color}; margin:2px 0;}} li {{margin-bottom:3px;}}</style>']
    if result.status.startswith("Exact fallback"):
        html.append("<p><small>Exact lookup only. Install Stanza models in Settings to analyze word forms.</small></p>")
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
    if not result.entries:
        html.append("<p>No TDK entry found.</p>")
    if result.suggestions:
        html.append("<p><b>Did you mean?</b></p><ul>")
        for i, suggestion in enumerate(result.suggestions):
            html.append(f'<li><a href="suggestion:{i}">{escape(suggestion.headword)}</a>'
                        f' <small>via {escape(suggestion.candidate)}</small></li>')
        html.append("</ul>")
    for entry in result.entries:
        html.append(f"<h2>{escape(entry['headword'])}</h2>")
        match = next((m for m in result.matches if m.entry_id == entry["id"]), None)
        if match is not None and result.text[match.start:match.end] != entry["headword"]:
            surface = result.text[match.start:match.end]
            label = " · casing retry" if match.route == "casing_lemma" else ""
            html.append(f"<p>{escape(surface)} → {escape(entry['headword'])}{label}</p>")
        elif match is None and result.target is not None:
            token = result.tokens[result.target]
            surface = result.text[token.start:token.end]
            html.append(f"<p>{escape(surface)} → {escape(token.lemma)} · {escape(token.pos or '')}</p>")
        html.append("<ol style='margin-top:3px; margin-bottom:4px; margin-left:18px;'>")
        for sense in entry["senses"] if show_more else entry["senses"][:3]:
            tags = ", ".join(sense["labels"])
            tag_html = f"<i>{escape(tags)}</i> " if config.show_pos or config.show_tags else ""
            html.append(f"<li>{tag_html}{escape(sense['text'])}")
            if examples:
                for example in sense["examples"][:1]:
                    author = " — " + escape(example["author"]) if example["author"] else ""
                    html.append(f"<p><i>{escape(example['text'])}{author}</i></p>")
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
    if result.entries:
        html.append('<p><small>TDK</small></p>')
    if result.wordnet and result.entries and not wordnet_expanded:
        html.append(f'<p><a href="section:wordnet">WordNet · {len(result.wordnet)} senses ▸</a></p>')
        return "".join(html)
    if result.wordnet:
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

