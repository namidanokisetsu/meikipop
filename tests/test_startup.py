import sys
import types
import unittest
from unittest.mock import patch

from meikipop.utils import startup


class _Key:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(), KEY_SET_VALUE=1, REG_SZ=1,
            CreateKeyEx=lambda *_args: _Key(),
            OpenKey=self._open_key,
            SetValueEx=lambda _key, name, _reserved, _kind, value: self.values.__setitem__(name, value),
            QueryValueEx=lambda _key, name: (self.values[name], 1),
            DeleteValue=lambda _key, name: self.values.pop(name),
        )

    def _open_key(self, *_args):
        if not self.values:
            raise FileNotFoundError
        return _Key()

    def test_enable_query_and_disable(self):
        with patch.object(startup.sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": self.winreg}):
            startup.set_startup_enabled(True)
            self.assertIn("meikipop", self.values)
            self.assertTrue(startup.is_startup_enabled())
            startup.set_startup_enabled(False)
            self.assertFalse(self.values)

    def test_packaged_command_quotes_executable(self):
        with patch.object(startup.sys, "executable", r"C:\Program Files\meikipop\meikipop.exe"), \
                patch.object(startup.sys, "frozen", True, create=True):
            self.assertEqual(
                startup.startup_command(),
                '"C:\\Program Files\\meikipop\\meikipop.exe"',
            )


if __name__ == "__main__":
    unittest.main()
