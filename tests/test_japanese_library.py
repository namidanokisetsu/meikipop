import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from meikipop.dictionary.library import import_yomitan
from meikipop.dictionary.search import SearchEngine


class JapaneseLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        words = [("読む", "よむ", "v5"), ("行く", "いく", "v5"), ("走る", "はしる", "v5"),
                 ("書く", "かく", "v5"), ("有る", "ある", "v5"), ("食べる", "たべる", "v1"),
                 ("来る", "くる", "vk"), ("する", "する", "vs"), ("暑い", "あつい", "adj-i"),
                 ("行", "ぎょう", ""), ("走", "そう", ""), ("書", "しょ", ""), ("来", "らい", ""),
                 ("下", "した", ""), ("仕手", "して", "")]
        for source in ("A", "B"):
            archive = directory / (source + ".zip")
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(dict(title=source, format=3, sourceLanguage="ja")))
                output.writestr("term_bank_1.json", json.dumps([[term, reading, "", rule, 0, ["fixture"], -1, ""]
                                                               for term, reading, rule in words]))
            import_yomitan(archive, directory / "library")
        self.engine = SearchEngine(directory / "library")
        self.addCleanup(self.engine.close)

    def test_yomitan_families_accept_common_conjugations(self):
        cases = [("読んでいる", "読む"), ("行かなかった", "行く"), ("走った", "走る"),
                 ("書けなかった", "書く"), ("有った", "有る"), ("食べました", "食べる"),
                 ("来ました", "来る"), ("しました", "する"), ("暑かった", "暑い")]
        for query, expected in cases:
            with self.subTest(query=query):
                entries = self.engine._japanese(query)
                self.assertEqual({entry.term for entry in entries}, {expected})
                self.assertTrue(all(entry.route == "inflected" for entry in entries))

    def test_intermediate_stems_do_not_become_noun_inflections(self):
        for query in ("行かなかった", "走った", "書けなかった", "来ました", "してください"):
            with self.subTest(query=query):
                entries = self.engine._japanese(query)
                self.assertTrue(entries)
                self.assertFalse(any(entry.term in {"行", "走", "書", "来", "仕手"} for entry in entries))

    def test_reading_homograph_keeps_direct_hit_and_valid_verb(self):
        entries = self.engine._japanese("した")
        self.assertEqual(entries[0].term, "下")
        self.assertIn("する", {entry.term for entry in entries})

    def test_source_order_and_unique_entries_are_preserved(self):
        entries = self.engine._japanese("行かなかった")
        self.assertEqual([entry.source for entry in entries], ["A", "B"])
        self.assertEqual(len({entry.id for entry in entries}), len(entries))

    def test_longest_prefix_can_be_inflected_at_sentence_start(self):
        entries = self.engine._japanese("読んでいるところです。")
        self.assertEqual({entry.term for entry in entries}, {"読む"})

    def test_inflection_labels_hide_intermediate_stems(self):
        self.assertEqual(self.engine._japanese("行かなかった")[0].inflection, ("negative", "past"))
        self.assertEqual(self.engine._japanese("読んでいる")[0].inflection, ("progressive",))


if __name__ == "__main__":
    unittest.main()
