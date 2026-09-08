"""Versioned English Wiktionary packs, explicitly updated from wiktionary-to-yomitan releases."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import urllib.request
import zipfile
import re

from meikipop.language.analyzer import normalize


def default_wiktionary_path():
    from meikipop.utils.paths import paths
    return Path(paths.data_dir) / "languages/tr/packs/tr-wiktionary/1/dictionary.sqlite3"


def build(source, output, metadata=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary) / "dictionary.sqlite3"
        db = sqlite3.connect(stage)
        count = 0
        try:
            db.executescript("CREATE TABLE entries(key TEXT, data TEXT); CREATE INDEX entry_key ON entries(key);"
                             "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);")
            with zipfile.ZipFile(source) as archive:
                if sum(i.file_size for i in archive.infolist()) > 1_500_000_000:
                    raise ValueError("Wiktionary archive exceeds size limit")
                index = json.loads(archive.read("index.json"))
                if (index.get("format"), index.get("sourceLanguage"), index.get("targetLanguage")) != (3, "tr", "en"):
                    raise ValueError("Expected a Turkish to English Yomitan dictionary")
                banks = sorted(n for n in archive.namelist() if re.fullmatch(r"term_bank_\d+\.json", n))
                for name in banks:
                    for row in json.loads(archive.read(name)):
                        if not isinstance(row, list) or len(row) != 8 or not isinstance(row[0], str) or not isinstance(row[5], list):
                            raise ValueError("Invalid Yomitan term")
                        data = dict(word=row[0], pos=row[2], definitions=row[5], tags=row[7])
                        db.execute("INSERT INTO entries VALUES (?,?)", (normalize(row[0]), json.dumps(data, ensure_ascii=False)))
                        count += 1
            if not count:
                raise ValueError("No Turkish entries in Wiktionary source")
            info = dict(metadata or {}, schema=1, entries=count, revision=index["revision"], index=index)
            db.executemany("INSERT INTO metadata VALUES (?,?)", ((k, json.dumps(v)) for k, v in info.items()))
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Invalid Wiktionary pack")
        finally:
            db.close()
        stage.replace(output)
    return info


def setup_wiktionary(source=None, output=None):
    lock = json.loads((Path(__file__).parents[1] / "resources/turkish/wiktionary.json").read_text(encoding="utf-8"))
    output = Path(output or default_wiktionary_path())
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        if source is None:
            source = Path(temporary) / "source.zip"
            with urllib.request.urlopen(lock["url"], timeout=90) as response, source.open("wb") as stream:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 1_500_000_000:
                        raise ValueError("Wiktionary source exceeds size limit")
                    stream.write(chunk)
        with Path(source).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return build(source, output, dict(lock, source_sha256=digest))


class WiktionaryStore:
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = self.db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
            if row is None or json.loads(row[0]) != 1:
                raise ValueError("Unsupported Wiktionary schema")
        except Exception:
            self.db.close()
            raise

    def lookup(self, words):
        entries, seen = [], set()
        pending = list(words)
        queued = {normalize(word) for word in pending}
        index = 0
        while index < len(pending):
            word = pending[index]
            index += 1
            for (data,) in self.db.execute("SELECT data FROM entries WHERE key=? ORDER BY rowid", (normalize(word),)):
                if data in seen:
                    continue
                entry = json.loads(data)
                entries.append(entry)
                seen.add(data)
                labels = (entry.get("pos", "") + " " + entry.get("tags", "")).split()
                if any(label.lower() in ("non-lemma", "nonlemma") for label in labels):
                    for definition in entry.get("definitions", ()):
                        if (isinstance(definition, list) and definition
                                and isinstance(definition[0], str)):
                            lemma = definition[0]
                            if normalize(lemma) not in queued:
                                pending.append(lemma)
                                queued.add(normalize(lemma))
        return tuple(entries)

    def close(self):
        self.db.close()
