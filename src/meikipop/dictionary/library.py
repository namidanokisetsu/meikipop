"""Immutable, indexed Yomitan packs shared by desktop search and OCR lookup."""
from dataclasses import dataclass, replace
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from time import monotonic, time_ns
import unicodedata
import zipfile
from meikipop.utils.timing import mark

_changes = {}
_changes_lock = threading.Lock()


def library_changed(directory):
    identity = os.path.normcase(os.path.abspath(directory))
    with _changes_lock:
        _changes[identity] = _changes.get(identity, 0) + 1


def default_library_path():
    from meikipop.utils.paths import paths
    return Path(paths.data_dir) / "dictionaries"


def key(text, language="ja"):
    from meikipop.language.profiles import get_profile
    return get_profile(language).lookup_key(text)


def language_code(value):
    value = str(value).strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", value):
        raise ValueError("Enter a language code such as ja, tr, en, de or zh.")
    return value


def folded(text):
    text = key(text, "tr").replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(c))


@dataclass(frozen=True)
class Entry:
    id: str
    term: str
    reading: str
    source: str
    language: str
    definitions: tuple
    rules: tuple = ()
    route: str = "exact"
    frequencies: tuple = ()
    inflection: tuple = ()

    def glosses(self):
        from meikipop.scripts.import_yomitan_dict_html import StructuredContentConverter
        return StructuredContentConverter().extract_glosses(list(self.definitions))


def import_yomitan(archive, directory=None, language=None, progress=None, cancelled=None):
    """Read one bank at a time, then atomically publish a complete pack.

    Existing packs stay readable during imports. The archive hash makes reimport
    idempotent; revisions with the same title are selected by installation time.
    """
    from meikipop.scripts.import_yomitan_dict_text import extract_glosses
    archive = Path(archive)
    directory = Path(directory or default_library_path())
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    sha = digest.hexdigest()
    # Language belongs to the pack identity when a legacy archive omits it.
    with zipfile.ZipFile(archive) as zf:
        index = json.loads(zf.read("index.json"))
        source_language = language_code(language or index.get("sourceLanguage") or "ja")
        title = index.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Dictionary index has no title.")
        if index.get("format", index.get("version")) not in (1, 2, 3):
            raise ValueError("Unsupported Yomitan dictionary version.")
        destination = directory / f"{source_language}-{sha}.sqlite3"
        if destination.exists():
            with closing(sqlite3.connect(destination)) as existing:
                version = existing.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if version and version[0] == "2":
                return destination
        banks = sorted((n for n in zf.namelist() if re.fullmatch(r"term_bank_\d+\.json", n)),
                       key=lambda n: int(n[10:-5]))
        metadata_banks = [n for n in zf.namelist() if re.fullmatch(r"(?:term_meta|kanji)_bank_\d+\.json", n)]
        if not banks and not metadata_banks:
            raise ValueError("No definitions, forms, frequency or kanji banks found.")
        fd, temporary = tempfile.mkstemp(prefix=".import-", suffix=".sqlite3.tmp", dir=directory)
        os.close(fd)
        db = sqlite3.connect(temporary)
        count = redirects = 0
        try:
            db.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                PRAGMA cache_size=-16384;
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE terms(id INTEGER PRIMARY KEY, term TEXT, reading TEXT,
                    key TEXT, reading_key TEXT, folded TEXT, score REAL, rules TEXT, definitions TEXT);
                CREATE TABLE forms(key TEXT, folded TEXT, target TEXT, labels TEXT);
                CREATE TABLE frequencies(key TEXT, reading_key TEXT, rank REAL, label TEXT);
                CREATE TABLE kanji(character TEXT PRIMARY KEY, data TEXT);
                CREATE VIRTUAL TABLE gloss_search USING fts5(gloss, content='');
            """)
            for number, name in enumerate(banks, 1):
                if cancelled and cancelled():
                    raise InterruptedError("Dictionary import cancelled.")
                with zf.open(name) as stream:
                    rows = json.load(stream)
                if not isinstance(rows, list):
                    raise ValueError(f"Invalid term bank: {name}")
                terms, forms, glosses = [], [], []
                for row in rows:
                    if (not isinstance(row, list) or len(row) < 6 or
                            not isinstance(row[0], str) or not isinstance(row[1], str) or
                            not isinstance(row[5], list)):
                        raise ValueError(f"Invalid dictionary entry in {name}")
                    term, reading, definitions = row[0], row[1], row[5]
                    canonical = key(term, source_language)
                    if not canonical:
                        continue
                    regular = []
                    for definition in definitions:
                        if isinstance(definition, list):
                            if definition and isinstance(definition[0], str):
                                labels = definition[1] if len(definition) > 1 and isinstance(definition[1], list) else []
                                forms.append((canonical, folded(term), key(definition[0], source_language),
                                              json.dumps([s for s in labels if isinstance(s, str)], ensure_ascii=False)))
                                redirects += 1
                        else:
                            regular.append(definition)
                    if not regular:
                        continue
                    count += 1
                    terms.append((count, term, reading, canonical, key(reading, source_language),
                                  folded(term), float(row[4] or 0), str(row[3] or ""),
                                  json.dumps(regular, ensure_ascii=False, separators=(",", ":"))))
                    glosses.append((count, " ".join(extract_glosses(regular))))
                db.executemany("INSERT INTO terms VALUES(?,?,?,?,?,?,?,?,?)", terms)
                db.executemany("INSERT INTO forms VALUES(?,?,?,?)", forms)
                db.executemany("INSERT INTO gloss_search(rowid,gloss) VALUES(?,?)", glosses)
                if progress:
                    progress(f"{title}: {number}/{len(banks)}")
            from .metadata import frequency_rows, kanji_rows
            frequency_count = kanji_count = 0
            for term, reading, rank, label in frequency_rows(zf, source_language, cancelled):
                db.execute("INSERT INTO frequencies VALUES(?,?,?,?)",
                           (key(term, source_language), key(reading, source_language), rank, label))
                frequency_count += 1
                if frequency_count % 10000 == 0 and cancelled and cancelled():
                    raise InterruptedError("Dictionary import cancelled.")
            for character, data in kanji_rows(zf, cancelled):
                db.execute("INSERT OR REPLACE INTO kanji VALUES(?,?)",
                           (character, json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
                kanji_count += 1
            if not (count or redirects or frequency_count or kanji_count):
                raise ValueError("Dictionary contains no usable definitions, forms, frequencies or kanji.")
            if progress:
                progress(f"{title}: indexing…")
            db.executescript("""
                CREATE INDEX term_key ON terms(key);
                CREATE INDEX term_reading ON terms(reading_key);
                CREATE INDEX term_folded ON terms(folded);
                CREATE INDEX form_key ON forms(key);
                CREATE INDEX form_folded ON forms(folded);
                CREATE INDEX frequency_key ON frequencies(key,reading_key);
            """)
            metadata = dict(schema_version="2", imported_at_ns=str(time_ns()), title=title, language=source_language,
                            target_language=str(index.get("targetLanguage", "")),
                            frequency_mode=str(index.get("frequencyMode", "rank-based")),
                            revision=str(index.get("revision", "")), sha256=sha,
                            entries=str(count), forms=str(redirects),
                            frequencies=str(frequency_count), kanji=str(kanji_count))
            db.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
            db.commit()
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Dictionary integrity check failed.")
            if cancelled and cancelled():
                raise InterruptedError("Dictionary import cancelled.")
            db.close()
            if destination.exists():
                # Upgrade in a transaction: Windows readers can keep the existing pack open.
                with closing(sqlite3.connect(destination)) as existing, existing:
                    existing.execute("ATTACH DATABASE ? AS upgraded", (temporary,))
                    existing.execute("BEGIN IMMEDIATE")
                    existing.execute("ALTER TABLE forms ADD COLUMN labels TEXT NOT NULL DEFAULT '[]'")
                    existing.execute("""UPDATE forms SET labels=COALESCE((SELECT labels FROM upgraded.forms f
                        WHERE f.rowid=forms.rowid AND f.key=forms.key AND f.target=forms.target),'[]')""")
                    existing.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
            else:
                os.replace(temporary, destination)
                library_changed(directory)
        finally:
            db.close()
            if os.path.exists(temporary):
                os.unlink(temporary)
    return destination


class Library:
    """Open on the querying thread; no dictionary-sized Python collections."""
    def __init__(self, directory=None):
        self.directory = Path(directory or default_library_path())
        self._identity = os.path.normcase(os.path.abspath(self.directory))
        self.packs = []
        self.errors = []
        self.revision = 0
        self.refresh()

    def close(self):
        for _, _, db in self.packs:
            db.close()
        self.packs = []

    def refresh(self):
        self.revision += 1
        self._change_revision = _changes.get(self._identity, 0)
        self.close()
        self.errors = []
        selected = {}
        try:
            preferences = json.loads((self.directory / "preferences.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            preferences = {}
        if not isinstance(preferences, dict):
            preferences = {}
        disabled = preferences.get("disabled", [])
        order = preferences.get("order", [])
        disabled = disabled if isinstance(disabled, list) else []
        order = order if isinstance(order, list) else []
        for path in sorted(self.directory.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime_ns, reverse=True):
            if path.with_suffix(".removing").exists():
                continue
            db = None
            try:
                db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA cache_size=-2048")
                metadata = dict(db.execute("SELECT key,value FROM metadata"))
                if metadata.get("schema_version") not in ("1", "2"):
                    raise ValueError("Unsupported dictionary pack")
                identity = (metadata["language"], metadata["title"])
                previous = selected.get(identity)
                if previous:
                    previous_time = int(previous[1].get("imported_at_ns", previous[0].stat().st_mtime_ns))
                    if previous_time >= int(metadata.get("imported_at_ns", path.stat().st_mtime_ns)):
                        db.close()
                        continue
                    previous[2].close()
                    self.packs.remove(previous)
                metadata["enabled"] = path.name not in disabled
                selected[identity] = (path, metadata, db)
                self.packs.append(selected[identity])
            except (OSError, sqlite3.Error, ValueError, KeyError) as error:
                if db:
                    db.close()
                self.errors.append(f"{path.name}: {error}")
        self.packs.sort(key=lambda p: (order.index(p[0].name) if p[0].name in order else len(order), p[1]["title"]))
        self._signature = self._inventory_signature()
        self._next_inventory_check = monotonic() + 2

    def _inventory_signature(self):
        mark("inventory", self.revision)
        files = [*self.directory.glob("*.sqlite3"), *self.directory.glob("*.removing")]
        preferences = self.directory / "preferences.json"
        if preferences.exists():
            files.append(preferences)
        signature = []
        for path in files:
            try:
                stat = path.stat()
                signature.append((path.name, stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                pass
        return tuple(sorted(signature))

    def refresh_if_changed(self):
        if _changes.get(self._identity, 0) != self._change_revision:
            self.refresh()
            return True
        if monotonic() < self._next_inventory_check:
            return False
        self._next_inventory_check = monotonic() + 2
        if self._inventory_signature() != self._signature:
            self.refresh()
            return True
        return False

    def _active(self, language):
        return [(path, meta, db) for path, meta, db in self.packs
                if meta["enabled"] and meta["language"] == language]

    @staticmethod
    def _entry(path, meta, row, route):
        return Entry(f"{path.stem}:{row['id']}", row["term"], row["reading"],
                     meta["title"], meta["language"], tuple(json.loads(row["definitions"])),
                     tuple(row["rules"].split()), route)

    def lookup(self, text, language="ja", limit=60, *, tolerant=True):
        term = key(text, language)
        if not term or len(term) > 2000:
            return ()
        packs = self._active(language)
        keys = {term: "exact"}
        if language == "ja":
            hiragana = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in term)
            katakana = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in term)
            keys.update({hiragana: "exact", katakana: "exact"})
        # Forms may live in a separate pack. Resolve a bounded graph to avoid cycles.
        form_paths = {}

        def form_rows(meta, db, candidate, fold=False):
            column = "folded" if fold else "key"
            labels = "labels" if meta.get("schema_version") == "2" else "'[]'"
            return db.execute(f"SELECT target,{labels} FROM forms WHERE {column}=? LIMIT 64",
                              (folded(candidate) if fold else candidate,))

        def remember_form(candidate, target, raw):
            if target == term:
                return
            labels = tuple(json.loads(raw)) or ("inflected form",)
            paths = form_paths.setdefault(target, [])
            for parent in tuple(form_paths.get(candidate, [()])):
                path = parent + labels
                if path not in paths and len(paths) < 8:
                    paths.append(path)

        def inflections():
            return {target: paths[0] if len(paths) == 1 else (" OR ".join(" · ".join(p) for p in paths),)
                    for target, paths in form_paths.items() if paths}

        frontier = set(keys)
        for _ in range(3):
            following = set()
            for _, meta, db in packs:
                for candidate in frontier:
                    for row in form_rows(meta, db, candidate):
                        remember_form(candidate, row[0], row[1])
                        if row[0] not in keys and len(keys) < 128:
                            keys[row[0]] = "form"
                            following.add(row[0])
            if not following:
                break
            frontier = following
        result = self._lookup_keys(packs, keys, limit, inflections=inflections())
        if language == "tr" and tolerant:
            # A single indexed query fixes any number of missing Turkish accents.
            folded_keys = {term: "spelling"}
            for _, meta, db in packs:
                for row in form_rows(meta, db, term, fold=True):
                    remember_form(term, row[0], row[1])
                    folded_keys[row[0]] = "form spelling"
            result += self._lookup_keys(packs, folded_keys, limit, fold=True, inflections=inflections())
        unique = {}
        for entry in result:
            unique.setdefault(entry.id, entry)
        return self._with_frequencies(tuple(list(unique.values())[:limit]), language)

    def _with_frequencies(self, entries, language):
        cache = {}
        result = []
        for entry in entries:
            identity = (entry.term, entry.reading)
            if identity not in cache:
                cache[identity] = self.frequencies(*identity, language)
            result.append(replace(entry, frequencies=cache[identity]))
        return tuple(result)

    def frequencies(self, term, reading="", language="ja"):
        from .metadata import Frequency
        result = []
        for _, meta, db in self._active(language):
            if not int(meta.get("frequencies", 0)):
                continue
            for row in db.execute("SELECT rank,label,reading_key FROM frequencies WHERE key=? AND reading_key IN ('',?)",
                                  (key(term, language), key(reading, language))):
                result.append(Frequency(meta["title"], row[0], row[1], row[2], meta.get("frequency_mode", "rank-based")))
        return tuple(dict.fromkeys(result))

    def kanji_info(self, text, limit=12):
        from .kanji import KanjiEntry, kanji_characters
        characters = kanji_characters(text, limit)
        result = []
        for character in characters:
            for _, meta, db in self._active("ja"):
                if not int(meta.get("kanji", 0)):
                    continue
                row = db.execute("SELECT data FROM kanji WHERE character=?", (character,)).fetchone()
                if row:
                    data = json.loads(row[0])
                    result.append(KanjiEntry(character=character, source=meta["title"],
                        onyomi=tuple(data.get("onyomi", ())), kunyomi=tuple(data.get("kunyomi", ())),
                        meanings=tuple(data.get("meanings", ())), tags=tuple(data.get("tags", ())),
                        stats=tuple(data.get("stats", {}).items())))
        return tuple(result)

    def _lookup_keys(self, packs, keys, limit, fold=False, inflections=None):
        result = []
        # Direct spellings precede form-derived entries across all dictionaries.
        for candidate, route in keys.items():
            for path, meta, db in packs:
                if fold:
                    rows = db.execute("SELECT * FROM terms WHERE folded=? ORDER BY score DESC,id LIMIT ?",
                                      (folded(candidate), limit))
                else:
                    rows = db.execute("SELECT * FROM terms WHERE key=? OR reading_key=? ORDER BY score DESC,id LIMIT ?",
                                      (candidate, candidate, limit))
                result.extend(replace(self._entry(path, meta, row, route),
                                      inflection=(inflections or {}).get(candidate, ()) if route.startswith("form") else ())
                              for row in rows)
        return result

    def reverse(self, text, language="ja", limit=30):
        """English gloss search, with quoted tokens instead of raw FTS syntax."""
        words = re.findall(r"[^\W_]+", text, re.UNICODE)[:12]
        if not words:
            return ()
        query = " AND ".join('"' + word.replace('"', '""') + '"' for word in words)
        result = []
        for path, meta, db in self._active(language):
            plain = " ".join(words).lower()
            rows = db.execute("""SELECT t.* FROM gloss_search g JOIN terms t ON t.id=g.rowid
                WHERE gloss_search MATCH ? ORDER BY
                EXISTS(SELECT 1 FROM json_tree(t.definitions) j WHERE j.type='text' AND
                    (lower(j.value) IN (?,?) OR lower(j.value) LIKE ? OR lower(j.value) LIKE ?
                     OR lower(j.value) LIKE ? OR lower(j.value) LIKE ?)) DESC,
                t.score DESC, length(t.term), rank LIMIT ?""",
                (query, plain, 'to ' + plain, plain + ";%", plain + " (%", 'to ' + plain + " (%", plain + ",%", limit))
            result.extend(self._entry(path, meta, row, "English gloss") for row in rows)
        return self._with_frequencies(tuple(result[:limit]), language)

    def suggest(self, text, language="tr", limit=8):
        """Bounded typo candidates; normalized accent recovery happens in lookup."""
        text = folded(text) if language == "tr" else key(text, language)
        if not 2 <= len(text) <= 40 or not text.isalpha():
            return ()
        variants = {text[:i] + text[i + 1:] for i in range(len(text))}
        variants.update(text[:i] + text[i + 1] + text[i] + text[i + 2:] for i in range(len(text) - 1))
        if language == "tr":
            for char in "abcdefghijklmnopqrstuvwxyz":
                variants.update(text[:i] + char + text[i + 1:] for i in range(len(text)))
                variants.update(text[:i] + char + text[i:] for i in range(len(text) + 1))
        variants = sorted(variants - {text})
        found = set()
        column = "folded" if language == "tr" else "key"
        for _, _, db in self._active(language):
            for start in range(0, len(variants), 400):
                batch = variants[start:start + 400]
                placeholders = ",".join("?" for _ in batch)
                found.update(r[0] for r in db.execute(
                    f"SELECT term FROM terms WHERE {column} IN ({placeholders}) LIMIT 40", batch))
        return tuple(sorted(found, key=lambda w: (abs(len(w) - len(text)), w))[:limit])


def remove_dictionary(directory, filename, refresh, cancelled):
    """Remove all revisions of one pack after readers release Windows file handles."""
    root = Path(directory).resolve()
    target = (root / filename).resolve()
    if target.parent != root or target.suffix != ".sqlite3":
        raise ValueError("Choose an installed dictionary.")
    def identity(path):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            return metadata["language"], metadata["title"]
    selected = identity(target)
    paths = []
    for path in root.glob("*.sqlite3"):
        if path.resolve().parent != root:
            continue
        try:
            if identity(path) == selected:
                paths.append(path)
        except (sqlite3.Error, KeyError):
            continue
    markers = [path.with_suffix(".removing") for path in paths]
    try:
        for marker in markers:
            marker.touch()
        library_changed(root)
        refresh()
        deadline = monotonic() + 15
        remaining = list(paths)
        while remaining:
            if cancelled.is_set():
                raise InterruptedError("Removal cancelled.")
            for path in remaining[:]:
                try:
                    path.unlink(missing_ok=True)
                    remaining.remove(path)
                except PermissionError:
                    if monotonic() >= deadline:
                        raise OSError("Dictionary is still in use. Close other Meikipop windows and try again.")
            if remaining:
                cancelled.wait(.05)
    finally:
        for marker in markers:
            marker.unlink(missing_ok=True)
        library_changed(root)
        refresh()


def save_preferences(directory, disabled, order):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".preferences-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(dict(disabled=list(disabled), order=list(order)), stream, ensure_ascii=False)
        os.replace(temporary, directory / "preferences.json")
        library_changed(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
