"""Serialized offline Turkish OCR and dictionary lookup."""
from dataclasses import replace
from pathlib import Path
import threading
import sqlite3

from meikipop.dictionary.turkish_lookup import TurkishLookup
from meikipop.dictionary.turkish_store import TurkishStore
from meikipop.utils.lastest_queue import LatestValueQueue


class TextWorker(threading.Thread):
    def __init__(self, signals, dictionary, analyzer, model_dir):
        super().__init__(daemon=True, name="TurkishLookup")
        self.signals = signals
        self.dictionary, self.analyzer, self.model_dir = Path(dictionary), analyzer, model_dir
        self.queue = LatestValueQueue()

    def run(self):
        store, lookup, wordnet, ocr = None, None, None, None
        try:
            while True:
                request = self.queue.get()
                if request is None:
                    break
                request_id, text, target, scan = request
                phase = "dictionary"
                try:
                    if lookup is None:
                        if store is None:
                            store = TurkishStore(self.dictionary)
                        lookup = TurkishLookup(store, self.analyzer, self.model_dir)
                    if scan is not None:
                        phase = "ocr"
                        from meikipop.ocr.turkish_paddle import LocalOCR
                        if ocr is None:
                            ocr = LocalOCR()
                        hit = ocr.lookup_point(*scan)
                        if hit is None:
                            self.signals.completed.emit(request_id, None, "No text under the pointer. Move onto a word and scan again.")
                            continue
                        text, offset = hit
                        target = next((i for i, token in enumerate(lookup.analyze(text))
                                       if token.start <= offset < token.end), None)
                        if target is None:
                            self.signals.completed.emit(request_id, None, "No selectable word under the pointer.")
                            continue
                    phase = "dictionary"
                    result = lookup.lookup(text, target)
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
                        result = replace(result, wordnet=wordnet.lookup(words), wordnet_status="KeNet · Turkish WordNet")
                    except (OSError, ValueError, sqlite3.Error):
                        result = replace(result, wordnet_status="WordNet unavailable · install it in Settings")
                    self.signals.completed.emit(request_id, result, "")
                except Exception:
                    # No clipboard text or history is written to logs.
                    self.signals.completed.emit(request_id, None,
                        "Local OCR failed. Install OCR in Settings, then retry." if phase == "ocr" else
                        "Lookup failed. Check the dictionary path or run meikipop build-turkish-dict, then retry.")
        finally:
            if store is not None:
                store.close()
            if wordnet is not None:
                wordnet.close()
