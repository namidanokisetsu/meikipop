import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ModelCacheTests(unittest.TestCase):
    def test_model_libraries_use_app_cache_without_shared_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            script = '''
import json, os, sys
from unittest.mock import patch
from types import SimpleNamespace
from meikipop.utils.model_cache import configure_model_cache
with patch("meikipop.utils.paths.paths", SimpleNamespace(cache_dir=sys.argv[1])):
    configure_model_cache()
from huggingface_hub import constants
from huggingface_hub.file_download import are_symlinks_supported
print(json.dumps([constants.HF_HUB_CACHE, constants.HF_XET_CACHE,
                  are_symlinks_supported(constants.HF_HUB_CACHE),
                  os.environ["PADDLE_PDX_CACHE_HOME"]]))
'''
            result = subprocess.run([sys.executable, "-c", script, folder],
                                    env={**os.environ, "HF_HUB_CACHE": "unused-shared-cache"},
                                    capture_output=True, text=True, check=True)
            hub, xet, symlinks, paddle = json.loads(result.stdout)
            for path in (hub, xet, paddle):
                self.assertTrue(Path(path).is_relative_to(folder))
            if sys.platform == "win32":
                self.assertFalse(symlinks)

    @unittest.skipUnless(sys.platform == "win32", "Windows installer mutex")
    def test_installer_detects_running_process_until_it_exits(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.OpenMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        script = ('from meikipop.utils.startup import hold_installer_mutex; '
                  'hold_installer_mutex(); print("ready", flush=True); input()')
        process = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            handle = kernel.OpenMutexW(0x100000, False, "Local\\MeikipopDesktop")
            self.assertTrue(handle)
            if handle:
                kernel.CloseHandle(handle)
        finally:
            process.communicate("\n", timeout=10)
        self.assertEqual(process.returncode, 0)
