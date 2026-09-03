import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from meikipop.audio.repository import AudioRepository, AudioRepositoryError
from meikipop.audio.worker import AudioRequest, AudioWorker


SCHEMA = """
CREATE TABLE entries (
 id INTEGER PRIMARY KEY, expression TEXT NOT NULL, reading TEXT,
 source TEXT NOT NULL, speaker TEXT, display TEXT, file TEXT NOT NULL
);
CREATE TABLE android (
 id INTEGER PRIMARY KEY, file TEXT NOT NULL, source TEXT NOT NULL, data BLOB NOT NULL
);
CREATE INDEX entries_expression_reading ON entries(expression, reading);
CREATE INDEX android_file_source ON android(file, source);
"""


class AudioRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "audio fixture.db"
        connection = sqlite3.connect(self.path)
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO entries VALUES (?, ?, ?, ?, NULL, NULL, ?)",
            [
                (1, "食べる", "たべる", "secondary", "secondary.mp3"),
                (2, "食べる", "たべる", "preferred", "orphan.mp3"),
                (3, "食べる", "たべる", "preferred", "preferred.mp3"),
                (4, "かな", "かな", "equal", "equal.mp3"),
                (5, "かな", "", "empty", "empty.mp3"),
                (6, "かな", None, "null", "null.mp3"),
            ],
        )
        connection.executemany(
            "INSERT INTO android VALUES (?, ?, ?, ?)",
            [
                (1, "secondary.mp3", "secondary", b"secondary"),
                (2, "preferred.mp3", "preferred", b"preferred"),
                (3, "equal.mp3", "equal", b"equal"),
                (4, "empty.mp3", "empty", b"empty"),
                (5, "null.mp3", "null", b"null"),
            ],
        )
        connection.commit()
        connection.close()
        self.repository = AudioRepository()
        self.repository.open(str(self.path))

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def test_preference_and_orphan_fallback(self):
        clip = self.repository.load(7, "食べる", "たべる", ("preferred", "secondary"))
        self.assertEqual(clip.data, b"preferred")
        self.assertEqual(clip.activation_id, 7)

    def test_kana_reading_variants_are_explicitly_supported(self):
        for source, expected in (("equal", b"equal"), ("empty", b"empty"), ("null", b"null")):
            with self.subTest(source=source):
                clip = self.repository.load(1, "かな", "", (source,))
                self.assertEqual(clip.data, expected)

    def test_missing_entry(self):
        self.assertIsNone(self.repository.load(1, "不存在", "", ()))

    def test_connection_is_read_only(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.repository.connection.execute(
                "INSERT INTO android(file, source, data) VALUES ('x', 'x', X'00')"
            )

    def test_bad_path_and_schema(self):
        other = AudioRepository()
        with self.assertRaises(AudioRepositoryError):
            other.open(str(Path(self.tempdir.name) / "missing.db"))
        invalid = Path(self.tempdir.name) / "invalid.db"
        sqlite3.connect(invalid).close()
        with self.assertRaises(AudioRepositoryError):
            other.open(str(invalid))

    def test_worker_coalesces_pending_requests_and_stops_cleanly(self):
        clips = []
        ready = threading.Event()

        def receive(clip):
            clips.append(clip)
            ready.set()

        worker = AudioWorker(receive, lambda _status: None)
        worker.submit(AudioRequest(1, ("食べる", "たべる"), str(self.path), ("secondary",)))
        worker.submit(AudioRequest(2, ("かな", ""), str(self.path), ("equal",)))
        worker.start()
        self.assertTrue(ready.wait(2))
        worker.stop()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual([(clip.activation_id, clip.data) for clip in clips], [(2, b"equal")])


if __name__ == "__main__":
    unittest.main()
