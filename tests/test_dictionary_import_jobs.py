from contextlib import closing
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
import zipfile

from meikipop.dictionary.library import import_yomitan


class DictionaryChecksumTests(unittest.TestCase):
    def make_archive(self, path, bank):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("index.json", json.dumps({"title": "Pitch", "format": 3, "sourceLanguage": "ja"}))
            archive.writestr("term_meta_bank_1.json", bank)
        data = bytearray(path.read_bytes())
        position = 0
        while True:
            position = data.find(b"PK\x01\x02", position)
            if position < 0:
                break
            size = struct.unpack_from("<H", data, position + 28)[0]
            if data[position + 46:position + 46 + size] == b"term_meta_bank_1.json":
                crc = struct.unpack_from("<I", data, position + 16)[0]
                struct.pack_into("<I", data, position + 16, crc ^ 1)
                break
            position += 4
        path.write_bytes(data)

    def test_crc_mismatch_is_advisory_when_pitch_contents_are_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "pitch.zip"
            self.make_archive(archive, json.dumps([["猫", "pitch", {"reading": "ねこ", "pitches": [{"position": 1}]}]]))
            with zipfile.ZipFile(archive) as strict:
                with self.assertRaises(zipfile.BadZipFile):
                    strict.read("term_meta_bank_1.json")
            warnings = []
            destination = import_yomitan(archive, Path(folder) / "library", warnings=warnings)
            self.assertEqual(warnings, ["term_meta_bank_1.json"])
            with closing(sqlite3.connect(destination)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pitches").fetchone()[0], 1)

    def test_invalid_json_is_not_published_when_crc_is_relaxed(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "pitch.zip"
            self.make_archive(archive, b"[broken json")
            library = Path(folder) / "library"
            with self.assertRaises(json.JSONDecodeError):
                import_yomitan(archive, library)
            self.assertFalse(list(library.glob("*.sqlite3")))
            self.assertFalse(list(library.glob("*.tmp")))
