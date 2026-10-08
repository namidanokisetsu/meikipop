"""Small, model-free language policies for lookup and source text spans.

The profile/shared-policy design follows Anki Miner's language registry:
https://github.com/0xzerolight/anki_miner/blob/a1955f4a/anki_miner/languages/registry.py
Implementation is independent; no upstream tokenizer or NLP model is imported.
Dictionary normalization never changes the source text used for offsets.
"""
from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata


_APOSTROPHES = frozenset("'’ʼ")
_CLOSERS = frozenset("'\"’”»›」』）)]}｣】〉》")
_TERMINATORS = frozenset(".!?。！？｡．؟।։")
_ABBREVIATIONS = frozenset({"dr", "prof", "mr", "mrs", "ms", "e.g", "i.e"})
_NAMES = {"ja": "日本語", "tr": "Türkçe", "en": "English", "zh": "中文",
          "ko": "한국어", "de": "Deutsch", "fr": "Français", "es": "Español",
          "ru": "Русский", "uk": "Українська", "ar": "العربية", "el": "Ελληνικά"}


def configured_profiles(settings):
    initial = settings.value("initial_language", "ja")
    settings.beginGroup("profiles")
    try:
        return tuple(dict.fromkeys((initial, *settings.childGroups())))
    finally:
        settings.endGroup()


def default_partner(code):
    return "ja" if code == "en" else "en"


def _letter_or_number(char):
    return char.isalnum()


def _mark(char):
    return unicodedata.category(char).startswith("M")


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str = ""
    word_mode: str = "spaced"
    abbreviations: frozenset[str] = _ABBREVIATIONS
    terminators: frozenset[str] = _TERMINATORS

    def lookup_key(self, text: str) -> str:
        """Same normalization at import/query time; keep existing pack keys."""
        text = unicodedata.normalize("NFKC", text).strip()
        if self.code == "tr":
            text = text.translate(str.maketrans("Iİ’ʼ", "ıi''"))
        return text.lower()

    def word_spans(self, text: str) -> tuple[tuple[int, int], ...]:
        """Exact source spans, not guessed lemmas or inferred word boundaries.

        Unspaced scripts expose one base character plus its combining marks;
        their dictionary lookup can test longer prefixes from that position.
        Spaced scripts retain internal apostrophes and decimal separators.
        """
        result = []
        index = 0
        while index < len(text):
            if not _letter_or_number(text[index]):
                index += 1
                continue
            start = index
            index += 1
            while index < len(text):
                char = text[index]
                if _mark(char):
                    index += 1
                    continue
                if self.word_mode == "unspaced":
                    break
                if _letter_or_number(char):
                    index += 1
                    continue
                if char in _APOSTROPHES and index + 1 < len(text) and _letter_or_number(text[index+1]):
                    index += 1
                    continue
                if char in ".," and text[index-1].isdigit() and index + 1 < len(text) and text[index+1].isdigit():
                    index += 1
                    continue
                break
            result.append((start, index))
        return tuple(result)

    def sentence_span(self, text: str, start: int, end: int | None = None) -> tuple[str, int, int]:
        """Visible sentence and a relative span, using the unchanged source."""
        if not text:
            return "", 0, 0
        start = max(0, min(start, len(text)-1))
        end = max(start+1, min(end if end is not None else start+1, len(text)))
        boundaries = {0, len(text)}
        boundaries.update(match.end() for match in re.finditer(r"\n[ \t]*\n", text))
        index = 0
        while index < len(text):
            if text[index] not in self.terminators:
                index += 1
                continue
            first = index
            while index < len(text) and text[index] in self.terminators:
                index += 1
            punctuation = text[first:index]
            while index < len(text) and text[index] in _CLOSERS:
                index += 1
            if set(punctuation) <= {".", "．"}:
                if len(punctuation) > 1:
                    continue
                if punctuation == ".":
                    if index < len(text) and not text[index].isspace():
                        continue
                    token = re.search(r"[\w.]+$", text[:first])
                    word = token.group() if token else ""
                    if word.casefold() in self.abbreviations:
                        continue
                    if len(word) == 1 and word.isupper() and index < len(text):
                        continue
            boundaries.add(index)
        left = max(boundary for boundary in boundaries if boundary <= start)
        right = min(boundary for boundary in boundaries if boundary >= end)
        raw = text[left:right]
        leading = len(raw)-len(raw.lstrip())
        sentence = raw.strip()
        relative_start = max(0, min(len(sentence), start-left-leading))
        relative_end = max(relative_start, min(len(sentence), end-left-leading))
        return sentence, relative_start, relative_end


@lru_cache(maxsize=128)
def get_profile(code: str = "ja") -> LanguageProfile:
    """Unknown language codes get Unicode text handling without model imports."""
    code = str(code).strip().lower()
    base = code.split("-", 1)[0]
    abbreviations = _ABBREVIATIONS
    if base == "tr":
        abbreviations |= frozenset({"doç", "sn", "örn", "vb", "vs"})
    terminators = _TERMINATORS | frozenset(";;") if base == "el" else _TERMINATORS
    return LanguageProfile(code, _NAMES.get(base, code.upper()),
                           "unspaced" if base in {"ja", "zh", "yue"} else "spaced",
                           abbreviations, terminators)
