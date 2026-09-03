import tempfile
import unittest
from pathlib import Path

import meikipop.config.config as config_module


class ConfigMigrationTests(unittest.TestCase):
    def test_legacy_hotkey_becomes_one_activation_binding(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "config.ini"
            path.write_text("[Settings]\nhotkey = ctrl+alt\n", encoding="utf-8")
            old_path = config_module.CONFIG_PATH
            old_instance = config_module.Config._instance
            try:
                config_module.CONFIG_PATH = str(path)
                config_module.Config._instance = None
                migrated = config_module.Config()
                self.assertEqual(migrated.activation_bindings, "ctrl+alt")
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
            finally:
                config_module.CONFIG_PATH = old_path
                config_module.Config._instance = old_instance


if __name__ == "__main__":
    unittest.main()
