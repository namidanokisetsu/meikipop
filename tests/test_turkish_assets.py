import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from meikipop.dictionary.turkish_assets import activate, validate, write_manifest
from meikipop.dictionary.turkish_wiktionary import build, WiktionaryStore
from meikipop.dictionary.turkish_lookup import TextResult
from meikipop.gui.turkish.rendering import render_result


class AssetTests(unittest.TestCase):
    def test_yomitan_import_and_source_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.zip"
            index = dict(format=3, sourceLanguage="tr", targetLanguage="en", revision="fixture-1")
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(index))
                output.writestr("term_bank_1.json", json.dumps([["kitap", "", "n", "", 0,
                    [{"type": "structured-content", "content": {"tag": "div", "content": "a book <test>"}}], 0, ""]]))
            build(archive, root / "dictionary.sqlite3")
            store = WiktionaryStore(root / "dictionary.sqlite3")
            try:
                entries = store.lookup(["KİTAP", "kitap"])
            finally:
                store.close()
            self.assertEqual(len(entries), 1)
            tdk = dict(headword="kitap", senses=[], relations=[])
            result = TextResult("kitap", (), None, (tdk,), "", wiktionary=entries)
            html = render_result(result, source_order=["Wiktionary", "KeNet", "TDK"])
            self.assertLess(html.index("Wiktionary"), html.index("TDK"))
            self.assertIn("a book &lt;test&gt;", html)
            index["targetLanguage"] = "ja"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(index))
            with self.assertRaises(ValueError):
                build(archive, root / "dictionary.sqlite3")
            self.assertTrue((root / "dictionary.sqlite3").exists())

    def test_activation_retains_previous_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, stage = root / "current", root / "stage"
            for directory, text in ((target, "old"), (stage, "new")):
                directory.mkdir()
                (directory / "data").write_text(text)
                write_manifest(directory, "fixture")
            activate(stage, target)
            validate(target)
            self.assertEqual((root / "current.previous/data").read_text(), "old")
            (target / "data").write_text("broken")
            with self.assertRaises(ValueError):
                validate(target)
