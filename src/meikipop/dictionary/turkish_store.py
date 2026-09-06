"""Small, read-only TDK pack reader. No Qt or NLP dependencies."""
import json
from pathlib import Path
import sqlite3

from meikipop.language.analyzer import normalize

SCHEMA_VERSION = 1


def default_dictionary_path():
    from meikipop.utils.paths import paths
    return Path(paths.data_dir) / "languages/tr/packs/tr-tdk/poc-1/dictionary.sqlite3"


class TurkishStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            self.metadata = dict(self.connection.execute("SELECT key,value FROM metadata"))
            if int(self.metadata["schema_version"]) != SCHEMA_VERSION:
                raise ValueError("Unsupported Turkish dictionary schema; rebuild the pack")
        except Exception:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def lookup(self, text, pos=None):
        rows = self.connection.execute("""
            SELECT e.*, k.kind FROM lookup_keys k JOIN entries e ON e.id=k.entry_id
            WHERE k.key=? AND (k.kind='headword' OR (? IN ('VERB','AUX') AND k.kind='verb_stem'))
            ORDER BY CASE k.kind WHEN 'headword' THEN 0 ELSE 1 END, e.id
        """, (normalize(text.strip()), pos))
        entries = []
        for row in rows:
            entry = dict(row)
            entry["senses"] = json.loads(entry["senses"])
            entry["relations"] = [dict(r) for r in self.connection.execute(
                "SELECT phrase,related_id,kind FROM relations WHERE entry_id=? ORDER BY phrase", (entry["id"],))]
            entries.append(entry)
        if pos:
            entries.sort(key=lambda e: not any(s["pos"] == pos for s in e["senses"]))
        return entries
