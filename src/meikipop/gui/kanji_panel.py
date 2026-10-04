"""Compact Qt rich-text kanji cards; expand details without another window."""
from html import escape


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


def render_kanji(entries, expanded=False):
    """Return HTML; callers handle the single ``kanji:toggle`` action."""
    if not entries:
        return ""
    from meikipop.config.config import config
    accent = _text(config.color_highlight_word)
    reading_color = _text(config.color_highlight_reading)
    parts = ['<hr><p><small><b>Kanji</b> &nbsp; <a href="kanji:toggle">',
             'Show less' if expanded else 'Details', '</a></small></p>']
    for entry in entries:
        parts.append('<table width="100%" cellspacing="0" cellpadding="3"><tr>'
                     f'<td width="48" valign="top" style="font-size:34px;color:{accent}">{_text(entry.character)}</td><td valign="top">')
        if entry.meanings:
            parts.append(f'<p style="margin:0 0 3px">{_joined(entry.meanings, None if expanded else 3)}</p>')
        for label, readings in (("音", entry.onyomi), ("訓", entry.kunyomi)):
            if readings:
                parts.append(f'<p style="margin:1px 0"><small>{label}</small> '
                             f'<span style="color:{reading_color}">{_joined(readings, None if expanded else 4)}</span></p>')
        if expanded:
            if entry.source:
                parts.append(f'<p style="margin:5px 0 2px"><small>{_text(entry.source)}</small></p>')
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
        parts.append('</td></tr></table>')
    return "".join(parts)
