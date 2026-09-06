"""Context analysis and whole-token/phrase lookup for clipboard text."""
from dataclasses import dataclass
from functools import lru_cache
import unicodedata

from meikipop.language.analyzer import ExactAnalyzer, Token, normalize
from meikipop.language.turkish_recovery import (
    MAX_ANALYSES, MAX_SUGGESTIONS, diacritic_candidates, edit_candidates,
    nominal_forms, nominal_stems,
)


@dataclass(frozen=True)
class Match:
    entry_id: str
    start: int
    end: int
    candidate: str
    route: str


@dataclass(frozen=True)
class Suggestion:
    entry_id: str
    headword: str
    start: int
    end: int
    candidate: str
    route: str
    cost: int


@dataclass(frozen=True)
class TextResult:
    text: str
    tokens: tuple[Token, ...]
    target: int | None
    entries: tuple
    status: str
    matches: tuple[Match, ...] = ()
    suggestions: tuple[Suggestion, ...] = ()
    attempts: tuple = ()
    wordnet: tuple = ()
    wordnet_status: str = ""


class TurkishLookup:
    def __init__(self, store, analyzer="stanza", model_dir=None):
        self.store = store
        self.analyzer = ExactAnalyzer()
        self.status = "Exact lookup (no lemmatization)"
        if analyzer == "stanza":
            try:
                from meikipop.language.stanza_analyzer import StanzaAnalyzer
                self.analyzer = StanzaAnalyzer(model_dir)
                self.status = "Stanza 1.14.0 · Turkish IMST"
            except Exception:
                self.status = "Exact fallback — Stanza unavailable. Run: meikipop setup-turkish-model"

    @lru_cache(maxsize=32)
    def analyze(self, text):
        return self.analyzer.analyze(text)

    def lookup(self, text, target=None, debug=False):
        try:
            tokens = self.analyze(text)
        except Exception:
            self.analyzer = ExactAnalyzer()
            self.analyze.cache_clear()
            self.status = "Exact fallback — Stanza analysis failed; restart after model setup"
            tokens = self.analyze(text)
        entries, matches, attempts = [], [], []
        suggestions = ()

        def query(candidate, pos, start, end, route):
            found = self.store.lookup(candidate, pos)
            if debug:
                attempts.append(dict(candidate=candidate, pos=pos, start=start, end=end,
                                     route=route, entry_ids=[e["id"] for e in found]))
            return found

        def collect(candidate, pos, start, end, route):
            found = query(candidate, pos, start, end, route)
            entries.extend(found)
            matches.extend(Match(e["id"], start, end, candidate, route) for e in found)

        if target is None:
            collect(text.strip(), None, len(text) - len(text.lstrip()), len(text.rstrip()), "surface")
            if not entries and tokens:
                target = 0
        if target is not None and 0 <= target < len(tokens):
            token = tokens[target]
            # Bounded contiguous phrases; only verb lemmas are substituted.
            phrases = []
            for length in range(min(5, len(tokens)), 1, -1):
                for start in range(max(0, target - length + 1), min(target + 1, len(tokens) - length + 1)):
                    window = tokens[start:start + length]
                    if any(not text[a.end:b.start].isspace() for a,b in zip(window, window[1:])):
                        continue
                    span = (window[0].start, window[-1].end)
                    phrases.append((text[span[0]:span[1]], *span, "phrase_surface"))
                    for i, word in enumerate(window):
                        if word.pos in ("VERB", "AUX"):
                            parts = [text[t.start:t.end] for t in window]
                            parts[i] = word.lemma
                            phrases.append((" ".join(parts), *span, "phrase_lemma"))
                            # Idioms often lack source POS tags. Reach their literal
                            # headwords using the POS-confirmed verb's infinitive.
                            for entry in query(word.lemma, word.pos, word.start, word.end, "verb_alias")[:4]:
                                if any(s["pos"] == "VERB" for s in entry["senses"]):
                                    parts[i] = entry["headword"]
                                    phrases.append((" ".join(parts), *span, "phrase_verb_alias"))
            for phrase, start, end, route in dict.fromkeys(phrases):
                collect(phrase, "VERB", start, end, route)
            collect(text[token.start:token.end], token.pos, token.start, token.end, "surface")
            collect(token.lemma, token.pos, token.start, token.end, "lemma")
            if not entries and not isinstance(self.analyzer, ExactAnalyzer):
                self._retry_case(text, token, collect)
            if not entries:
                suggestions = self._suggest(text, token, query)
        unique = {e["id"]: e for e in reversed(entries)}
        ordered = tuple(unique[eid] for eid in dict.fromkeys(e["id"] for e in entries))
        return TextResult(text, tokens, target, ordered, self.status, tuple(dict.fromkeys(matches)),
                          suggestions, tuple(attempts))

    def _suggest(self, text, token, query):
        surface = normalize(text[token.start:token.end])
        variants = diacritic_candidates(surface)
        found = {}

        def offer(candidate, pos, route, cost, spelling=None, nominal=False):
            for entry in query(candidate, pos, token.start, token.end, route):
                if nominal and not any(s["pos"] in ("NOUN", "ADJ", "PROPN") for s in entry["senses"]):
                    continue
                suggestion = Suggestion(entry["id"], entry["headword"], token.start, token.end,
                                        spelling or candidate, route, cost)
                key = normalize(entry["headword"])
                if key not in found or cost < found[key].cost:
                    found[key] = suggestion

        # Validate a proposed nominal stem by generating a supported inflected form.
        spellings = dict(variants)
        for stem in nominal_stems(surface):
            for candidate, _ in diacritic_candidates(stem):
                for form in nominal_forms(candidate):
                    if form in spellings:
                        cost = spellings[form]
                        offer(candidate, None, "nominal" if cost == 0 else "diacritic_nominal",
                              cost, form, nominal=True)
                        break
        for candidate, cost in variants:
            if cost:
                offer(candidate, None, "diacritic", cost)
        if not isinstance(self.analyzer, ExactAnalyzer):
            for candidate, cost in variants[1:MAX_ANALYSES + 1]:
                context = text[:token.start] + candidate + text[token.end:]
                try:
                    words = self.analyze(context)
                except Exception:
                    continue
                for word in words:
                    if (word.start, word.end) == (token.start, token.start + len(candidate)):
                        offer(word.lemma, word.pos, "diacritic_lemma", cost, candidate)
                        break
        if not found:
            for candidate in edit_candidates(surface):
                offer(candidate, None, "edit", 4)
        return tuple(sorted(found.values(), key=lambda s: (s.cost, s.headword))[:MAX_SUGGESTIONS])

    def _retry_case(self, text, token, collect):
        # Boundary mapping also handles Unicode lowercase expansions outside Turkish.
        parts, boundaries, offset = [], {0: 0}, 0
        start = 0
        for end in range(1, len(text) + 1):
            if end < len(text) and unicodedata.combining(text[end]):
                continue
            part = normalize(text[start:end])
            parts.append(part)
            offset += len(part)
            boundaries[offset] = end
            start = end
        lowered = "".join(parts)
        if lowered == text:
            return
        try:
            retried = self.analyze(lowered)
        except Exception:
            return
        for word in retried:
            if (boundaries.get(word.start), boundaries.get(word.end)) == (token.start, token.end):
                collect(word.lemma, word.pos, token.start, token.end, "casing_lemma")
                break
