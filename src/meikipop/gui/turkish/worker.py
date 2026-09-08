"""Independent recognition and serialized offline dictionary workers."""
from dataclasses import replace
import logging
from pathlib import Path
import threading
import sqlite3

from meikipop.dictionary.turkish_lookup import TurkishLookup
from meikipop.dictionary.turkish_store import TurkishStore
from meikipop.utils.lastest_queue import LatestValueQueue

logger = logging.getLogger(__name__)


class TextWorker(threading.Thread):
    def __init__(self, signals, dictionary, analyzer, model_dir):
        super().__init__(daemon=True, name="TurkishLookup")
        self.signals = signals
        self.dictionary, self.analyzer, self.model_dir = Path(dictionary), analyzer, model_dir
        self.queue = LatestValueQueue()

    def run(self):
        store, lookup, wordnet, wiktionary = None, None, None, None
        try:
            while True:
                request = self.queue.get()
                if request is None:
                    break
                request_id, text, target, scan = request
                try:
                    if lookup is None:
                        if store is None:
                            store = TurkishStore(self.dictionary)
                        lookup = TurkishLookup(store, self.analyzer, self.model_dir)
                    if scan is not None:
                        offset = scan
                        target = next((i for i, token in enumerate(lookup.analyze(text))
                                       if token.start <= offset < token.end), None)
                        if target is None:
                            self.signals.completed.emit(request_id, None, "No selectable word under the pointer.")
                            continue
                    result = lookup.lookup(text, target)
                    words = [e["headword"] for e in result.entries]
                    words.append(text.strip())
                    if result.target is not None:
                        token = result.tokens[result.target]
                        words.extend((text[token.start:token.end], token.lemma))
                    from meikipop.dictionary.turkish_wiktionary import WiktionaryStore, default_wiktionary_path
                    try:
                        if wiktionary is None:
                            wiktionary = WiktionaryStore(default_wiktionary_path())
                        result = replace(result, wiktionary=wiktionary.lookup(words))
                    except (OSError, ValueError, sqlite3.Error):
                        pass
                    from meikipop.dictionary.turkish_wordnet import WordNetStore, default_wordnet_path
                    try:
                        if wordnet is None:
                            wordnet = WordNetStore(default_wordnet_path())
                        words = [e["headword"] for e in result.entries]
                        if not words:
                            words = [text.strip()]
                            if result.target is not None:
                                token = result.tokens[result.target]
                                words.extend((text[token.start:token.end], token.lemma))
                        pos = result.tokens[result.target].pos if result.target is not None else None
                        result = replace(result, wordnet=wordnet.lookup(words, pos), wordnet_status="KeNet")
                    except (OSError, ValueError, sqlite3.Error):
                        result = replace(result, wordnet_status="WordNet unavailable · install it in Settings")
                    self.signals.completed.emit(request_id, result, "")
                except Exception:
                    # No clipboard text or history is written to logs.
                    self.signals.completed.emit(request_id, None,
                        "Lookup failed. Check the dictionary path or run meikipop build-turkish-dict, then retry.")
        finally:
            if store is not None:
                store.close()
            if wordnet is not None:
                wordnet.close()
            if wiktionary is not None:
                wiktionary.close()


class OCRWorker(threading.Thread):
    """Recognition has its own latest-frame queue, independent of NLP latency."""
    def __init__(self, signals):
        super().__init__(daemon=True, name="TurkishOCR")
        self.signals = signals
        self.queue = LatestValueQueue()

    def run(self):
        ocr = None
        while True:
            request = self.queue.get()
            if request is None:
                return
            request_id, pixels = request
            try:
                if ocr is None:
                    from meikipop.ocr.turkish_paddle import LocalOCR
                    ocr = LocalOCR()
                results = ocr.scan_cache.scan(pixels, ocr.recognize)
                self.signals.recognized.emit(request_id, results, "")
            except Exception as error:
                logger.exception("Turkish local OCR failed")
                detail = " ".join(str(error).split()) or type(error).__name__
                detail = detail[:240]
                self.signals.recognized.emit(request_id, None, f"Local OCR unavailable: {detail}")
