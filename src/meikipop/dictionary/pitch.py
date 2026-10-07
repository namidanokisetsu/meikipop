"""Reading-specific Yomitan pitch metadata and portable HTML notation.

Format: https://github.com/yomidevs/yomitan/blob/master/ext/data/schemas/dictionary-term-meta-bank-v3-schema.json
"""
from dataclasses import dataclass
from html import escape
import re
import unicodedata

from .metadata import _bank_rows


@dataclass(frozen=True)
class Pitch:
    source: str
    reading: str
    position: int | str
    nasal: tuple = ()
    devoice: tuple = ()
    tags: tuple = ()


def morae(reading):
    result = []
    for char in unicodedata.normalize("NFC", reading):
        if result and char in "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ":
            result[-1] += char
        else:
            result.append(char)
    return tuple(result)


def _markers(value):
    values = value if isinstance(value, list) else [value]
    if any(type(item) is not int or item < 0 for item in values):
        raise ValueError("Invalid pitch pronunciation marker")
    return tuple(dict.fromkeys(values))


def pitch_rows(archive, cancelled=None, progress=None):
    for row in _bank_rows(archive, "term_meta_bank", cancelled, progress):
        if len(row) != 3 or row[1] != "pitch":
            continue
        term, _, data = row
        if (not isinstance(term, str) or not term.strip() or not isinstance(data, dict)
                or not isinstance(data.get("reading"), str) or not data["reading"]
                or not isinstance(data.get("pitches"), list)):
            raise ValueError("Invalid pitch metadata")
        for accent in data["pitches"]:
            position = accent.get("position") if isinstance(accent, dict) else None
            if not (type(position) is int and position >= 0 or
                    isinstance(position, str) and re.fullmatch("[HL]+", position)):
                raise ValueError("Invalid pitch position")
            tags = accent.get("tags", [])
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                raise ValueError("Invalid pitch tags")
            normalized = dict(position=position, nasal=_markers(accent.get("nasal", [])),
                              devoice=_markers(accent.get("devoice", [])), tags=tags)
            yield term, data["reading"], normalized


def levels(pitch):
    count = len(morae(pitch.reading))
    if isinstance(pitch.position, str):
        # Missing suffix levels are unknown, not an inferred drop.
        return tuple(c == "H" for c in pitch.position[:count + 1])
    return tuple(i == 0 if pitch.position == 1 else i > 0 and (
        pitch.position == 0 or i < pitch.position) for i in range(count + 1))


def render_pitches(pitches):
    rows = []
    for pitch in dict.fromkeys(pitches):
        pattern, parts = levels(pitch), []
        for index, mora in enumerate(morae(pitch.reading)):
            text = escape(mora)
            if index < len(pattern) and pattern[index]:
                text = f'<span style="text-decoration:overline">{text}</span>'
            parts.append(text)
            if index + 1 < len(pattern) and pattern[index] and not pattern[index + 1]:
                parts.append("ꜜ")
        annotations = list(pitch.tags)
        for label, indices in (("nasal", pitch.nasal), ("devoiced", pitch.devoice)):
            if indices:
                annotations.append(f'{label}: {", ".join(map(str, indices))}')
        suffix = " · " + escape(" · ".join(annotations)) if annotations else ""
        rows.append(f'<p><small>{"".join(parts)} [{escape(str(pitch.position))}]'
                    f' · {escape(pitch.source)}{suffix}</small></p>')
    return "".join(rows)
