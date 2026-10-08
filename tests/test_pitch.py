import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from meikipop.dictionary.library import Library, import_yomitan, save_preferences
from meikipop.dictionary.pitch import Pitch, levels, morae, render_pitches


class PitchTests(unittest.TestCase):
    def test_morae_and_pitch_patterns(self):
        self.assertEqual(morae("きょうアームいっぽん"), ("きょ", "う", "ア", "ー", "ム", "い", "っ", "ぽ", "ん"))
        for position, expected in ((0, (False, True, True, True)), (1, (True, False, False, False)),
                                   (2, (False, True, False, False)), (3, (False, True, True, False)),
                                   ("LHHH", (False, True, True, True))):
            self.assertEqual(levels(Pitch("Pitch", "おとこ", position)), expected)
        self.assertNotIn("ꜜ", render_pitches([Pitch("Pitch", "おとこ", "LHH")]))
        self.assertIn("こ</span>ꜜ", render_pitches([Pitch("Pitch", "おとこ", 3)]))
        self.assertNotIn("&lt;source&gt;", render_pitches([Pitch("<source>", "あ", 1)]))

    def test_identical_accents_merge_across_sources_but_variants_remain(self):
        html = render_pitches([
            Pitch("First", "ねこ", 1), Pitch("Second", "ねこ", 1),
            Pitch("Third", "ねこ", 0), Pitch("Fourth", "ねこ", 1, devoice=(1,)),
            Pitch("Fifth", "ねこ", 1, tags=("<rare>",)),
        ])
        self.assertEqual(html.count("<p "), 1)
        self.assertEqual(html.count("[1]"), 3)
        self.assertNotIn("First", html)
        self.assertNotIn("Second", html)
        self.assertIn("devoiced: 1", html)
        self.assertIn("&lt;rare&gt;", html)

    def test_import_readings_sources_disable_and_upgrade_with_live_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "dictionary.zip"
            packs = root / "packs"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(dict(title="Words", format=3, sourceLanguage="ja")))
                output.writestr("term_bank_1.json", json.dumps([
                    ["生", "せい", "", "", 0, ["life"]], ["生", "なま", "", "", 0, ["raw"]]]))
            words = import_yomitan(archive, packs)
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(dict(title="Pitch", format=3)))
                output.writestr("term_meta_bank_1.json", json.dumps([
                    ["生", "pitch", {"reading": "せい", "pitches": [
                        {"position": 0}, {"position": 1, "devoice": 1, "tags": ["noun"]}, {"position": 0}]}]]))
            pitch = import_yomitan(archive, packs)
            with sqlite3.connect(pitch) as db:
                db.execute("DROP TABLE pitches")
                db.execute("DELETE FROM metadata WHERE key='pitches'")
                db.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
            db.close()
            library = Library(packs)
            try:
                self.assertEqual(library.lookup("生")[0].pitches, ())
                self.assertEqual(import_yomitan(archive, packs), pitch)
                self.assertTrue(library.refresh_if_changed())
                entries = {entry.reading: entry for entry in library.lookup("生")}
                self.assertEqual([p.position for p in entries["せい"].pitches], [0, 1])
                self.assertEqual(entries["せい"].pitches[1].devoice, (1,))
                self.assertEqual(entries["なま"].pitches, ())
                self.assertTrue(library.reverse("life")[0].pitches)
                save_preferences(packs, [pitch.name], [words.name, pitch.name])
                library.refresh_if_changed()
                self.assertFalse(library.lookup("生")[0].pitches)
            finally:
                library.close()

    def test_invalid_pitch_does_not_publish_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "pitch.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(dict(title="Bad pitch", format=3)))
                output.writestr("term_meta_bank_1.json", json.dumps([
                    ["猫", "pitch", {"reading": "ねこ", "pitches": [{"position": True}]}]]))
            with self.assertRaises(ValueError):
                import_yomitan(archive, root / "packs")
            self.assertEqual(list((root / "packs").iterdir()), [])

    def test_empty_term_rows_are_ignored_after_payload_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "pitch.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(dict(title="Pitch", format=3)))
                output.writestr("term_meta_bank_1.json", json.dumps([
                    ["", "pitch", {"reading": "あくらつ", "pitches": [{"position": 0}]}],
                    ["悪辣", "pitch", {"reading": "あくらつ", "pitches": [{"position": 0}]}],
                ]))

            imported = import_yomitan(archive, root / "packs")
            with sqlite3.connect(imported) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pitches").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT key FROM pitches").fetchone()[0], "悪辣")

            for accent in ({"position": True}, {"position": 0, "nasal": "bad"},
                           {"position": 0, "tags": "bad"}):
                with self.subTest(accent=accent):
                    with zipfile.ZipFile(archive, "w") as output:
                        output.writestr("index.json", json.dumps(dict(title="Invalid", format=3)))
                        output.writestr("term_meta_bank_1.json", json.dumps([
                            ["", "pitch", {"reading": "ねこ", "pitches": [accent]}]]))
                    with self.assertRaises(ValueError):
                        import_yomitan(archive, root / "packs")
