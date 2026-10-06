"""Indexed local search with optional offline lemma fallback after dictionary forms."""
from collections import OrderedDict
from dataclasses import dataclass, replace
import json
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


class SearchEngine:
    def __init__(self, directory=None, translator=None):
        self.library = Library(directory)
        self.translator = translator or LocalTranslator()
        self.cache = OrderedDict()
        self.deconjugator = None
        self._analyzer = None
        self._analysis_errors = {}

    def close(self):
        self.library.close()
        self._analyzer = None

    def refresh(self):
        self.library.refresh()
        self.cache.clear()
        self._analysis_errors.clear()

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
                               (r"[\u0590-\u05ff]", ("he",))):
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
               morphology=False, context=None, translation_progress=None, translation_state=None, cancelled=None, request_id=0):
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
                     morphology, context if morphology else None)
        if cache_key in self.cache:
            self.cache.move_to_end(cache_key)
            return self.cache[cache_key]
        automatic_source = source == "auto"
        source = self.detect(text, foreign, languages=None if translate and requested_target else pair) if automatic_source else source
        if pair:
            if not translate or automatic_source and not requested_target:
                source = source if source in pair else pair[0]
            target = requested_target if translate and requested_target else pair[0] if source == pair[1] else pair[1]
            foreign = pair[0]
        else:
            target = requested_target if translate and requested_target else foreign if source == "en" else "en"
        if translate and target == source:
            if requested_target:
                raise ValueError("Choose different source and target languages.")
            target = foreign if source == "en" and foreign != "en" else "en"
        entries, suggestions, message = (), (), ""
        matched_length = 0
        if text and not translate:
            if (source == "en" and foreign != "en") or pair and source == pair[1]:
                entries = self.library.reverse(text, foreign if pair else target)
                if not entries and morphology and foreign != "ja":
                    entries = self._lemma_lookup(text, foreign, context)
                    if entries:
                        source, target = foreign, source
                        matched_length = len(text)
                if not entries:
                    suggestions = self.library.suggest(text, target)
            else:
                entries = self._japanese(text) if source == "ja" else self.library.lookup(text, source)
                if not entries and morphology and source != "ja":
                    entries = self._lemma_lookup(text, source, context)
                matched_length = self._matched_length if source == "ja" else len(text) if entries else 0
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
        result = SearchResult(text, source, target, entries, suggestions, translation, message, kanji, model, matched_length)
        # A missing or starting local server must be retryable on the same text.
        if (not translate or translation) and not (cancelled is not None and cancelled.is_set()):
            self.cache[cache_key] = result
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return result

    def _lemma_lookup(self, text, language, context):
        if not self.library._active(language):
            return ()
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
                candidate = candidate[:token.start-start] + token.lemma + candidate[token.end-start:]
        if candidate == text:
            return ()
        return tuple(replace(entry, route="lemma", inflection=("lemma",))
                     for entry in self.library.lookup(candidate, language, tolerant=False))

    def _japanese(self, text):
        self._matched_length = 0
        from .deconjugator import Deconjugator
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
        # Prefer the longest word at the beginning of a phrase, as the OCR lookup does.
        for length in range(min(25, len(text)), 0, -1):
            prefix = text[:length]
            results = list(self.library.lookup(prefix, "ja"))
            for form in sorted(self.deconjugator.deconjugate(prefix), key=lambda f: (len(f.process), f.text, f.tags)):
                if form.text == prefix:
                    continue
                for entry in self.library.lookup(form.text, "ja"):
                    if not compatible(form.tags, entry.rules):
                        continue
                    labels = {"teiru": "progressive", "teru (teiru)": "progressive",
                              "teoru": "progressive", "toru (teoru)": "progressive"}
                    process = tuple(dict.fromkeys(labels.get(step, step) for step in reversed(form.process)
                                                  if step and not step.startswith("(")))
                    results.append(replace(entry, route="inflected", inflection=process))
            if results:
                self._matched_length = length
                unique = {}
                for entry in results:
                    unique.setdefault(entry.id, entry)
                return tuple(unique.values())[:60]
        return ()
