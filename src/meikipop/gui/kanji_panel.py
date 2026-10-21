"""Compact Qt rich-text kanji cards; expand details without another window."""
from html import escape
from dataclasses import replace
from urllib.parse import quote


_STAT_LABELS = {"strokes": "Strokes", "stroke_count": "Strokes", "grade": "Grade",
                "jlpt": "JLPT", "freq": "Frequency", "frequency": "Frequency",
                "radical": "Radical", "ucs": "Unicode", "unicode": "Unicode"}


def _text(value):
    return escape(str(value), quote=True)


def _joined(values, limit=None):
    values = tuple(str(value) for value in values if value is not None and str(value))
    if limit is None or len(values) <= limit:
        return " · ".join(_text(value) for value in values)
    return " · ".join(_text(value) for value in values[:limit]) + " …"


def _stats_rows(stats):
    values = stats.items() if isinstance(stats, dict) else stats
    for key, value in values:
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                yield f"{key}: {subkey}", subvalue
        else:
            yield _STAT_LABELS.get(key, key), value


def _entry_html(entry, reading_color, *, full=False, show_source=False):
    parts = []
    if show_source and entry.source:
        parts.append(f'<p style="margin:0 0 1px"><small>{_text(entry.source)}</small></p>')
    if entry.meanings:
        parts.append(f'<p style="margin:0 0 1px">{_joined(entry.meanings, None if full else 3)}</p>')
    for label, readings in (("音", entry.onyomi), ("訓", entry.kunyomi)):
        if readings:
            parts.append(f'<p style="margin:0"><small>{label}</small> '
                         f'<span style="color:{reading_color}">{_joined(readings, None if full else 4)}</span></p>')
    if not full:
        return "".join(parts)
    stats = [f'{_text(name)} {_text(value)}' for name, value in _stats_rows(entry.stats)
             if value is not None and str(value)]
    if stats:
        parts.append(f'<p style="margin:2px 0"><small>{" · ".join(stats)}</small></p>')
    if entry.tags:
        parts.append(f'<p style="margin:2px 0"><small>{_joined(entry.tags)}</small></p>')
    if entry.components:
        components = []
        for component in entry.components:
            if isinstance(component, dict):
                char, meaning = component.get("c", ""), component.get("m", "")
                components.append(f'<b>{_text(char)}</b> {_text(meaning)}'.strip())
            else:
                components.append(_text(component))
        parts.append('<p style="margin:5px 0 2px"><small>Parts</small> ' + " · ".join(components) + '</p>')
    if entry.examples:
        examples = []
        for example in entry.examples:
            if isinstance(example, dict):
                word, reading, meaning = example.get("w", ""), example.get("r", ""), example.get("m", "")
                row = f'<b>{_text(word)}</b>'
                if reading:
                    row += f' <span style="color:{reading_color}">{_text(reading)}</span>'
                if meaning:
                    row += f' {_text(meaning)}'
                examples.append(row)
            else:
                examples.append(_text(example))
        parts.append('<p style="margin:5px 0 2px"><small>Examples</small><br>' + '<br>'.join(examples) + '</p>')
    return "".join(parts)


def render_kanji_export(entries, term):
    """Card HTML shares full dictionary content, without popup links or fonts."""
    parts = []
    for character in dict.fromkeys(term):
        group = tuple(entry for entry in entries if entry.character == character)
        if not group:
            continue
        parts.append('<div class="kanji-detail" style="display:flex;gap:1em;'
                     'text-align:left;border-left:2px solid currentColor;padding-left:1em;margin:1em 0">'
                     f'<div class="kanji-character" style="font-size:2.5em">{_text(character)}</div>'
                     '<div class="kanji-content">')
        for entry in group:
            parts.append(_entry_html(entry, "inherit", full=True, show_source=True))
        parts.append('</div></div>')
    return '<div class="kanji-details">' + ''.join(parts) + '</div>' if parts else ''


def _character_link(character, accent, expanded, scheme="kanji"):
    href = quote(character, safe="")
    title = "Collapse" if expanded else "Expand"
    return (f'<a href="{scheme}:{href}" title="{title}" '
            f'style="color:{accent};text-decoration:none">{_text(character)}</a>')


def _shared_values(entries, field):
    values = []
    for entry in entries:
        for value in getattr(entry, field):
            if value is None or not str(value):
                continue
            match = next((item for item in values if item[0] == value), None)
            if match is None:
                match = (value, [])
                values.append(match)
            if entry.source and entry.source not in match[1]:
                match[1].append(entry.source)
    return values


def _attributed(value, sources):
    return f'<span title="{_text(" · ".join(sources))}">{_text(value)}</span>'


def render_kanji_extra(entries):
    """Keep unknown fields available under their original source."""
    parts = []
    for entry in entries:
        stats = [(name, value) for name, value in _stats_rows(entry.stats)
                 if name != "Strokes" and value is not None and str(value)]
        if not stats and not entry.tags:
            continue
        parts.append(f'<p><small><b>{_text(entry.source or "Dictionary")}</b></small></p>')
        for name, value in stats:
            parts.append(f'<p style="margin:0"><small>{_text(name)}</small> {_text(value)}</p>')
        if entry.tags:
            parts.append(f'<p style="margin:0"><small>Tags</small> {_joined(entry.tags)}</p>')
    return "".join(parts)


def render_kanji_details(entries, scheme="kanji", *, more=False):
    if not entries:
        return ""
    from meikipop.config.config import config
    from meikipop.utils.stroke_order_font import stroke_order_family
    character = entries[0].character
    accent = _text(config.color_highlight_word)
    reading_color = _text(config.color_highlight_reading)
    family = stroke_order_family(character) if getattr(config, "kanji_stroke_order", True) else ""
    glyph_style = f'font-size:128px;font-family:{_text(family)}' if family else 'font-size:96px'
    anchor = quote(f"{scheme}:{character}", safe="")
    parts = ['<table width="100%" cellspacing="0" cellpadding="1"><tr><td valign="top">',
             f'<a name="kanji-detail-{anchor}"></a><span style="{glyph_style}">'
             f'{_character_link(character, accent, True, scheme)}</span></td><td valign="top">']
    sources = tuple(dict.fromkeys(entry.source for entry in entries if entry.source))
    if sources:
        parts.append(f'<p style="margin:0"><small>{_joined(sources)}</small></p>')
    for label, field in (("Meanings", "meanings"), ("音", "onyomi"), ("訓", "kunyomi")):
        values = _shared_values(entries, field)
        if values:
            color = reading_color if field != "meanings" else _text(config.color_foreground)
            text = " · ".join(_attributed(value, sources) for value, sources in values)
            parts.append(f'<p style="margin:2px 0"><small>{label}</small><br>'
                         f'<span style="color:{color}">{text}</span></p>')
    strokes = {}
    for entry in entries:
        for name, value in _stats_rows(entry.stats):
            if name == "Strokes" and value is not None and str(value):
                sources = strokes.setdefault(str(value), [])
                if entry.source and entry.source not in sources:
                    sources.append(entry.source)
    for value, sources in strokes.items():
        source = f' <small>({_joined(sources)})</small>' if len(strokes) > 1 and sources else ""
        parts.append(f'<p style="margin:2px 0"><small>Strokes {_text(value)}</small>{source}</p>')
    parts.append('</td></tr>')
    parts.append('</table>')
    for field in ("components", "examples"):
        groups = {}
        for value, sources in _shared_values(entries, field):
            groups.setdefault(tuple(sources), []).append(value)
        for sources, values in groups.items():
            fields = {"components": (), "examples": (), field: tuple(values)}
            item = replace(entries[0], source=" · ".join(sources), meanings=(), onyomi=(), kunyomi=(),
                           stats=(), tags=(), **fields)
            parts.append(_entry_html(item, reading_color, full=True, show_source=len(entries) > 1))
    if more:
        parts.append(render_kanji_extra(entries))
    return "".join(parts)


def render_kanji(entries, expanded=False, *, compact_only=False, expanded_characters=()):
    """Return compact cards and optional full-width character detail sections."""
    if not entries:
        return ""
    from meikipop.config.config import config
    accent = _text(config.color_highlight_word)
    reading_color = _text(config.color_highlight_reading)
    parts = ['<p style="margin:8px 0 4px"><a name="scroll-section-kanji"></a><small><b>Kanji</b> &nbsp; <a href="kanji:toggle">',
             'Show less' if expanded else 'Details', '</a></small></p>']
    if compact_only:
        expanded = False
        parts = ['<p style="margin:8px 0 4px"><a name="scroll-section-kanji"></a></p>']
    expanded_characters = set(expanded_characters)
    groups = {}
    for entry in entries:
        groups.setdefault(entry.character, []).append(entry)
    groups = tuple(groups.items())
    detailed = {character for character, _ in groups
                if expanded or character in expanded_characters}
    columns = min(3, len(groups))
    parts.append('<table width="100%" cellspacing="0" cellpadding="0">')
    for row_start in range(0, len(groups), columns):
        row_groups = groups[row_start:row_start + columns]
        parts.append('<tr>')
        for character, group in row_groups:
            parts.append('<td valign="top" width="{}%" style="padding:0 2px 4px 0">'.format(100 // columns))
            parts.append('<table width="100%" cellspacing="0" cellpadding="1">')
            for index, entry in enumerate(group):
                parts.append('<tr>')
                if index == 0:
                    parts.append(f'<td width="36" rowspan="{len(group)}" valign="top" '
                                 f'style="font-size:30px;color:{accent}">'
                                 f'{_character_link(character, accent, character in detailed)}</td>')
                parts.append(f'<td valign="top">{_entry_html(entry, reading_color, show_source=len(group) > 1)}</td></tr>')
            parts.append('</table></td>')
        if len(row_groups) < columns:
            parts.append(f'<td colspan="{columns - len(row_groups)}"></td>')
        parts.append('</tr>')
    parts.append('</table>')
    for character, group in groups:
        if character not in detailed:
            continue
        parts.append(render_kanji_details(group, more=True))
    return "".join(parts)
