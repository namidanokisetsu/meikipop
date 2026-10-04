"""Exercise metadata packs through the real atomic importer and lookup API."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from meikipop.dictionary.library import Library, import_yomitan, save_preferences
from meikipop.dictionary.search import SearchEngine


class LibraryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "library"
        self.serial = 0

    def install(self, title, banks, language="ja", **index):
        self.serial += 1
        archive = self.root / f"pack-{self.serial}.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("index.json", json.dumps(dict(
                title=title, format=3, sourceLanguage=language, **index)))
            for name, rows in banks.items():
                output.writestr(name + ".json", json.dumps(rows, ensure_ascii=False))
        return import_yomitan(archive, self.directory)

    def library(self):
        library = Library(self.directory)
        self.addCleanup(library.close)
        self.assertFalse(library.errors)
        return library

    @staticmethod
    def word(term, reading, gloss):
        return [term, reading, "", "", 0, [gloss], -1, ""]

    def install_words(self):
        return self.install("Words", {"term_bank_1": [
            self.word("生", "せい", "life"), self.word("生", "なま", "raw"),
            self.word("日本語", "にほんご", "Japanese language")]})

    def test_frequency_only_pack_attaches_generic_and_matching_reading(self):
        self.install_words()
        self.install("Frequency", {"term_meta_bank_1": [
            ["生", "freq", 80],
            ["生", "freq", {"reading": "せい", "frequency": {"value": 12, "displayValue": "12 ★"}}],
            ["生", "freq", {"reading": "なま", "frequency": "common"}],
            ["生", "pitch", {"reading": "せい", "pitches": [{"position": 1}]}]]})
        library = self.library()
        metadata = next(meta for _, meta, _ in library.packs if meta["title"] == "Frequency")
        self.assertEqual((metadata["entries"], metadata["frequencies"]), ("0", "3"))
        entries = {entry.reading: entry for entry in library.lookup("生")}
        self.assertEqual([(f.rank, f.label) for f in entries["せい"].frequencies], [(80, "80"), (12, "12 ★")])
        self.assertEqual([(f.rank, f.label) for f in entries["なま"].frequencies], [(80, "80"), (None, "common")])
        self.assertEqual([f.rank for f in library.frequencies("生")], [80])
        self.assertEqual([f.label for f in library.reverse("raw")[0].frequencies], ["80", "common"])
        self.assertEqual(entries["せい"].definitions, ("life",))

    def test_frequency_language_normalization_mode_and_disable(self):
        self.install("TR Words", {"term_bank_1": [self.word("IŞIK", "", "light")]}, language="tr")
        frequency_pack = self.install("TR Counts", {"term_meta_bank_1": [["ışık", "freq", 740]]},
                                      language="tr", frequencyMode="occurrence-based")
        self.install("Other language", {"term_meta_bank_1": [["ışık", "freq", 999]]}, language="ja")
        library = self.library()
        entry, = library.lookup("ışık", "tr")
        self.assertEqual([(f.source, f.rank, f.mode) for f in entry.frequencies],
                         [("TR Counts", 740, "occurrence-based")])
        save_preferences(self.directory, [frequency_pack.name], [])
        self.assertTrue(library.refresh_if_changed())
        self.assertEqual(library.lookup("IŞIK", "tr")[0].frequencies, ())

    def test_kanji_only_pack_roundtrip_and_compound_selection(self):
        self.install_words()
        kanji_pack = self.install("Kanji", {"kanji_bank_1": [
            ["日", "ニチ ジツ", "ひ -び", "grade1", ["day", "sun"], {"stroke-count": "4", "freq": "1"}],
            ["本", "ホン", "もと", "grade1", ["book", "origin"], {"stroke-count": "5"}],
            ["語", "ゴ", "かた.る", "grade2", ["language"], {}]]})
        library = self.library()
        metadata = next(meta for _, meta, _ in library.packs if meta["title"] == "Kanji")
        self.assertEqual((metadata["entries"], metadata["kanji"]), ("0", "3"))
        entries = library.kanji_info("日本語、日本")
        self.assertEqual([entry.character for entry in entries], list("日本語"))
        first = entries[0]
        self.assertEqual((first.source, first.onyomi, first.kunyomi, first.meanings, first.tags),
                         ("Kanji", ("ニチ", "ジツ"), ("ひ", "-び"), ("day", "sun"), ("grade1",)))
        self.assertEqual(dict(first.stats), {"stroke-count": "4", "freq": "1"})
        engine = SearchEngine(self.directory)
        self.addCleanup(engine.close)
        result = engine.search("日本語", source="ja")
        self.assertEqual(result.entries[0].term, "日本語")
        self.assertEqual([entry.character for entry in result.kanji], list("日本語"))
        save_preferences(self.directory, [kanji_pack.name], [])
        library.refresh_if_changed()
        self.assertEqual(library.kanji_info("日本語"), ())

    def test_supplementary_and_compatibility_kanji_are_queryable(self):
        self.install("Rare Kanji", {"kanji_bank_1": [
            ["𠮷", "キチ", "よし", "", ["good luck"], {}],
            ["神", "シン", "かみ", "", ["god"], {}]]})
        self.assertEqual([entry.character for entry in self.library().kanji_info("𠮷神𠮷")], ["𠮷", "神"])

    def test_bad_metadata_does_not_publish_or_replace_a_healthy_pack(self):
        original = self.install_words()
        before = original.read_bytes()
        with self.assertRaises(ValueError):
            self.install("Words", {
                "term_bank_1": [self.word("新", "しん", "new")],
                "term_meta_bank_1": [["新", "freq", 12], ["生", "freq", {"value": True}]]}, revision="bad")
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(list(self.directory.glob("*.sqlite3")), [original])
        self.assertEqual(list(self.directory.glob(".import-*")), [])
        library = self.library()
        self.assertTrue(library.lookup("生"))
        self.assertFalse(library.lookup("新"))

    def test_invalid_kanji_metadata_rolls_back_frequency_bank(self):
        with self.assertRaises(ValueError):
            self.install("Bad metadata", {
                "term_meta_bank_1": [["日", "freq", 1]],
                "kanji_bank_1": [["日", "ニチ", "ひ", "", ["day"], {"stroke-count": [4]}]]})
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
