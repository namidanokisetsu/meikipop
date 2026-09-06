"""Build the locked TDK snapshot using only the Python standard library."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import tempfile
from urllib.request import urlopen

from meikipop.language.analyzer import normalize

LOCK_PATH = Path(__file__).resolve().parents[1] / "resources/turkish/sources.json"
POS = {"isim": "NOUN", "sıfat": "ADJ", "zarf": "ADV", "zamir": "PRON",
       "edat": "ADP", "bağlaç": "CCONJ", "ünlem": "INTJ"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download_source(lock):
    from meikipop.utils.paths import paths
    cache = Path(paths.cache_dir) / "turkish"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (lock["sha256"] + ".db")
    if target.exists() and sha256(target) == lock["sha256"]:
        return target
    url = f"https://raw.githubusercontent.com/ogun/guncel-turkce-sozluk/{lock['commit']}/{lock['artifact']}"
    temporary = target.with_suffix(".part")
    try:
        with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                output.write(block)
        if sha256(temporary) != lock["sha256"]:
            raise ValueError("TDK source checksum mismatch")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def build(source, output, lock=None):
    source, output = Path(source), Path(output)
    source_hash = sha256(source)
    if lock and source_hash != lock["sha256"]:
        raise ValueError("TDK source checksum mismatch")
    output.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Source SQLite integrity check failed")
        # Missing optional authors exist in v12. Count all broken source relations.
        source_fk_errors = len(src.execute("PRAGMA foreign_key_check").fetchall())
        labels, examples, senses = defaultdict(list), defaultdict(list), defaultdict(list)
        for row in src.execute("""SELECT a.anlam_id,o.tam_adi,o.tur FROM anlam_ozellik a
                                  JOIN ozellik o USING(ozellik_id) ORDER BY a.anlam_id,o.ozellik_id"""):
            labels[row["anlam_id"]].append(row["tam_adi"])
        for row in src.execute("""SELECT o.*,y.tam_adi AS author FROM ornek o LEFT JOIN yazar y
                                  USING(yazar_id) ORDER BY anlam_id,ornek_sira,ornek_id"""):
            if row["ornek"]:
                examples[row["anlam_id"]].append({"text": row["ornek"], "author": row["author"] or row["yazar_vd"] or ""})
        empty_senses = 0
        for row in src.execute("SELECT * FROM anlam ORDER BY madde_id,anlam_sira,anlam_id"):
            if not row["anlam"].strip():
                empty_senses += 1
                continue
            tags = labels[row["anlam_id"]]
            pos = "VERB" if row["fiil"] or any(t in tags for t in ("nesnesiz", "yardımcı  fiil", "-i", "-e", "-den", "-le", "-de")) else next((POS[t] for t in tags if t in POS), None)
            senses[row["madde_id"]].append({"text": row["anlam"], "order": row["anlam_sira"],
                                           "pos": pos, "labels": tags, "examples": examples[row["anlam_id"]]})
        with tempfile.TemporaryDirectory(dir=output) as temp:
            db_path = Path(temp) / "dictionary.sqlite3"
            db = sqlite3.connect(db_path)
            try:
                db.executescript("""
                    PRAGMA foreign_keys=ON;
                    CREATE TABLE entries(id TEXT PRIMARY KEY,headword TEXT NOT NULL,key TEXT NOT NULL,
                      source TEXT NOT NULL,language TEXT NOT NULL,senses TEXT NOT NULL,pronunciation TEXT,origin TEXT);
                    CREATE TABLE lookup_keys(key TEXT NOT NULL,entry_id TEXT REFERENCES entries(id),kind TEXT NOT NULL,
                      PRIMARY KEY(key,entry_id,kind));
                    CREATE INDEX entries_key ON entries(key);
                    CREATE TABLE relations(entry_id TEXT REFERENCES entries(id),related_id TEXT REFERENCES entries(id),
                      phrase TEXT NOT NULL,kind TEXT NOT NULL);
                    CREATE INDEX relations_entry ON relations(entry_id);
                    CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                """)
                visible, omitted = set(), 0
                for row in src.execute("SELECT * FROM madde ORDER BY madde_id"):
                    sid = row["madde_id"]
                    if not senses[sid] or not row["madde"].strip():
                        omitted += 1
                        continue
                    visible.add(sid)
                    eid, headword = f"tdk:{sid}", row["madde"]
                    key = normalize(headword)
                    db.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)", (eid, headword, key, "TDK", "tr",
                               json.dumps(senses[sid], ensure_ascii=False), row["telaffuz"], row["lisan"]))
                    db.execute("INSERT INTO lookup_keys VALUES(?,?,?)", (key, eid, "headword"))
                    if key.endswith(("mak", "mek")) and any(s["pos"] == "VERB" for s in senses[sid]):
                        db.execute("INSERT INTO lookup_keys VALUES(?,?,?)", (key[:-3], eid, "verb_stem"))
                for row in src.execute("""SELECT m.madde_id,a.madde_id AS related,a.madde FROM madde_atasozu m
                                          JOIN atasozu a ON a.madde_id=m.atasozu_madde_id
                                          ORDER BY m.madde_id,a.madde_id"""):
                    if row["madde_id"] in visible:
                        db.execute("INSERT INTO relations VALUES(?,?,?,?)", (f"tdk:{row['madde_id']}",
                                   f"tdk:{row['related']}" if row["related"] in visible else None, row["madde"], "idiom"))
                for row in src.execute("SELECT madde_id,birlesikler FROM madde WHERE birlesikler IS NOT NULL ORDER BY madde_id"):
                    if row["madde_id"] in visible:
                        for phrase in row["birlesikler"].split(","):
                            phrase = phrase.strip()
                            if not phrase:
                                continue
                            related = db.execute("SELECT id FROM entries WHERE key=? ORDER BY id LIMIT 1", (normalize(phrase),)).fetchone()
                            db.execute("INSERT INTO relations VALUES(?,?,?,?)", (f"tdk:{row['madde_id']}", related[0] if related else None, phrase, "compound"))
                report = {"schema_version": 1, "importer_version": 1, "pack_id": "tr-tdk", "source_sha256": source_hash,
                          "source": lock or {"fixture": True}, "entries": len(visible), "omitted_entries": omitted,
                          "empty_senses": empty_senses, "source_foreign_key_errors": source_fk_errors,
                          "python": platform.python_version(), "sqlite": sqlite3.sqlite_version}
                db.executemany("INSERT INTO metadata VALUES(?,?)", ((k, str(v) if isinstance(v, int) else json.dumps(v)) for k,v in report.items()))
                db.commit()
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Built pack failed integrity checks")
            finally:
                db.close()
            report["database_sha256"] = sha256(db_path)
            # Replace only a completely built, validated database.
            db_path.replace(output / "dictionary.sqlite3")
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            manifest.replace(output / "manifest.json")
        return report
    finally:
        src.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Previously downloaded locked v12 SQLite source")
    parser.add_argument("--output", type=Path, help="Pack directory (default: application Turkish data directory)")
    args = parser.parse_args(argv)
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if args.output is None:
        from meikipop.dictionary.turkish_store import default_dictionary_path
        args.output = default_dictionary_path().parent
    report = build(args.source or download_source(lock), args.output, lock)
    print(json.dumps(report, indent=2))
    print(f"Dictionary ready: {args.output / 'dictionary.sqlite3'}")


if __name__ == "__main__":
    main()
