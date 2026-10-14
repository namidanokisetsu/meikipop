from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from meikipop.language.turkish_ranking import FILENAME, load_counts, read_counts, write_counts


class TurkishRankingTests(unittest.TestCase):
    def test_bundled_and_cached_counts_skip_corpus_analysis(self):
        with tempfile.TemporaryDirectory() as directory, patch('meikipop.utils.paths.paths') as paths:
            paths.cache_dir = directory
            paths.get_resource_path.return_value = str(Path(directory) / 'bundle')
            compute = Mock(return_value={'ev_Noun': 3})
            self.assertEqual(load_counts(compute), compute.return_value)
            self.assertEqual(load_counts(compute), compute.return_value)
            compute.assert_called_once_with()
            write_counts(Path(paths.get_resource_path.return_value) / FILENAME, {'ev_Noun': 4})
            self.assertEqual(load_counts(compute), {'ev_Noun': 4})
            compute.assert_called_once_with()

    def test_cached_counts_round_trip_and_replace_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ranking' / 'counts.json'
            self.assertIsNone(read_counts(path))
            write_counts(path, {'kırk_Num': 2, 'ev_Noun': 3})
            self.assertEqual(read_counts(path), {'kırk_Num': 2, 'ev_Noun': 3})
            write_counts(path, {'ev_Noun': 4})
            self.assertEqual(read_counts(path), {'ev_Noun': 4})
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'counts.json'
            for content in ('{', '[]', '{}', '{"ev":true}', '{"ev":-1}', '{"ev":"2"}'):
                path.write_text(content, encoding='utf-8')
                self.assertIsNone(read_counts(path), content)
