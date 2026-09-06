"""KeNet pack builder and indexed offline semantic lookup."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

from meikipop.language.analyzer import normalize


def default_wordnet_path():
    from meikipop.utils.paths import paths
    return Path(paths.data_dir) / "languages/tr/packs/tr-kenet/1/wordnet.sqlite3"


def build(source, output, metadata=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as staging:
        temporary = Path(staging) / "wordnet.sqlite3"
        db = sqlite3.connect(temporary)
        try:
            db.executescript('''
                CREATE TABLE synsets(id TEXT PRIMARY KEY, pos TEXT, definition TEXT, example TEXT);
                CREATE TABLE members(synset TEXT, spelling TEXT, key TEXT, sense TEXT, group_id TEXT);
                CREATE INDEX member_key ON members(key);
                CREATE INDEX member_synset ON members(synset);
                CREATE TABLE edges(source TEXT, target TEXT, kind TEXT, target_sense TEXT);
                CREATE INDEX edge_source ON edges(source);
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
            ''')
            for _, node in ET.iterparse(source, events=("end",)):
                if node.tag != "SYNSET":
                    continue
                sid = node.findtext("ID")
                if not sid:
                    raise ValueError("KeNet synset without ID")
                db.execute("INSERT INTO synsets VALUES (?,?,?,?)", (
                    sid, node.findtext("POS", ""), node.findtext("DEF", ""), node.findtext("EXAMPLE", "")))
                for member in node.findall("SYNONYM/LITERAL"):
                    spelling = (member.text or "").strip()
                    if spelling:
                        db.execute("INSERT INTO members VALUES (?,?,?,?,?)", (
                            sid, spelling, normalize(spelling), member.findtext("SENSE", ""), member.findtext("GROUP", "")))
                for edge in node.findall("SR"):
                    db.execute("INSERT INTO edges VALUES (?,?,?,?)", (
                        sid, (edge.text or "").strip(), edge.findtext("TYPE", ""), edge.findtext("TO", "")))
                node.clear()
            missing = db.execute("SELECT COUNT(*) FROM edges WHERE target NOT IN (SELECT id FROM synsets)").fetchone()[0]
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("synsets", "members", "edges")}
            if not counts["synsets"]:
                raise ValueError("Empty WordNet source")
            info = dict(metadata or {}, schema=1, missing_targets=missing, **counts)
            db.executemany("INSERT INTO metadata VALUES (?,?)", [(k, json.dumps(v)) for k, v in info.items()])
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Invalid WordNet pack")
        finally:
            db.close()
        temporary.replace(output)
    return info


def setup_wordnet(source=None, output=None):
    lock_path = Path(__file__).parents[1] / "resources/turkish/wordnet.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if source is None:
        from meikipop.utils.paths import paths
        source = Path(paths.cache_dir) / (lock["sha256"] + ".xml")
        if not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(lock["url"], timeout=90) as response:
                data = response.read(50_000_001)
            if len(data) > 50_000_000 or hashlib.sha256(data).hexdigest() != lock["sha256"]:
                raise ValueError("KeNet download checksum mismatch")
            source.write_bytes(data)
    if hashlib.sha256(Path(source).read_bytes()).hexdigest() != lock["sha256"]:
        raise ValueError("KeNet source checksum mismatch")
    return build(source, output or default_wordnet_path(), lock)


class WordNetStore:
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        try:
            row = self.db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
            if row is None or json.loads(row[0]) != 1:
                raise ValueError("Unsupported WordNet schema")
        except Exception:
            self.db.close()
            raise

    def lookup(self, headwords):
        groups = {}
        for word in headwords:
            for row in self.db.execute("SELECT DISTINCT s.* FROM synsets s JOIN members m ON m.synset=s.id WHERE m.key=? ORDER BY s.id", (normalize(word),)):
                if row["id"] in groups:
                    continue
                group = dict(row)
                group["members"] = [dict(m) for m in self.db.execute("SELECT spelling,sense,group_id FROM members WHERE synset=?", (row["id"],))]
                group["relations"] = [dict(e) for e in self.db.execute('''
                    SELECT e.kind, e.target, e.target_sense, m.spelling FROM edges e
                    JOIN members m ON m.synset=e.target WHERE e.source=? ORDER BY e.kind,e.target,m.rowid
                ''', (row["id"],))]
                groups[row["id"]] = group
        return tuple(groups.values())

    def close(self):
        self.db.close()
