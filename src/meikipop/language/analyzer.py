from dataclasses import dataclass
import re
import unicodedata
from typing import Protocol


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(str.maketrans("Iİ", "ıi")).lower()


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    lemma: str
    pos: str | None = None


class Analyzer(Protocol):
    identity: str

    def analyze(self, text: str) -> tuple[Token, ...]: ...


class ExactAnalyzer:
    identity = "tr:exact:1"

    def analyze(self, text):
        # Combining marks stay attached; apostrophes in proper names stay intact.
        return tuple(Token(m.start(), m.end(), m.group()) for m in
                     re.finditer(r"[^\W_][\w\u0300-\u036f]*(?:['’][\w\u0300-\u036f]+)*", text))
