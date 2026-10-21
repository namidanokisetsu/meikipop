"""Indexed local search with optional offline lemma fallback after dictionary forms."""
from collections import OrderedDict
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import re

from .library import Library, language_code
from .translation import LocalTranslator

JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
TURKISH = re.compile(r"[ğışĞİŞ]")


@dataclass(frozen=True)
class SearchResult:
    text: str
    source: str
    target: str
    entries: tuple = ()
    suggestions: tuple = ()
    translation: str = ""
    message: str = ""
    kanji: tuple = ()
    translation_model: str = ""
    matched_length: int = 0
    analyses: tuple = ()


class SearchEngine:
    def __init__(self, directory=None, translator=None):
        self.library = Library(directory)
        self.translator = translator or LocalTranslator()
        self.cache = OrderedDict()
        self.deconjugator = None
        self._analyzer = None
        self._turkish_analyzer = None
        self._analysis_errors = {}
        self._analyses = ()

    def close(self):
        self.library.close()
        self._analyzer = None
        self._turkish_analyzer = None

    def refresh(self):
        self.library.refresh()
        self.cache.clear()
        self._analysis_errors.clear()
        if self._analyzer is not None:
            from meikipop.language.morphology import model_available
            if not model_available(self._analyzer[0]):
                self._analyzer = None

    def refresh_if_changed(self):
        if self.library.refresh_if_changed():
            self.cache.clear()
            self._analysis_errors.clear()

    def detect(self, text, foreign="ja", languages=None):
        if re.search(r"[\u3040-\u30ff\uff66-\uff9f]", text):
            return "ja"
        languages = self.languages() if languages is None else languages
        if JAPANESE.search(text):
            return "zh" if foreign.startswith("zh") or "ja" not in languages and "zh" in languages else "ja"
        for pattern, codes in ((r"[\uac00-\ud7af]", ("ko",)),
                               (r"[\u0400-\u04ff]", ("ru", "uk", "bg")),
                               (r"[\u0600-\u06ff]", ("ar", "fa", "ur")),
                               (r"[\u0370-\u03ff]", ("el",)),
                               (r"[\u0590-\u05ff]", ("he", "yi"))):
            if re.search(pattern, text):
                return foreign if foreign in codes else next((c for c in codes if c in languages), codes[0])
        words = re.findall(r"[^\W\d_]+", text, re.UNICODE)[:12]
        if words:
            scores = {language: sum(bool(self.library.lookup(word, language, limit=1, tolerant=False)) for word in words)
                      for language in languages if language != "en"}
            if scores:
                best = max(scores, key=lambda c: (scores[c], c == foreign))
                if scores[best] >= max(1, (len(words) + 1) // 2):
                    return best
            # English headwords such as 'cat' must beat Turkish accent guesses
            # ('çat'). Exact dictionary evidence above still wins ambiguous cases.
            # Turkish example sentences are also indexed; incidental mentions
            # must not outrank accent recovery as evidence of English input.
            if self.library.reverse(text, foreign, limit=1, exact_gloss=foreign == "tr"):
                return "en"
            if "tr" in languages:
                hits = sum(bool(self.library.lookup(word, "tr", limit=1)) for word in words)
                if hits >= max(1, (len(words) + 1) // 2):
                    return "tr"
        if TURKISH.search(text):
            return "tr"
        return "en"

    def languages(self):
        return tuple(dict.fromkeys(meta["language"] for _, meta, _ in self.library.packs if meta["enabled"]))

    def search(self, text, source="auto", foreign="ja", translate=False, target=None, pair=None, translation_settings=None,
               morphology=False, context=None, translation_progress=None, translation_state=None, cancelled=None, request_id=0,
               exact_only=False, max_lookup_length=25):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("Translation cancelled.")
        self.refresh_if_changed()
        text = text.strip()
        if len(text) > 2000:
            raise ValueError("Enter at most 2,000 characters.")
        if source != "auto":
            source = language_code(source)
        foreign = language_code(foreign)
        if isinstance(self.translator, LocalTranslator):
            self.translator.settings_override = translation_settings
        translator_key = getattr(self.translator, "cache_key", lambda: None)() if translate else None
        requested_target = language_code(target) if target else None
        pair = tuple(language_code(code) for code in pair) if pair else None
        cache_key = (self.library.revision, text, source, foreign, translate, translator_key, requested_target, pair,
                     morphology, context if morphology else None, exact_only, max_lookup_length)
        if cache_key in self.cache:
            self.cache.move_to_end(cache_key)
            return self.cache[cache_key]
        automatic_source = source == "auto"
        exact_entries = ()
        if exact_only and not translate:
            # Phrase headwords establish their language even without separate word entries.
            candidates = dict.fromkeys((foreign, *(pair or ("en",)))) if automatic_source else (source,)
            for language in candidates:
                exact_entries = self.library.lookup(text, language, tolerant=False,
                                                   target_language=foreign if language != foreign else None)
                if exact_entries:
                    source = language
                    break
        if source == "auto":
            source = self.detect(text, foreign, languages=None if translate and requested_target else pair)
        if pair:
            if not translate or automatic_source and not requested_target:
                source = source if source in pair else pair[0]
            target = requested_target if translate and requested_target else pair[0] if source == pair[1] else pair[1]
            foreign = pair[0]
        else:
            target = requested_target if translate and requested_target else foreign if source == "en" else "en"
        if translate and target == source:
            if requested_target and not automatic_source:
                raise ValueError("Choose different source and target languages.")
            target = next((code for code in reversed(pair or (foreign, "en")) if code != source), "en")
        entries, suggestions, message = (), (), ""
        self._analyses = ()
        matched_length = 0
        if text and not translate:
            if exact_only:
                entries = exact_entries
                matched_length = len(text) if entries else 0
            elif (source == "en" and foreign != "en") or pair and source == pair[1]:
                dictionary_language = foreign if pair else target
                entries = self.library.lookup(text, source, target_language=dictionary_language)
                if not entries:
                    entries = self.library.reverse(text, dictionary_language,
                                                   exact_gloss=dictionary_language == "tr")
                if entries:
                    matched_length = len(text)
                if not entries and morphology and foreign != "ja":
                    entries = self._lemma_lookup(text, foreign, context)
                    if entries or self._analyses:
                        source, target = foreign, source
                        matched_length = len(text)
                if not entries:
                    suggestions = self.library.suggest(text, dictionary_language)
            else:
                if source == "ja":
                    entries = self._japanese(text, max_lookup_length)
                    matched_length = self._matched_length
                else:
                    from meikipop.language.profiles import get_profile
                    entries = self.library.lookup(text, source)
                    if not entries and source == "fa":
                        entries = self._persian_lookup(text)
                    matched_length = len(text) if entries else 0
                    if not entries and get_profile(source).word_mode == "unspaced":
                        entries, matched_length = self._prefix_lookup(text, source)
                if not entries and morphology and source != "ja":
                    entries = self._lemma_lookup(text, source, context)
                    matched_length = len(text) if entries else 0
                if not entries:
                    suggestions = self.library.suggest(text, source)
            if not entries and not suggestions:
                message = "No entry found."
        translation = ""
        if translate and text:
            try:
                options = {}
                if isinstance(self.translator, LocalTranslator):
                    options = dict(on_text=(lambda value: translation_progress(SearchResult(
                        text, source, target, translation=value))) if translation_progress else None,
                                   on_state=translation_state, cancelled=cancelled, request_id=request_id)
                translation = self.translator.translate(text, source, target, **options)
            except (ImportError, RuntimeError, ValueError) as error:
                message = str(error)
        kanji = self.library.kanji_info(entries[0].term if entries else text) if not translate and (source == "ja" or target == "ja") else ()
        model = getattr(self.translator, "last_model", "") if translation else ""
        analyses = self._analyses if not entries else ()
        if analyses:
            message = "No dictionary entry."
            alternatives = (entry.term for lemma in dict.fromkeys(reading.lemma for reading in analyses)
                            for entry in self.library.lookup(lemma, "tr"))
            suggestions = tuple(dict.fromkeys((*suggestions, *alternatives)))[:8]
        result = SearchResult(text, source, target, entries, suggestions, translation, message, kanji, model, matched_length,
                              analyses=analyses)
        # A missing or starting local server must be retryable on the same text.
        if (not translate or translation) and not (cancelled is not None and cancelled.is_set()):
            self.cache[cache_key] = result
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return result

    def _lemma_lookup(self, text, language, context):
        if not self.library._active(language):
            return ()
        if language == "tr":
            return self._turkish_lookup(text, context)
        if language in self._analysis_errors:
            raise RuntimeError(self._analysis_errors[language])
        try:
            from meikipop.language.stanza_analyzer import StanzaAnalyzer, default_model_dir
            if self._analyzer is None or self._analyzer[0] != language:
                if not (default_model_dir(language) / "resources.json").is_file():
                    raise FileNotFoundError("models not installed")
                self._analyzer = (language, StanzaAnalyzer(language=language))
            original, start, end = context or (text, 0, len(text))
            tokens = [token for token in self._analyzer[1].analyze(original)
                      if start <= token.start < token.end <= end]
        except Exception as error:
            import logging
            logging.getLogger(__name__).warning("Base-form lookup failed for %s: %s", language, error)
            message = f"Base-form model unavailable for {language}. Use Install model in Settings → Dictionaries."
            self._analysis_errors[language] = message
            raise RuntimeError(message) from error
        if not tokens or tokens[0].start != start or tokens[-1].end != end:
            return ()
        candidate = original[start:end]
        for token in reversed(tokens):
            if token.lemma and token.lemma != "_":
                lemma = token.lemma
                candidate = candidate[:token.start-start] + lemma + candidate[token.end-start:]
        if candidate == text:
            return ()
        entries = self.library.lookup(candidate, language, tolerant=False)
        return tuple(replace(entry, route="lemma", inflection=("lemma",))
                     for entry in entries)

    def _turkish_lookup(self, text, context):
        from meikipop.language.turkish_analyzer import TurkishAnalyzer, grammar_labels
        if self._turkish_analyzer is None:
            self._turkish_analyzer = TurkishAnalyzer()
        original, start, end = context or (text, 0, len(text))
        if original[start:end] != text:
            return ()
        entries, candidates = {}, {}
        self._analyses = self._turkish_analyzer.candidates(original, start, end)
        for reading in self._analyses:
            if reading.pos1 != "X":
                candidates.setdefault(reading.lemma, []).append(reading)
        for lemma, readings in candidates.items():
            found = self.library.lookup(lemma, "tr", tolerant=False)
            direct = tuple(entry for entry in found if entry.route == "exact")
            for entry in direct or found:
                previous = entries.get(entry.id, entry)
                analyses = tuple(dict.fromkeys((*previous.morphology, *readings)))
                labels = grammar_labels(analyses)
                entries[entry.id] = replace(previous, route="morphology", morphology=analyses,
                                            inflection=(*labels, *entry.inflection))
        return tuple(entries.values())[:60]

    def _persian_lookup(self, text):
        unified = text.translate(str.maketrans("كي", "کی"))
        variants = dict.fromkeys((unified, text.replace("\u200c", ""), unified.replace("\u200c", "")))
        for candidate in variants:
            if candidate == text:
                continue
            entries = self.library.lookup(candidate, "fa", tolerant=False)
            if entries:
                return tuple(replace(entry, route="form spelling" if entry.route == "form" else "spelling")
                             for entry in entries)
        return ()

    def _prefix_lookup(self, text, language):
        from meikipop.language.profiles import get_profile
        # Only complete source clusters may end a prefix; Thai tone marks stay attached.
        lengths = [end for _, end in get_profile(language).word_spans(text) if end < len(text) and end <= 25]
        for length in reversed(lengths):
            entries = self.library.lookup(text[:length], language, tolerant=False)
            if entries:
                return entries, length
        return (), 0

    def _japanese(self, text, max_lookup_length=25):
        self._matched_length = 0
        from .deconjugator import Deconjugator
        from .kanji import kanji_characters
        from .metadata import harmonic_rank
        if self.deconjugator is None:
            rules = Path(__file__).parents[1] / "scripts/deconjugator.json"
            self.deconjugator = Deconjugator(json.loads(rules.read_text(encoding="utf-8")))
        def compatible(tags, rules):
            if not tags:
                return False
            tag = tags[-1]
            # The bundled rules emit JMdict subclasses (v5m, vs-i), whereas
            # Yomitan dictionaries normally store conjugation families (v5, vs).
            # Intermediate stems are not dictionary forms, even if a homographic
            # noun happens to exist in the dictionary.
            if tag.startswith("stem-") or tag == "topic-condition":
                return False
            if tag in ("exp", "uninflectable"):
                return not rules or tag in rules
            family = "v5" if tag.startswith("v5") else "vs" if tag.startswith("vs") else tag
            return tag in rules or family in rules or (
                family == "v1" and "v1-s" in rules or family == "adj-i" and "adj-ix" in rules)
        lookups = {}

        def lookup(surface):
            if surface not in lookups:
                lookups[surface] = self.library.lookup(surface, "ja", limit=None)
            return lookups[surface]

        # Full dictionary matches are independent of the prefix scan budget.
        lengths = ((len(text),) if len(text) > max_lookup_length and lookup(text)
                   else range(min(max_lookup_length, len(text)), 0, -1))
        for length in lengths:
            prefix = text[:length]
            results = [(entry, len(entry.inflection)) for entry in lookup(prefix)]
            for form in sorted(self.deconjugator.deconjugate(prefix), key=lambda f: (len(f.process), f.text, f.tags)):
                if form.text == prefix:
                    continue
                for entry in lookup(form.text):
                    if not compatible(form.tags, entry.rules):
                        continue
                    labels = {"teiru": "progressive", "teru (teiru)": "progressive",
                              "teoru": "progressive", "toru (teoru)": "progressive"}
                    process = tuple(dict.fromkeys(labels.get(step, step) for step in reversed(form.process)
                                                  if step and not step.startswith("(")))
                    results.append((replace(entry, route="inflected", inflection=process), len(form.process)))
            if results:
                self._matched_length = length
                unique = {}
                for entry, cost in results:
                    if entry.id not in unique or cost < unique[entry.id][1]:
                        unique[entry.id] = (entry, cost)
                groups = OrderedDict()
                for entry, cost in unique.values():
                    groups.setdefault((entry.term, entry.reading), []).append((entry, cost))
                kana_query = not kanji_characters(prefix, 1)

                def priority(group):
                    entries = groups[group]
                    cost = min(cost for _, cost in entries)
                    score = -cost
                    rank = harmonic_rank(f for entry, _ in entries for f in entry.frequencies)
                    if rank is not None and rank < 999_999:
                        score += 10 * (1 - math.log(max(1, rank)) / math.log(999_999))
                    if kana_query and not cost and not kanji_characters(group[0], 1):
                        score += 3
                    return score

                # Limit lexical groups after ranking, keeping their senses and sources together.
                return tuple(entry for group in sorted(groups, key=priority, reverse=True)[:60]
                             for entry, _ in groups[group])
        return ()
