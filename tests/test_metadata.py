import io
import json
import unittest
import zipfile

from meikipop.dictionary.metadata import Frequency, frequency_rows, harmonic_rank, kanji_rows


def archive_for(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, rows in files.items():
            archive.writestr(name, json.dumps(rows, ensure_ascii=False))
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


class MetadataTests(unittest.TestCase):
    def test_harmonic_rank_weights_dictionaries_equally(self):
        frequencies = (Frequency("A", 100, "100"), Frequency("A", 900, "900㋕"),
                       Frequency("B", 400, "400"))
        self.assertEqual(harmonic_rank(frequencies * 2), 160)
        self.assertEqual(harmonic_rank(frequencies[:2]), 100)

    def test_harmonic_rank_excludes_counts_labels_and_invalid_ranks(self):
        frequencies = (Frequency("Count", 10000, "10000", mode="occurrence-based"),
                       Frequency("Band", None, "common"), Frequency("Zero", 0, "0"),
                       Frequency("Bad", float("nan"), ""), Frequency("Infinite", float("inf"), ""))
        self.assertIsNone(harmonic_rank(frequencies))
        self.assertEqual(harmonic_rank((*frequencies, Frequency("Rank", 50, "50"))), 50)

    def test_frequency_shapes_preserve_reading_display_and_numeric_value(self):
        rows = [["猫", "freq", 42], ["猫", "freq", "1,234"], ["猫", "freq", "common"],
                ["猫", "freq", {"value": 12, "displayValue": "12★"}],
                ["猫", "freq", {"reading": "ねこ", "frequency": {"value": 8, "displayValue": "8㊤"}}],
                ["猫", "freq", {"reading": "ねこま", "frequency": 90000}],
                ["猫", "pitch", {"reading": "ねこ", "pitches": []}]]
        with archive_for({"term_meta_bank_1.json": rows}) as archive:
            result = list(frequency_rows(archive))
        self.assertEqual(result, [("猫", "", 42, "42"), ("猫", "", 1234, "1,234"),
                                  ("猫", "", None, "common"), ("猫", "", 12, "12★"),
                                  ("猫", "ねこ", 8, "8㊤"), ("猫", "ねこま", 90000, "90000")])

    def test_banks_are_numeric_order_and_metadata_does_not_require_terms(self):
        with archive_for({"term_meta_bank_10.json": [["十", "freq", 10]],
                          "term_meta_bank_2.json": [["二", "freq", 2]]}) as archive:
            self.assertEqual([row[0] for row in frequency_rows(archive)], ["二", "十"])

    def test_invalid_numeric_and_reading_metadata_are_rejected(self):
        for value in (True, -1, float("inf"), {"frequency": 2}, {"value": "2"}, {"value": 2, "displayValue": 3}):
            with self.subTest(value=value), archive_for({"term_meta_bank_1.json": [["猫", "freq", value]]}) as archive:
                with self.assertRaises(ValueError):list(frequency_rows(archive))

    def test_kanji_readings_meanings_tags_and_stats_are_preserved(self):
        with archive_for({"kanji_bank_1.json": [["猫", "ビョウ", "ねこ", "jouyou", ["cat"], {"strokes": "11", "grade": "8"}]]}) as archive:
            rows = list(kanji_rows(archive))
        self.assertEqual(rows, [("猫", {"onyomi": ["ビョウ"], "kunyomi": ["ねこ"], "tags": ["jouyou"],
                                      "meanings": ["cat"], "stats": {"strokes": "11", "grade": "8"}})])

    def test_legacy_kanji_format_and_cancellation(self):
        with archive_for({"kanji_bank_1.json": [["読", "ドク", "よ.む", "", "read", "study"]]}) as archive:
            self.assertEqual(list(kanji_rows(archive))[0][1]["meanings"], ["read", "study"])
            with self.assertRaises(InterruptedError):list(kanji_rows(archive, cancelled=lambda: True))

    def test_kanji_invalid_shapes_fail_before_partial_import(self):
        for row in (["猫", "ビョウ", "ねこ", "", ["cat"]], ["猫", "ビョウ", "ねこ", "", [1], {}],
                    ["猫", "ビョウ", "ねこ", "", ["cat"], {"strokes": 11}]):
            with self.subTest(row=row), archive_for({"kanji_bank_1.json": [row]}) as archive:
                with self.assertRaises(ValueError):list(kanji_rows(archive))


if __name__ == "__main__":
    unittest.main()
