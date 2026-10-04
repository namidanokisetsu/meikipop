"""Kanji card data shared by local metadata packs and the legacy dictionary.

Compact glyph/readings/meanings with optional examples and components follow
the interaction in https://github.com/hectahertz/meikikai; no data is invented.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class KanjiEntry:
    character: str
    source: str = ""
    onyomi: tuple = ()
    kunyomi: tuple = ()
    meanings: tuple = ()
    tags: tuple = ()
    stats: tuple = ()
    components: tuple = ()
    examples: tuple = ()

    @property
    def readings(self):
        return tuple(dict.fromkeys((*self.onyomi, *self.kunyomi)))


def kanji_characters(text, limit=8):
    """Unique ideographs in source order, including CJK extension characters."""
    result = []
    for char in text:
        point = ord(char)
        if (0x3400 <= point <= 0x4DBF or 0x4E00 <= point <= 0x9FFF or
                0xF900 <= point <= 0xFAFF or 0x20000 <= point <= 0x2FA1F or
                0x30000 <= point <= 0x323AF):
            if char not in result:
                result.append(char)
                if len(result) >= limit:
                    break
    return tuple(result) if limit > 0 else ()


def from_legacy(data, source="KANJIDIC"):
    """Adapt an already-loaded legacy kanji record, preserving its examples."""
    readings = data.get("readings", ())
    onyomi = tuple(reading for reading in readings if any("ァ" <= char <= "ヺ" for char in reading))
    kunyomi = tuple(reading for reading in readings if reading not in onyomi)
    stats = data.get("stats", ())
    return KanjiEntry(character=data["character"], source=source, onyomi=onyomi, kunyomi=kunyomi,
                      meanings=tuple(data.get("meanings", ())), tags=tuple(data.get("tags", ())),
                      stats=tuple(stats.items()) if isinstance(stats, dict) else tuple(stats),
                      components=tuple(data.get("components", ())), examples=tuple(data.get("examples", ())))
