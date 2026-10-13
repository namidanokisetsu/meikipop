import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from meikipop.dictionary.library import Library, import_yomitan, save_preferences
from meikipop.dictionary.pitch import (PITCH_DATA, PITCH_OBJECT, PITCH_PREFIX, Pitch, install_pitch_renderer,
                                      levels, morae, nasal_mora, pitch_category, pitch_format, pitch_payload,
                                      render_pitches)


class PitchTests(unittest.TestCase):
    def test_morae_and_pitch_patterns(self):
        self.assertEqual(morae("きょうアームいっぽん"), ("きょ", "う", "ア", "ー", "ム", "い", "っ", "ぽ", "ん"))
        for position, expected in ((0, (False, True, True, True)), (1, (True, False, False, False)),
                                   (2, (False, True, False, False)), (3, (False, True, True, False)),
                                   ("LHHH", (False, True, True, True))):
            self.assertEqual(levels(Pitch("Pitch", "おとこ", position)), expected)
        self.assertEqual(pitch_payload(self.href(Pitch("Pitch", "おとこ", "LHH")))["position"], "LHH")
        self.assertEqual(pitch_payload(self.href(Pitch("Pitch", "おとこ", 3)))["position"], 3)
        self.assertNotIn("&lt;source&gt;", render_pitches([Pitch("<source>", "あ", 1)]))

    @staticmethod
    def href(pitch):
        import re
        return re.search(r'href="([^"]+)"', render_pitches([pitch]))[1]

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
        self.assertNotIn("devoiced:", html)
        self.assertNotIn("nasal:", html)
        self.assertIn('devoice%22%3A%5B1%5D', html)
        self.assertIn("&lt;rare&gt;", html)

    def test_category_and_phonetic_markers_keep_original_reading(self):
        for position, category in ((0, "heiban"), (1, "atamadaka"), (2, "nakadaka"),
                                   (3, "odaka"), ("LHHH", "heiban"), ("LHLL", "nakadaka"),
                                   ("LHL", None), ("HHH", None), (4, None)):
            self.assertEqual(pitch_category(Pitch("NHK", "おとこ", position)), category)
        self.assertEqual(nasal_mora("ぎゃ"), "きゃ")
        self.assertEqual(nasal_mora("ガ"), "カ")
        payload = pitch_payload(self.href(Pitch("NHK", "きがん", 1, nasal=(2,), devoice=(1,))))
        self.assertEqual(payload, dict(reading="きがん", position=1, nasal=[2], devoice=[1]))
        for href in ("https://example.test", PITCH_PREFIX + "%7Bbroken",
                     PITCH_PREFIX + '%7B%22reading%22%3A%22x%22%2C%22position%22%3Atrue%7D'):
            self.assertIsNone(pitch_payload(href))

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


class PitchPainterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_small_native_annotations_draw_marks_and_preserve_copy_base(self):
        from unittest.mock import patch
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QTextCharFormat, QTextDocument, QTextFormat
        from meikipop.config.config import config
        document = QTextDocument()
        document.setDefaultFont(QFont("Yu Gothic UI"))
        font = QFont(document.defaultFont())
        font.setPixelSize(12)
        char_format = QTextCharFormat()
        char_format.setFont(font)
        renderer = install_pitch_renderer(document, document)
        payload = dict(reading="きがん", position=0, nasal=[2], devoice=[1])
        fmt = pitch_format(char_format, payload)
        self.assertEqual(fmt.objectType(), QTextFormat.ObjectTypes.UserObject.value + 2)
        self.assertEqual(PITCH_DATA, QTextFormat.Property.UserProperty.value + 4)
        self.assertEqual(fmt.property(QTextFormat.Property.UserProperty.value + 1), "きがん [0]")
        self.assertEqual(json.loads(fmt.property(PITCH_DATA)), payload)
        cells = renderer.layout(document, fmt)[4]
        self.assertEqual(cells[0][5:], (False, True))
        self.assertEqual(cells[1][0], "か")
        self.assertEqual(cells[1][5:], (True, False))
        for background in ("#ffffff", "#000000"):
            with self.subTest(background=background), patch.object(config, "color_background", background):
                size = renderer.intrinsicSize(document, 0, fmt)
                image = QImage(160, 40, QImage.Format.Format_ARGB32)
                image.fill(QColor(background))
                painter = QPainter(image)
                renderer.drawObject(painter, QRectF(4, 4, size.width(), size.height()), document, 0, fmt)
                painter.end()
                colors = [image.pixelColor(x, y) for y in range(40) for x in range(160)]
                self.assertTrue(any(color.blue() > color.red() * 1.25 for color in colors))
                self.assertTrue(any(color.red() > color.green() * 1.25 and color.blue() < color.green()
                                    for color in colors))

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
            db.close()

            for accent in ({"position": True}, {"position": 0, "nasal": "bad"},
                           {"position": 0, "tags": "bad"}):
                with self.subTest(accent=accent):
                    with zipfile.ZipFile(archive, "w") as output:
                        output.writestr("index.json", json.dumps(dict(title="Invalid", format=3)))
                        output.writestr("term_meta_bank_1.json", json.dumps([
                            ["", "pitch", {"reading": "ねこ", "pitches": [accent]}]]))
                    with self.assertRaises(ValueError):
                        import_yomitan(archive, root / "packs")
