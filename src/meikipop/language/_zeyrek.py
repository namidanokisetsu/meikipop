"""Zeyrek fixes and ranking adapted from Anki Miner (GPL-3.0).

Source: 0xzerolight/anki_miner, 808b5208bf93d919b3f18ea3aba66db5fd7fd0ea.
See resources/licenses/turkish-analysis.txt and zeyrek.txt.
Fixes: isolated phonetic sets, deterministic root attributes, suffix-internal harmony.
Loaded only on the Turkish lookup worker. Adapted imports; retains morpheme paths.
"""

from __future__ import annotations

import collections
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import zeyrek
import zeyrek.attributes
import zeyrek.morphotactics
from zeyrek import tr as zeyrek_tr
from zeyrek.attributes import PhoneticAttribute, RootAttribute, calculate_phonetic_attributes
from zeyrek.lexicon import RootLexicon
from zeyrek.morphotactics import SurfaceTransition
from zeyrek.rulebasedanalyzer import RuleBasedAnalyzer

from .turkish_analyzer import TrAnalysis, TrMorpheme, front_spelling, tr_casefold, upos

#: Readings of a lowercased word with no capital evidence: ``bize`` → ``Bize``, ``mu`` → ``Mu``.
MARKED_SECONDARY_POS = frozenset({"Prop", "Abbrv"})
#: Closed-class roots win a morpheme-count tie: ``bana`` is ``ben``, not ``banmak`` + optative.
CLOSED_CLASS_POS = frozenset({"Pron", "Postp", "Conj", "Det", "Ques"})
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'"})
_ROOT_ATTRIBUTE_ORDER = {attribute: index for index, attribute in enumerate(RootAttribute)}
#: Fix 4's recompute: zeyrek's undecorated function takes the predecessor's set as is (the cache would hash it).
_phonetics = zeyrek.attributes.calculate_phonetic_attributes.__wrapped__
_VOWELS = zeyrek_tr.vowels_lower_set


def _uncached_phonetics() -> None:
    """Keep cached phonetic sets out of mutable lexicon state."""
    zeyrek.morphotactics.calculate_phonetic_attributes = zeyrek.attributes.calculate_phonetic_attributes.__wrapped__


class _OrderedRootAttributes(set[Any]):
    """Fix 3: a dictionary item's root attributes, iterated in ``RootAttribute`` declaration order."""

    __slots__ = ()

    def __iter__(self) -> Iterator[Any]:
        return iter(sorted(set.__iter__(self), key=_ROOT_ATTRIBUTE_ORDER.__getitem__))


def _ordered_lexicon() -> Any:
    """Fix 3: zeyrek's own lexicon, every item's attributes re-wrapped so their order is the declaration order."""
    lexicon = RootLexicon.default_text_dictionaries()
    for item in lexicon.item_set:
        item.attributes = _OrderedRootAttributes(item.attributes)
    return lexicon


def _generate_surface(transition: Any, phonetic_attributes: set[Any]) -> str:
    """Fix 4: zeyrek 0.1.3 ``generate_surface`` (MIT, Olga Bulat), each token read against the surface so far.

    Zemberek's ``generateSurface`` recomputes the attributes from the partial surface before every token. A partial
    with no vowel carries the predecessor's vowel attributes over, so a vowel token only needs the recompute once
    the partial holds a vowel (parsing takes about 1.5x stock's time; a recompute before every token took 1.9x).
    """
    surface = ""
    for index, token in enumerate(transition.token_list):
        kind = token.type_
        if kind in ("LETTER", "LAST_VOICED", "LAST_NOT_VOICED"):
            surface += token.letter
            continue
        if kind in ("A_VOWEL", "I_VOWEL") and index == 0 and PhoneticAttribute.LastLetterVowel in phonetic_attributes:
            continue
        if surface and (kind in ("APPEND", "DEVOICE_FIRST") or not _VOWELS.isdisjoint(surface)):
            attributes = _phonetics(surface, phonetic_attributes)
        else:
            attributes = phonetic_attributes
        if kind == "A_VOWEL":
            if PhoneticAttribute.LastVowelBack in attributes:
                surface += "a"
            elif PhoneticAttribute.LastVowelFrontal in attributes:
                surface += "e"
            else:
                raise ValueError(f"Cannot generate A form from {attributes}")
        elif kind == "I_VOWEL":
            unrounded = PhoneticAttribute.LastVowelUnrounded in attributes
            if PhoneticAttribute.LastVowelFrontal in attributes:
                surface += "i" if unrounded else "ü"
            elif PhoneticAttribute.LastVowelBack in attributes:
                surface += "ı" if unrounded else "u"
            else:
                raise ValueError(f"Cannot generate I form from {attributes}")
        elif kind == "APPEND":
            if PhoneticAttribute.LastLetterVowel in attributes:
                surface += token.letter
        elif kind == "DEVOICE_FIRST":
            voiceless = PhoneticAttribute.LastLetterVoiceless in attributes
            surface += zeyrek_tr.devoice(token.letter) if voiceless else token.letter
    return surface


class _DeterministicAnalyzer(RuleBasedAnalyzer):
    """Port of zeyrek 0.1.3 ``RuleBasedAnalyzer.search``/``advance`` (MIT, Olga Bulat) where every path owns its set."""

    def search(self, current_paths: list[Any]) -> list[Any]:
        result: list[Any] = []
        while current_paths:
            new_paths: list[Any] = []
            for path in current_paths:
                if (
                    not path.tail
                    and path.is_terminal
                    and PhoneticAttribute.CannotTerminate not in path.phonetic_attributes
                ):
                    result.append(path)
                    continue
                new_paths.extend(self.advance(path))
            current_paths = new_paths
        return result

    def advance(self, path: Any) -> list[Any]:
        new_paths: list[Any] = []
        for transition in path.current_state.outgoing:
            if not path.tail and transition.has_surface_form:
                continue
            surface = _generate_surface(transition, path.phonetic_attributes)
            if not path.tail.startswith(surface) or not transition.can_pass(path):
                continue
            if not transition.has_surface_form:
                new_paths.append(path.copy(SurfaceTransition("", transition), path.phonetic_attributes))
                continue
            if path.tail == surface:
                attributes = set(path.phonetic_attributes)
            else:
                attributes = set(calculate_phonetic_attributes(surface, tuple(path.phonetic_attributes)))
            attributes.discard(PhoneticAttribute.CannotTerminate)
            last_token = transition.last_template_token
            if last_token.type_ == "LAST_VOICED":
                attributes.add(PhoneticAttribute.ExpectsConsonant)
            elif last_token.type_ == "LAST_NOT_VOICED":
                attributes.add(PhoneticAttribute.ExpectsVowel)
                attributes.add(PhoneticAttribute.CannotTerminate)
            new_paths.append(path.copy(SurfaceTransition(surface, transition), attributes))
        return new_paths


def _secondary(item: Any) -> str:
    value = item.secondary_pos.value
    return "" if value in (None, "Unk") else str(value)


class TurkishAnalyzer:
    """``analyse(word)``: every distinct reading of one word, the card-front choice first."""

    def __init__(self, *, rebuild_ranking=False) -> None:
        _uncached_phonetics()
        self._zeyrek = zeyrek.MorphAnalyzer(lexicon=_ordered_lexicon())
        self._zeyrek.analyzer = _DeterministicAnalyzer(self._zeyrek.morphotactics)
        self._family = self._family_counts() if rebuild_ranking else self._load_family_counts()

    def _load_family_counts(self):
        from .turkish_ranking import load_counts
        return collections.Counter(load_counts(self._family_counts))

    def _family_counts(self) -> collections.Counter[str]:
        """How many of zeyrek's own ``first-10K`` surfaces have a reading with each dictionary item."""
        counts: collections.Counter[str] = collections.Counter()
        path = Path(zeyrek.__file__).parent / "resources" / "tr" / "first-10K"
        for line in path.read_text(encoding="utf-8").splitlines():
            word = line.strip()
            if word[:1].isalpha():
                counts.update({reading.dict_item.id_ for reading in self._zeyrek._parse(word)})
        return counts

    def _ranked(self, readings: list[Any]) -> list[Any]:
        """Rank readings independently of hash seed and parse history."""
        content = {
            tr_casefold(front_spelling(r.dict_item.lemma, ""))
            for r in readings
            if r.dict_item.primary_pos.value != "Interj"
        }

        def key(reading: Any) -> tuple[bool, bool, int, bool, int, int, str, str]:
            item = reading.dict_item
            primary = item.primary_pos.value
            shadowed = primary == "Interj" and tr_casefold(front_spelling(item.lemma, "")) in content
            return (
                not (primary == "Ques" and not reading.ending),
                _secondary(item) in MARKED_SECONDARY_POS or shadowed,
                len(reading.morphemes),
                primary not in CLOSED_CLASS_POS,
                -self._family[item.id_],
                -len(reading.stem),
                item.lemma,
                item.id_,
            )

        return sorted(readings, key=key)

    def analyse(self, word: str) -> list[TrAnalysis]:
        """One ``TrAnalysis`` per distinct lemma and POS, in ``_ranked`` order; a verb's flags cover all its readings."""
        out: dict[tuple[str, str, str], TrAnalysis] = {}
        for reading in self._ranked(self._zeyrek._parse(word.translate(_APOSTROPHES))):
            item = reading.dict_item
            secondary = _secondary(item)
            pos1 = upos(item.primary_pos.value, secondary)
            lemma = front_spelling(item.lemma, word)
            key = (lemma if pos1 == "PROPN" else tr_casefold(lemma), pos1, secondary)
            morphemes = {morpheme.id_ for morpheme, _surface in reading.morphemes} if pos1 == "VERB" else set()
            seen = out.get(key, TrAnalysis(*key))
            path = tuple(TrMorpheme(m.id_, surface, m.name, m.derivational)
                         for m, surface in reading.morphemes)
            out[key] = TrAnalysis(
                *key, imperative=seen.imperative or "Imp" in morphemes, aorist=seen.aorist or "Aor" in morphemes,
                paths=seen.paths if path in seen.paths else (*seen.paths, path),
            )
        return list(out.values())
