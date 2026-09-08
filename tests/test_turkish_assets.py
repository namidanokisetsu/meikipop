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
    def test_dictionary_popup_formatting(self):
        def glosses(*texts):
            example = {"tag": "details", "data": {"content": "details-entry-examples"}, "content": [
                {"tag": "summary", "data": {"content": "summary-entry"}, "content": "1 example"},
                {"tag": "div", "data": {"content": "extra-info"}, "content": {
                    "tag": "div", "data": {"content": "example-sentence"}, "content": [
                        {"tag": "div", "data": {"content": "example-sentence-a"}, "content": "Turkish example"},
                        {"tag": "div", "data": {"content": "example-sentence-b"}, "content": "English translation"},
                ]}},
            ]
            }
            items = []
            for text in texts:
                content = {"tag": "div", "content": [text, example]} if text == "gloss 1" else text
                items.append({"tag": "li", "content": content})
            return {"type": "structured-content", "content": {
                "tag": "ol", "data": {"content": "glosses"},
                "content": items}}

        wikt = dict(word="istemek", pos="v vt", tags=[], definitions=[glosses(
            "gloss 1", "gloss 2", "gloss 3", "gloss 4", "gloss 5", "gloss 6")])
        nonlemma = dict(word="istesem", pos="non-lemma", tags=[], definitions=[])
        senses = [{"text": f"TDK {i}", "labels": [], "examples": []} for i in range(1, 7)]
        senses[0]["examples"] = [{"text": "quote one", "author": "Author"},
                                  {"text": "quote two", "author": ""}]
        tdk = dict(headword="istemek", senses=senses, relations=[])
        result = TextResult("istemek", (), None, (tdk,), "", wiktionary=(nonlemma, wikt))

        preview = render_result(result)
        self.assertNotIn("non-lemma", preview)
        self.assertNotIn("istesem", preview)
        self.assertIn("verb · transitive", preview)
        self.assertNotIn("1 example", preview)
        self.assertNotIn("Example:", preview)
        self.assertLess(preview.index("gloss 1"), preview.index("Turkish example"))
        self.assertLess(preview.index("Turkish example"), preview.index("English translation"))
        self.assertIn('class="example wiktionary-example-tr"', preview)
        self.assertIn('class="example wiktionary-example-en"', preview)
        self.assertIn("font-size:inherit", preview)
        self.assertNotIn(".example {font-size:small", preview)
        self.assertIn("quote one", preview)
        self.assertIn("quote two", preview)
        self.assertIn("gloss 5", preview)
        self.assertNotIn("gloss 6", preview)
        self.assertIn("Show more", preview)
        self.assertNotIn("Show less", preview)

        expanded = render_result(result, show_more=True)
        self.assertIn("gloss 6", expanded)
        self.assertIn("TDK 6", expanded)
        self.assertIn("Author", expanded)
        self.assertIn("Show less", expanded)

    def test_kenet_popup_keeps_all_examples_but_limits_meaning_groups(self):
        groups = []
        for i in range(1, 7):
            groups.append({
                "definition": f"Meaning {i}", "pos": "n", "members": [{"spelling": f"term{i}"}],
                "matched_members": [], "relations": [], "example": "first|second",
            })
        result = TextResult("word", (), None, (), "", wordnet=tuple(groups))
        preview = render_result(result)
        self.assertIn("Meaning 5", preview)
        self.assertNotIn("Meaning 6", preview)
        self.assertIn("first", preview)
        self.assertIn("second", preview)
        self.assertIn('class="term"', preview)
        expanded = render_result(result, show_more=True)
        self.assertIn("Meaning 6", expanded)

    def test_wiktionary_nonlemma_lookup_adds_referenced_lemma(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.zip"
            index = dict(format=3, sourceLanguage="tr", targetLanguage="en", revision="fixture-1")
            rows = [
                ["istemek", "", "v vt", "", 0, ["to want"], 0, ""],
                ["istesem", "", "non-lemma", "", 0, [["istemek", ["conditional"]]], 0, ""],
            ]
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(index))
                output.writestr("term_bank_1.json", json.dumps(rows))
            build(archive, root / "dictionary.sqlite3")
            store = WiktionaryStore(root / "dictionary.sqlite3")
            try:
                entries = store.lookup(["istesem"])
            finally:
                store.close()
        self.assertEqual([entry["word"] for entry in entries], ["istesem", "istemek"])

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
