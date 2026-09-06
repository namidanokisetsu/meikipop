"""Bounded candidate generation, separate from canonical dictionary keys."""
from heapq import heappop, heappush

from .analyzer import normalize

MAX_LENGTH = 32
MAX_VARIANTS = 64
MAX_EDITS = 256
MAX_ANALYSES = 8
MAX_SUGGESTIONS = 5
PAIRS = dict(zip("cçgğoösşuüiı", "çcğgöoşsüuıi"))
ALPHABET = "abcçdefgğhıijklmnoöprsştuüvyz"


def diacritic_candidates(text):
    text = normalize(text)
    if not 2 <= len(text) <= MAX_LENGTH or not text.isalpha():
        return ()
    # Each state changes positions only left-to-right; even queued work is capped.
    queue, result, generated = [(0, text, 0)], [], 1
    while queue and len(result) < MAX_VARIANTS:
        cost, candidate, start = heappop(queue)
        result.append((candidate, cost))
        if cost == 3:
            continue
        for i in range(start, len(text)):
            if generated >= MAX_VARIANTS * 4:
                break
            if text[i] in PAIRS:
                changed = candidate[:i] + PAIRS[text[i]] + candidate[i + 1:]
                heappush(queue, (cost + 1, changed, i + 1))
                generated += 1
    return tuple(result)


def edit_candidates(text):
    text = normalize(text)
    if not 2 <= len(text) <= MAX_LENGTH or not text.isalpha():
        return ()
    result = dict.fromkeys(text[:i] + text[i + 1:] for i in range(len(text)))
    result.update(dict.fromkeys(text[:i] + text[i + 1] + text[i] + text[i + 2:]
                               for i in range(len(text) - 1)))
    for char in ALPHABET:
        for i in range(len(text) + 1):
            for candidate in (text[:i] + char + text[i:], text[:i] + char + text[i + 1:]):
                if candidate != text:
                    result[candidate] = None
                if len(result) >= MAX_EDITS:
                    return tuple(result)
    return tuple(result)


def nominal_forms(stem):
    """A conservative single-suffix subset, used to validate guesses by generation."""
    vowel = next((c for c in reversed(stem) if c in "aeıioöuü"), None)
    if vowel is None:
        return ()
    low = "a" if vowel in "aıou" else "e"
    high = dict(zip("aıeiouöü", "ııiiuuüü"))[vowel]
    voiced = stem[:-1] + {"p": "b", "ç": "c", "t": "d", "k": "ğ"}.get(stem[-1], stem[-1])
    consonant = "t" if stem[-1] in "fstkçşhp" else "d"
    if stem[-1] in "aeıioöuü":
        accusative, dative, genitive = stem + "y" + high, stem + "y" + low, stem + "n" + high + "n"
    else:
        accusative, dative, genitive = voiced + high, voiced + low, voiced + high + "n"
    return (stem + "l" + low + "r", accusative, dative, genitive,
            stem + consonant + low, stem + consonant + low + "n")


def nominal_stems(surface):
    surface = normalize(surface)
    if not 3 <= len(surface) <= MAX_LENGTH or not surface.isalpha():
        return ()
    result = []
    for count in (1, 2, 3):
        stem = surface[:-count]
        if len(stem) < 2:
            continue
        result.append(stem)
        for ending in {"b": "p", "c": "ç", "d": "t", "ğ": "k", "g": "k"}.get(stem[-1], ""):
            result.append(stem[:-1] + ending)
    return tuple(dict.fromkeys(result))
