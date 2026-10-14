import tempfile
import unittest
from pathlib import Path

import meikipop.config.config as config_module


class ConfigTests(unittest.TestCase):
    def test_old_hotkey_does_not_override_activation_bindings(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "config.ini"
            path.write_text("[Settings]\nhotkey = ctrl+alt\n", encoding="utf-8")
            old_path = config_module.CONFIG_PATH
            old_instance = config_module.Config._instance
            try:
                config_module.CONFIG_PATH = str(path)
                config_module.Config._instance = None
                settings = config_module.Config()
                self.assertEqual(settings.activation_bindings, "shift,middle")
            finally:
                config_module.CONFIG_PATH = old_path
                config_module.Config._instance = old_instance

    def test_new_install_gets_shift_and_middle_defaults(self):
        with tempfile.TemporaryDirectory() as tempdir:
            old_path = config_module.CONFIG_PATH
            old_instance = config_module.Config._instance
            try:
                config_module.CONFIG_PATH = str(Path(tempdir) / "not-created.ini")
                config_module.Config._instance = None
                fresh = config_module.Config()
                self.assertEqual(fresh.activation_bindings, "shift,middle")
                self.assertEqual(fresh.theme_name, "Dark")
        self.assertEqual(fresh.background_opacity, 230)
                self.assertTrue(fresh.pitch_colors)
                self.assertTrue(fresh.kanji_stroke_order)
            finally:
                config_module.CONFIG_PATH = old_path
                config_module.Config._instance = old_instance

    def test_saved_legacy_dark_name_and_pitch_preference_round_trip(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "config.ini"
            path.write_text("[Theme]\ntheme_name = Monochrome Dark\npitch_colors = false\nkanji_stroke_order = false\nbackground_opacity = 128\n", encoding="utf-8")
            old_path, old_instance = config_module.CONFIG_PATH, config_module.Config._instance
            try:
                config_module.CONFIG_PATH = str(path)
                config_module.Config._instance = None
                saved = config_module.Config()
                self.assertEqual(saved.theme_name, "Dark")
                self.assertEqual(saved.background_opacity, 128)
                self.assertFalse(saved.pitch_colors)
                self.assertFalse(saved.kanji_stroke_order)
                saved.save()
                config_module.Config._instance = None
                restored = config_module.Config()
                self.assertEqual(restored.theme_name, "Dark")
                self.assertFalse(restored.pitch_colors)
                self.assertFalse(restored.kanji_stroke_order)
            finally:
                config_module.CONFIG_PATH, config_module.Config._instance = old_path, old_instance


if __name__ == "__main__":
    unittest.main()
