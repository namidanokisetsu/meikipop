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
        self.assertIn("&lt;source&gt;", render_pitches([Pitch("<source>", "あ", 1)]))

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
