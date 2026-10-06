import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from meikipop.dictionary.library import Library, save_preferences


class RefreshTests(unittest.TestCase):
    def test_external_fallback_is_bounded_and_explicit_refresh_is_immediate(self):
        with tempfile.TemporaryDirectory() as temp:
            library = Library(temp)
            try:
                revision = library.revision
                with patch.object(library, "_inventory_signature", wraps=library._inventory_signature) as check:
                    for _ in range(100):
                        self.assertFalse(library.refresh_if_changed())
                    check.assert_not_called()
                    save_preferences(Path(temp), [], [])
                    library._next_inventory_check = 0
                    self.assertTrue(library.refresh_if_changed())
                    self.assertGreater(library.revision, revision)
                    revision = library.revision
                    library.refresh()
                    self.assertGreater(library.revision, revision)
            finally:
                library.close()
