"""Reading-specific Yomitan pitch metadata and native inline notation.

Format: https://github.com/yomidevs/yomitan/blob/master/ext/data/schemas/dictionary-term-meta-bank-v3-schema.json
Notation adapted from Yomitan e7334a96106a6c74e6fa75bd33a5ea1219d92712,
pronunciation-generator.js and display-pronunciation.css, GPL-3.0-or-later.
Copyright (C) 2023-2026 Yomitan Authors; 2021-2022 Yomichan Authors.
"""
from dataclasses import dataclass
from html import escape
import json
import re
import unicodedata
from urllib.parse import quote, unquote

from .metadata import _bank_rows

PITCH_PREFIX = "meikipop-pitch:"
PITCH_OBJECT = 4098  # QTextFormat.UserObject + 2, following the shared ruby object.
PITCH_DATA = 1048580  # QTextFormat.UserProperty + 4; ruby reserves +1 through +3.
_renderer_type = None


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
        if (not isinstance(term, str) or not isinstance(data, dict)
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
            # Blank lookup keys cannot be indexed; validate their payload first.
            if term.strip():
                yield term, data["reading"], normalized


def levels(pitch):
    count = len(morae(pitch.reading))
    if isinstance(pitch.position, str):
        # Missing suffix levels are unknown, not an inferred drop.
        return tuple(c == "H" for c in pitch.position[:count + 1])
    return tuple(i == 0 if pitch.position == 1 else i > 0 and (
        pitch.position == 0 or i < pitch.position) for i in range(count + 1))


def pitch_category(pitch):
    count = len(morae(pitch.reading))
    if isinstance(pitch.position, str):
        if len(pitch.position) < count + 1:
            return None
        positions = [index for index in range(1, len(pitch.position))
                     if pitch.position[index - 1:index + 1] == "HL"]
        position = positions[0] if positions else 0 if pitch.position.startswith("L") else -1
    else:
        position = pitch.position
    if position > count:
        return None
    if position == 0:
        return "heiban"
    if position == 1:
        return "atamadaka"
    if position > 1:
        return "odaka" if position == count else "nakadaka"
    return None


def nasal_mora(text):
    first = "".join(char for char in unicodedata.normalize("NFD", text[0])
                    if char not in "\u3099\u309a")
    return first + text[1:]


def pitch_payload(href):
    if not href.startswith(PITCH_PREFIX) or len(href) > 8192:
        return None
    try:
        data = json.loads(unquote(href[len(PITCH_PREFIX):].partition("#")[0]))
        pitch = Pitch("", data["reading"], data["position"], _markers(data.get("nasal", [])),
                      _markers(data.get("devoice", [])))
        if not isinstance(pitch.reading, str) or not 1 <= len(pitch.reading) <= 256:
            return None
        if not (type(pitch.position) is int and pitch.position >= 0 or
                isinstance(pitch.position, str) and len(pitch.position) <= 257 and re.fullmatch("[HL]+", pitch.position)):
            return None
        return dict(reading=pitch.reading, position=pitch.position,
                    nasal=list(pitch.nasal), devoice=list(pitch.devoice))
    except (KeyError, TypeError, ValueError):
        return None


def pitch_format(fmt, payload):
    from PyQt6.QtGui import QTextCharFormat, QTextFormat
    result = QTextCharFormat(fmt)
    result.setAnchor(False)
    result.setAnchorHref("")
    result.setFontUnderline(False)
    result.setObjectType(PITCH_OBJECT)
    result.setProperty(QTextFormat.Property.UserProperty.value + 1,
                       f'{payload["reading"]} [{payload["position"]}]')
    result.setProperty(PITCH_DATA, json.dumps(payload, ensure_ascii=False))
    return result


def install_pitch_renderer(document, parent):
    from PyQt6.QtCore import QObject, QPointF, QRectF, QSizeF, Qt
    from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPen, QTextFormat, QTextObjectInterface
    global _renderer_type
    if _renderer_type is None:
        class PitchObject(QObject, QTextObjectInterface):
            @staticmethod
            def layout(document, fmt):
                data = json.loads(fmt.property(PITCH_DATA))
                pitch = Pitch("", data["reading"], data["position"], tuple(data["nasal"]), tuple(data["devoice"]))
                font = QFont(fmt.toCharFormat().font())
                font.setFamilies(font.families() or document.defaultFont().families())
                if font.pixelSize() > 0:
                    font.setPixelSize(font.pixelSize())
                else:
                    font.setPointSizeF(font.pointSizeF())
                metrics = QFontMetricsF(font)
                em = metrics.height()
                pattern = levels(pitch)
                cells, x = [], 0.0
                for index, original in enumerate(morae(pitch.reading)):
                    nasal, devoice = index + 1 in pitch.nasal, index + 1 in pitch.devoice
                    text = nasal_mora(original) if nasal else original
                    width = metrics.horizontalAdvance(text)
                    high = pattern[index] if index < len(pattern) else False
                    drop = high and index + 1 < len(pattern) and not pattern[index + 1]
                    cells.append((text, x, width, high, drop, nasal, devoice))
                    x += width + (em * .2 if drop else 0)
                suffix = f" [{pitch.position}]"
                width = x + metrics.horizontalAdvance(suffix)
                height = -metrics.tightBoundingRect(pitch.reading).top() + em * .3
                return pitch, font, metrics, em, cells, x, suffix, QSizeF(width, height)

            def intrinsicSize(self, document, position, fmt):
                return self.layout(document, fmt)[-1]

            def drawObject(self, painter, rect, document, position, fmt):
                pitch, font, metrics, em, cells, suffix_x, suffix, _ = self.layout(document, fmt)
                from meikipop.config.config import config
                light = QColor(config.color_background).lightnessF() > .5
                palettes = ({"heiban": "#2563b3", "atamadaka": "#c63a45", "nakadaka": "#a36018", "odaka": "#28784f"},
                            {"heiban": "#61aeee", "atamadaka": "#ef7c83", "nakadaka": "#edb56e", "odaka": "#7ecc9f"})
                colors = getattr(config, "pitch_colors", True)
                color = QColor(palettes[not light].get(pitch_category(pitch),
                                                      fmt.toCharFormat().foreground().color().name())
                               if colors else fmt.toCharFormat().foreground().color())
                danger = QColor("#c83c28" if light else "#ef8170") if colors else color
                painter.save()
                painter.setRenderHint(painter.RenderHint.Antialiasing)
                painter.setFont(font)
                baseline, bar = rect.bottom(), rect.top() + em * .1
                for text, x, width, high, drop, nasal, devoice in cells:
                    x += rect.x()
                    painter.setPen(color)
                    painter.drawText(QPointF(x, baseline), text)
                    bounds = metrics.tightBoundingRect(text)
                    if high:
                        painter.setPen(QPen(color, max(1, em * .07)))
                        edge = x + width + (em * .1 if drop else 0)
                        painter.drawLine(QPointF(x, bar), QPointF(edge, bar))
                        if drop:
                            painter.drawLine(QPointF(edge, bar), QPointF(edge, bar + em * .4))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    if devoice:
                        pen = QPen(danger, max(1, em * .07))
                        pen.setStyle(Qt.PenStyle.DotLine)
                        painter.setPen(pen)
                        diameter = em * .85
                        painter.drawEllipse(QRectF(x + (width - diameter) / 2,
                                                  baseline + bounds.center().y() - diameter / 2,
                                                  diameter, diameter))
                    if nasal:
                        painter.setPen(QPen(danger, max(1, em * .065)))
                        diameter = em * .28
                        first_width = metrics.horizontalAdvance(text[0])
                        painter.drawEllipse(QRectF(x + first_width - diameter * .7,
                                                  baseline + bounds.top() + em * .08,
                                                  diameter, diameter))
                painter.setPen(color)
                painter.drawText(QPointF(rect.x() + suffix_x, baseline), suffix)
                painter.restore()
        _renderer_type = PitchObject
    renderer = _renderer_type(parent)
    document.documentLayout().registerHandler(PITCH_OBJECT, renderer)
    return renderer


def render_pitches(pitches, inline=False, *, native=True):
    rows = []
    for pitch in pitches:
        data = dict(reading=pitch.reading, position=pitch.position, nasal=pitch.nasal, devoice=pitch.devoice)
        href = PITCH_PREFIX + quote(json.dumps(data, ensure_ascii=False, separators=(",", ":")), safe="")
        tags = " · " + escape(" · ".join(pitch.tags)) if pitch.tags else ""
        if native:
            reading = f'<a href="{href}" style="text-decoration:none">{escape(pitch.reading)} [{escape(str(pitch.position))}]</a>'
        else:
            # Cards render in a browser, which cannot resolve the Qt object link.
            pattern, parts = levels(pitch), []
            for index, mora in enumerate(morae(pitch.reading)):
                text = escape(nasal_mora(mora) if index + 1 in pitch.nasal else mora)
                if index + 1 in pitch.nasal:
                    text += '<sup style="color:#c83c28">○</sup>'
                if index + 1 in pitch.devoice:
                    text = f'<span style="border:1px dotted #c83c28;border-radius:50%">{text}</span>'
                if index < len(pattern) and pattern[index]:
                    text = f'<span style="text-decoration:overline">{text}</span>'
                parts.append(text)
                if index + 1 < len(pattern) and pattern[index] and not pattern[index + 1]:
                    parts.append("ꜜ")
            reading = f'{"".join(parts)} [{escape(str(pitch.position))}]'
        rows.append(reading + tags)
    text = ' · '.join(dict.fromkeys(rows))
    return text if inline or not text else '<p style="margin:0"><small>' + text + '</small></p>'
