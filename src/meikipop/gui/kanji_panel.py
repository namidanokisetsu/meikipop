"""Compact Qt rich-text kanji cards; expand details without another window."""
from html import escape
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


def _character_link(character, accent, expanded):
    href = quote(character, safe="")
    title = "Collapse" if expanded else "Expand"
    return (f'<a href="kanji:{href}" title="{title}" '
            f'style="color:{accent};text-decoration:none">{_text(character)}</a>')


def render_kanji(entries, expanded=False, *, compact_only=False, expanded_characters=()):
    """Return compact cards and optional full-width character detail sections."""
    if not entries:
        return ""
    from meikipop.config.config import config
    accent = _text(config.color_highlight_word)
    reading_color = _text(config.color_highlight_reading)
    parts = ['<hr><p style="margin:2px 0 4px"><small><b>Kanji</b> &nbsp; <a href="kanji:toggle">',
             'Show less' if expanded else 'Details', '</a></small></p>']
    if compact_only:
        expanded = False
        parts = ['<hr>']
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
        parts.append(f'<div style="margin:2px 0 6px"><p style="margin:2px 0 1px">'
                     f'<b>{_character_link(character, accent, True)}</b></p>')
        parts.append('<table width="100%" cellspacing="0" cellpadding="1">')
        for entry in group:
            parts.append(f'<tr><td valign="top">{_entry_html(entry, reading_color, full=True, show_source=True)}</td></tr>')
        parts.append('</table></div>')
    return "".join(parts)
