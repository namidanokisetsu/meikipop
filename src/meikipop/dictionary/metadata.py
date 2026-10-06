"""Yomitan metadata parsed one bank at a time, without extracting ZIP paths.

Formats: https://github.com/yomidevs/yomitan/tree/master/ext/data/schemas
"""
from dataclasses import dataclass
import json
import math
import re


@dataclass(frozen=True)
class Frequency:
    source: str
    rank: float | None
    label: str
    reading: str = ""
    mode: str = "rank-based"


def harmonic_rank(frequencies):
    """One vote per dictionary, using its best matching positive rank."""
    ranks = {}
    for frequency in frequencies:
        rank = frequency.rank
        if frequency.mode == "rank-based" and rank is not None and math.isfinite(rank) and rank > 0:
            ranks[frequency.source] = min(rank, ranks.get(frequency.source, rank))
    if not ranks:
        return None
    smallest = min(ranks.values())
    return smallest * (len(ranks) / math.fsum(smallest / rank for rank in ranks.values()))


def _bank_rows(archive, prefix, cancelled=None):
    pattern = re.compile(re.escape(prefix) + r"_(\d+)\.json")
    names = sorted((name for name in archive.namelist() if pattern.fullmatch(name)),
                   key=lambda name: int(pattern.fullmatch(name)[1]))
    for name in names:
        if cancelled and cancelled():
            raise InterruptedError("Dictionary import cancelled.")
        with archive.open(name) as stream:
            rows = json.load(stream)
        if not isinstance(rows, list):
            raise ValueError(f"Invalid dictionary metadata bank: {name}")
        for index, row in enumerate(rows):
            if index % 1000 == 0 and cancelled and cancelled():
                raise InterruptedError("Dictionary import cancelled.")
            if not isinstance(row, list):
                raise ValueError(f"Invalid metadata row in {name}")
            yield row


def _frequency_value(data):
    label = None
    if isinstance(data, dict):
        if "value" not in data or not isinstance(data["value"], (int, float)) or isinstance(data["value"], bool):
            raise ValueError("Frequency object needs a numeric value")
        label = data.get("displayValue")
        if label is not None and not isinstance(label, str):
            raise ValueError("Frequency displayValue must be text")
        data = data["value"]
    if isinstance(data, bool) or not isinstance(data, (str, int, float)):
        raise ValueError("Frequency must be a number, string, or value object")
    if isinstance(data, str):
        text = data.strip()
        # Text labels (e.g. a frequency band) are not invented numeric ranks.
        number = float(text.replace(",", "")) if re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text) else None
    else:
        number = float(data)
    if number is not None and (not math.isfinite(number) or number < 0):
        raise ValueError("Frequency value must be finite and non-negative")
    return number, label if label is not None else str(data)


def frequency_rows(archive, language="ja", cancelled=None):
    """Yield (term, reading, numeric_value_or_None, display_label).

    The importer owns language-specific keys. Original reading/text are retained
    so different readings of the same written word keep their own frequencies.
    The index's frequencyMode distinguishes counts from ranks at presentation.
    """
    for row in _bank_rows(archive, "term_meta_bank", cancelled):
        if len(row) != 3 or not isinstance(row[0], str) or not isinstance(row[1], str):
            raise ValueError("Invalid term metadata row")
        term, mode, data = row
        if mode != "freq":
            continue
        if not term.strip():
            continue
        reading = ""
        if isinstance(data, dict) and "frequency" in data:
            reading = data.get("reading")
            if not isinstance(reading, str):
                raise ValueError("Reading-specific frequency needs a reading")
            data = data["frequency"]
        value, label = _frequency_value(data)
        yield term, reading, value, label


def kanji_rows(archive, cancelled=None):
    """Yield (character, serializable data), accepting v3 and legacy v1 banks."""
    for row in _bank_rows(archive, "kanji_bank", cancelled):
        if len(row) < 4 or not all(isinstance(value, str) for value in row[:4]) or not row[0]:
            raise ValueError("Invalid kanji metadata row")
        character, onyomi, kunyomi, tags = row[:4]
        if len(row) >= 5 and isinstance(row[4], list):
            if len(row) != 6 or not isinstance(row[5], dict):
                raise ValueError("Kanji v3 rows need meanings and stats")
            meanings, stats = row[4], row[5]
        else:
            meanings, stats = row[4:], {}
        if not all(isinstance(meaning, str) for meaning in meanings):
            raise ValueError("Kanji meanings must be text")
        if not all(isinstance(name, str) and isinstance(value, str) for name, value in stats.items()):
            raise ValueError("Kanji stats must contain text values")
        yield character, {"onyomi": onyomi.split(), "kunyomi": kunyomi.split(),
                          "meanings": meanings, "tags": tags.split(), "stats": stats}
