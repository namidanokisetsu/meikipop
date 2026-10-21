import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from meikipop.dictionary.library import import_yomitan, save_preferences
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


class JapaneseRankingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "library"

    @staticmethod
    def word(term, reading, rule="", score=0, gloss="fixture"):
        return [term, reading, "", rule, score, [gloss], -1, ""]

    def install(self, title, words=(), frequencies=(), **metadata):
        archive = self.root / (title + ".zip")
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("index.json", json.dumps(dict(
                title=title, format=3, sourceLanguage="ja", **metadata)))
            if words:
                output.writestr("term_bank_1.json", json.dumps(words))
            if frequencies:
                output.writestr("term_meta_bank_1.json", json.dumps(frequencies))
        return import_yomitan(archive, self.directory)

    def engine(self):
        engine = SearchEngine(self.directory)
        self.addCleanup(engine.close)
        return engine

    def test_kana_headword_precedes_reading_match_without_frequency_data(self):
        self.install("Words", [self.word("荒れ", "あれ", score=100), self.word("あれ", "あれ")])
        engine = self.engine()
        for _ in range(2):
            result = engine.search("あれ", source="ja")
            self.assertEqual([entry.term for entry in result.entries], ["あれ", "荒れ"])

    def test_frequency_ranks_homophones_and_ignores_occurrence_counts(self):
        self.install("Words", [self.word("箸", "はし", score=100), self.word("橋", "はし")])
        self.install("Ranks", frequencies=[["箸", "freq", 2000], ["橋", "freq", 20]])
        self.install("Counts", frequencies=[["箸", "freq", 1]], frequencyMode="occurrence-based")
        self.assertEqual([entry.term for entry in self.engine().search("はし", source="ja").entries],
                         ["橋", "箸"])

    def test_kana_ranking_uses_installed_frequency_metadata(self):
        self.install("Words", [self.word("荒れ", "あれ"), self.word("あれ", "あれ")])
        self.install("Ranks", frequencies=[["荒れ", "freq", 38009], ["あれ", "freq", 265]])
        self.assertEqual([entry.term for entry in self.engine().search("あれ", source="ja").entries],
                         ["あれ", "荒れ"])

    def test_frequent_verb_can_precede_direct_reading_homograph(self):
        self.install("Words", [self.word("下", "した"), self.word("する", "する", "vs")])
        self.install("Ranks", frequencies=[["下", "freq", 1000], ["する", "freq", 10]])
        entries = self.engine().search("した", source="ja").entries
        self.assertEqual([entry.term for entry in entries], ["する", "下"])
        self.assertEqual(entries[0].inflection, ("past",))

    def test_fewer_deconjugation_steps_win_equal_frequency(self):
        self.install("Words", [self.word("食べる", "たべる", "v1"),
                               self.word("食べられる", "たべられる", "v1")])
        self.install("Ranks", frequencies=[["食べる", "freq", 100], ["食べられる", "freq", 100]])
        entries = self.engine().search("食べられた", source="ja").entries
        self.assertEqual([entry.term for entry in entries], ["食べられる", "食べる"])

    def test_duplicate_senses_keep_every_source_in_preference_order(self):
        a = self.install("A", [self.word("あれ", "あれ", gloss=str(i)) for i in range(61)])
        b = self.install("B", [self.word("あれ", "あれ", gloss="other source")])
        save_preferences(self.directory, [], [b.name, a.name])
        entries = self.engine().search("あれ", source="ja").entries
        self.assertEqual([entry.source for entry in entries], ["B"] + ["A"] * 61)
        self.assertEqual({entry.definitions for entry in entries},
                         {("other source",), *((str(i),) for i in range(61))})

    def test_ranking_precedes_lexical_group_limit(self):
        self.install("Words", [*[self.word(f"語{i}", "あれ", score=100) for i in range(65)],
                               self.word("あれ", "あれ")])
        entries = self.engine().search("あれ", source="ja").entries
        self.assertEqual(entries[0].term, "あれ")
        self.assertEqual(len({(entry.term, entry.reading) for entry in entries}), 60)


if __name__ == "__main__":
    unittest.main()
