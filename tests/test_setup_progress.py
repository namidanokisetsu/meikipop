import io
import json
from pathlib import Path
from queue import Queue
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from meikipop.dictionary.catalog import install_recommended, recommendations
from meikipop.dictionary.import_job import _worker
from meikipop.dictionary.library import import_yomitan
from meikipop.utils.progress import content_length, download_progress


TERM = ["word", "", "", "", 0, ["meaning"], 0, ""]
FREQUENCY = ["word", "freq", 10]
PITCH = ["word", "pitch", {"reading": "word", "pitches": [{"position": 0}]}]
KANJI = ["字", "ジ", "あざ", "", ["character"], {}]


class SetupProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "library"

    def archive(self, banks):
        path = self.root / "dictionary.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("index.json", json.dumps(dict(title="Fixture", format=3, sourceLanguage="ja")))
            for name, rows in banks.items():
                archive.writestr(name + ".json", json.dumps(rows))
        return path

    def test_import_percentages_cover_definitions_and_metadata_only_packs(self):
        variants = [{"term_bank_1": [TERM]}, {"term_meta_bank_1": [FREQUENCY]},
                    {"term_meta_bank_1": [PITCH]}, {"kanji_bank_1": [KANJI]},
                    {"term_bank_1": [TERM], "term_bank_2": [],
                     "term_meta_bank_1": [FREQUENCY, PITCH], "kanji_bank_1": [KANJI]}]
        for index, banks in enumerate(variants):
            with self.subTest(banks=banks):
                messages = []
                directory = self.directory / str(index)

                def progress(text):
                    messages.append(text)
                    if text.endswith("100%"):
                        self.assertTrue(list(directory.glob("*.sqlite3")))

                import_yomitan(self.archive(banks), directory, progress=progress)
                percentages = [int(re.search(r"(\d+)%$", text)[1]) for text in messages]
                self.assertEqual(percentages, sorted(percentages))
                self.assertEqual((percentages[0], percentages[-1]), (0, 100))
                self.assertEqual(percentages.count(100), 1)
                self.assertTrue(any(text.startswith("Indexing ") for text in messages))

    def test_single_large_bank_reports_progress_before_bank_completion(self):
        for name, row in (("term_bank_1", TERM), ("term_meta_bank_1", FREQUENCY)):
            with self.subTest(bank=name):
                messages = []
                import_yomitan(self.archive({name: [row] * 2501}), self.directory / name, progress=messages.append)
                percentages = {int(re.search(r"(\d+)%$", text)[1]) for text in messages}
                self.assertTrue(any(0 < percent < 30 for percent in percentages))
                self.assertIn(100, percentages)

    def test_cancellation_never_reports_complete_or_publishes_a_pack(self):
        cancelled = threading.Event()
        messages = []

        def progress(text):
            messages.append(text)
            if not text.endswith("0%"):
                cancelled.set()

        path = self.archive({"term_bank_1": [TERM], "term_bank_2": [TERM]})
        with self.assertRaises(InterruptedError):
            import_yomitan(path, self.directory, progress=progress, cancelled=cancelled.is_set)
        self.assertFalse(any(text.endswith("100%") for text in messages))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_worker_delivers_completion_even_when_updates_are_throttled(self):
        path = self.archive({"term_bank_1": [TERM]})
        messages = Queue()
        with patch("meikipop.dictionary.import_job.monotonic", return_value=1):
            _worker([path], self.directory, "ja", None, messages, threading.Event())
        updates = []
        while not messages.empty():
            updates.append(messages.get_nowait())
        self.assertIn(("progress", "Importing Fixture · 100%"), updates)
        self.assertTrue(updates[-1][1][1])

    def test_download_uses_percentage_when_length_is_known_and_bytes_otherwise(self):
        payload = self.archive({"term_bank_1": [TERM]}).read_bytes()
        for length in (str(len(payload)), None, "unknown", "-1"):
            with self.subTest(length=length):
                response = io.BytesIO(payload)
                response.headers = {"Content-Length": length} if length is not None else {}
                messages = []
                with patch("meikipop.dictionary.catalog.urlopen", return_value=response):
                    install_recommended(recommendations("ja")[0], self.directory, messages.append, threading.Event())
                downloads = [text for text in messages if text.startswith("Downloading ") and " · " in text]
                self.assertTrue(downloads)
                if length == str(len(payload)):
                    self.assertTrue(downloads[0].endswith("0%"))
                    self.assertTrue(downloads[-1].endswith("100%"))
                else:
                    self.assertTrue(all(text.endswith(" MB") for text in downloads))

    def test_unknown_and_overstated_download_sizes_have_readable_progress(self):
        self.assertEqual(content_length(io.BytesIO()), 0)
        self.assertEqual(download_progress("Dictionary", 2 * 1024**2, 0), "Downloading Dictionary · 2 MB")
        self.assertEqual(download_progress("Dictionary", 20, 10), "Downloading Dictionary · 100%")
