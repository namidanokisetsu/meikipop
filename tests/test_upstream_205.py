"""Regression coverage for upstream v2.0.5 commits 44171ba and 0dbb499."""
import os
from pathlib import Path
import pickle
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meikipop.dictionary import customdict


class DictionaryValidationCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "dictionary.pkl"
        self.path.write_bytes(pickle.dumps({"entries": {1: []}, "lookup_map": {"word": [("word", None, 1, 1)]}}))
        self.config = SimpleNamespace(validated_dict_ts=-1, validated_dict_signature="", save=Mock())
        patcher = patch.object(customdict, "config", self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_upstream_44171ba_skips_unchanged_dictionary_validation(self):
        first = customdict.Dictionary()
        with patch.object(first, "_validate", wraps=first._validate) as validate:
            self.assertTrue(first.load_dictionary(self.path))
            validate.assert_called_once_with()
        second = customdict.Dictionary()
        with patch.object(second, "_validate", wraps=second._validate) as validate:
            self.assertTrue(second.load_dictionary(self.path))
            validate.assert_not_called()
        self.config.save.assert_called_once_with()

    def test_changed_file_is_validated_again(self):
        self.assertTrue(customdict.Dictionary().load_dictionary(self.path))
        stamp = self.path.stat().st_mtime_ns + 1_000_000_000
        os.utime(self.path, ns=(stamp, stamp))
        second = customdict.Dictionary()
        with patch.object(second, "_validate", wraps=second._validate) as validate:
            self.assertTrue(second.load_dictionary(self.path))
            validate.assert_called_once_with()

    def test_equal_timestamp_on_different_path_does_not_reuse_validation(self):
        self.assertTrue(customdict.Dictionary().load_dictionary(self.path))
        other = self.path.with_name("different.pkl")
        other.write_bytes(self.path.read_bytes())
        stamp = self.path.stat().st_mtime_ns
        os.utime(other, ns=(stamp, stamp))
        second = customdict.Dictionary()
        with patch.object(second, "_validate", wraps=second._validate) as validate:
            self.assertTrue(second.load_dictionary(other))
            validate.assert_called_once_with()

    def test_failed_validation_is_never_cached(self):
        for _ in range(2):
            dictionary = customdict.Dictionary()
            with patch.object(dictionary, "_validate", return_value=1) as validate:
                self.assertTrue(dictionary.load_dictionary(self.path))
                validate.assert_called_once_with()
        self.assertEqual(self.config.validated_dict_ts, -1)
        self.assertEqual(self.config.validated_dict_signature, "")

    def test_cache_write_failure_does_not_disable_a_loaded_dictionary(self):
        self.config.save.side_effect = OSError("read-only settings")
        dictionary = customdict.Dictionary()
        with self.assertLogs(customdict.logger, level="WARNING"):
            self.assertTrue(dictionary.load_dictionary(self.path))
        self.assertIn("word", dictionary.lookup_map)


class FullscreenPopupTests(unittest.TestCase):
    def test_upstream_0dbb499_bypass_is_limited_to_x11(self):
        from PyQt6.QtCore import Qt
        from meikipop.gui import popup

        for platform in ("xcb", "windows", "cocoa", "wayland"):
            with self.subTest(platform=platform), patch.object(popup.QApplication, "platformName", return_value=platform):
                flags = popup._popup_window_flags()
                self.assertEqual(bool(flags & Qt.WindowType.X11BypassWindowManagerHint), platform == "xcb")
                self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)


if __name__ == "__main__":
    unittest.main()
