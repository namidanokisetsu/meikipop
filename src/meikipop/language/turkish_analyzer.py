"""Offline Turkish candidates adapted from Anki Miner; see resources/licenses."""
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import re
import unicodedata
import threading

from .analyzer import normalize

ZEYREK_VERSION = "0.1.3"
MAX_WORD_LENGTH = 64
_CIRCUMFLEXES = "âîûÂÎÛ"
_CIRCUMFLEX_FOLD = str.maketrans(_CIRCUMFLEXES, "aiuAIU")
_APOSTROPHE = re.compile("['’ʼ]")
_TOKENS = re.compile(r"[^\W\d_][\w\u0300-\u036f]*(?:['’ʼ][\w\u0300-\u036f]+)?|\d+(?:[.,]\d+)*(?:['’ʼ][^\W\d_]+)?|[^\s\w]")
_OPENERS = frozenset("-‐‑‒–—―\"'“”„‟«»‘’‚‛‹›([{")
_SENTENCE_ENDS = frozenset(".!?…:")
_BARE_QUESTION = frozenset({"mi", "mı", "mu", "mü"})
_POS = {"Noun": "NOUN", "Verb": "VERB", "Adj": "ADJ", "Adv": "ADV", "Pron": "PRON",
        "Postp": "ADP", "Conj": "CCONJ", "Det": "DET", "Num": "NUM", "Interj": "INTJ",
        "Ques": "PART", "Dup": "X", "Punc": "PUNCT"}
_engine_future = None
_engine_guard = threading.Lock()
_parse_guard = threading.Lock()


def warmup():
    """Prepare one shared engine off the UI thread when Turkish becomes active."""
    global _engine_future
    with _engine_guard:
        if _engine_future is None:
            _engine_future = Future()
            threading.Thread(target=_load_engine, args=(_engine_future,), name="turkish-setup", daemon=True).start()
        return _engine_future


def _load_engine(future):
    try:
        from ._zeyrek import TurkishAnalyzer as Engine
        future.set_result(Engine())
    except Exception as error:
        future.set_exception(error)


def available():
    try:
        return version("zeyrek") == ZEYREK_VERSION
    except PackageNotFoundError:
        return False


def tr_casefold(text):
    return normalize(text).casefold()


def front_spelling(lemma, surface):
    return lemma if any(c in surface for c in _CIRCUMFLEXES) else lemma.translate(_CIRCUMFLEX_FOLD)


def upos(primary, secondary):
    return "PROPN" if secondary == "Prop" else "X" if secondary == "Abbrv" else _POS.get(primary, "X")


@dataclass(frozen=True)
class TrMorpheme:
    id: str
    surface: str
    name: str
    derivational: bool = False


@dataclass(frozen=True)
class TrAnalysis:
    lemma: str
    pos1: str
    pos2: str = ""
    imperative: bool = False
    aorist: bool = False
    paths: tuple[tuple[TrMorpheme, ...], ...] = ()


_LABELS = {"A1sg": "1sg", "A2sg": "2sg", "A3sg": "3sg", "A1pl": "1pl", "A2pl": "2pl",
           "A3pl": "plural", "P1sg": "my", "P2sg": "your", "P3sg": "3sg possessive",
           "P1pl": "our", "P2pl": "your (plural)", "P3pl": "3pl possessive",
           "Ness": "noun derivation", "Past": "past", "Narr": "reported past", "Fut": "future",
           "Prog1": "progressive", "Prog2": "progressive", "Pres": "present", "Cond": "conditional",
           "Imp": "imperative", "Neces": "necessitative", "Zero": "conversion",
           "Inf1": "infinitive", "Inf2": "verbal noun", "Inf3": "verbal noun"}
_HIDDEN = frozenset({"Root", "Noun", "Adj", "Verb", "Pron", "Adv", "Conj", "Punc", "Postp",
                     "Det", "Num", "Dup", "Interj", "Nom", "Pnon"})


def grammar_labels(readings):
    alternatives = []
    for reading in readings:
        for path in reading.paths:
            labels = []
            for step in path[1:]:
                if step.id in _HIDDEN or step.id == "A3sg" and not step.surface:
                    continue
                label = _LABELS.get(step.id, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", step.name).lower())
                labels.append(f"-{step.surface} ({label})" if step.surface else label)
            if labels:
                alternatives.append(" · ".join(labels))
    return (" OR ".join(dict.fromkeys(alternatives)),) if alternatives else ("base form",)


def _starts_sentence(surfaces, index):
    for before in reversed(surfaces[:index]):
        if before not in _OPENERS:
            return before in _SENTENCE_ENDS
    return True


def _pick(readings, index, surfaces, previous):
    """Anki Miner's name, imperative and aorist context preferences."""
    own, surface = readings[index], surfaces[index]
    if surface[0].isupper() and not surface.isupper() and not _starts_sentence(surfaces, index):
        for reading in own:
            if reading.pos2 == "Prop" and tr_casefold(reading.lemma) == tr_casefold(surface):
                return reading
    following = surfaces[index + 1] if index + 1 < len(surfaces) else ""
    if following == "!":
        if own[0].lemma not in {"var", "yok"} and not (previous and previous.pos1 == "DET"):
            return next((r for r in own if r.imperative), own[0])
    elif following and readings[index + 1] and readings[index + 1][0].pos1 == "PART":
        aorist = next((r for r in own if r.aorist), own[0])
        determiner = (previous is not None and previous.pos1 == "DET"
                      and all(r.pos1 != "PRON" for r in readings[index - 1]))
        plural = aorist.lemma in (own[0].lemma + "lamak", own[0].lemma + "lemek")
        if not (tr_casefold(following) in _BARE_QUESTION and (determiner or plural)):
            return aorist
    return own[0]


class TurkishAnalyzer:
    def __init__(self):
        if not available():
            raise RuntimeError(f"Turkish analysis requires zeyrek=={ZEYREK_VERSION}")
        self.engine = None
        self._words = OrderedDict()

    def _readings(self, surface):
        if not surface[0].isalpha() or len(surface) > MAX_WORD_LENGTH:
            return ()
        head = _APOSTROPHE.split(surface, maxsplit=1)[0]
        if surface not in self._words:
            if self.engine is None:
                self.engine = warmup().result()
            with _parse_guard:
                readings = tuple(self.engine.analyse(unicodedata.normalize("NFC", surface)))
            if head != surface and head[0].isupper():
                readings = tuple(r for r in readings if r.pos1 == "PROPN" and
                                 tr_casefold(r.lemma) == tr_casefold(head)) or (TrAnalysis(head, "PROPN", "Prop"),)
            self._words[surface] = readings
        self._words.move_to_end(surface)
        if len(self._words) > 4096:
            self._words.popitem(last=False)
        return self._words[surface]

    def candidates(self, text, start, end):
        """Keep the original selection and every ranked reading of that whole word."""
        spans = list(_TOKENS.finditer(text))
        target = next((i for i, m in enumerate(spans) if m.span() == (start, end)), None)
        if target is None:
            return ()
        # Context preferences need nearby words, not an entire pasted document.
        lower = max(0, target - 32)
        spans = spans[lower:target + 3]
        target -= lower
        surfaces = [m.group() for m in spans]
        readings = [self._readings(surface) for surface in surfaces]
        previous = None
        for i in range(target + 1):
            pick = _pick(readings, i, surfaces, previous) if readings[i] else None
            if i == target:
                return (pick, *(r for r in readings[i] if r != pick)) if pick else ()
            previous = pick
