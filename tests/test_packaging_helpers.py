import inspect
import io
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class HelperWindowTests(unittest.TestCase):
    def runtime(self, platform="win32", stdout=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        calls = []

        class Process:
            __signature__ = inspect.signature(subprocess.Popen)

            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

            def communicate(self):
                return b"output", b"errors"

        with patch("sys.platform", platform), patch("sys.stdout", stdout), patch("sys.stderr", io.StringIO()), \
                patch("platformdirs.user_cache_dir", return_value=temporary.name), \
                patch("meikipop.utils.model_cache.configure_model_cache"), patch.object(subprocess, "Popen", Process):
            state = runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging/runtime.py"))
            selected = subprocess.Popen
        if "stream" in state:
            state["stream"].close()
        return Process, selected, calls

    @unittest.skipUnless(hasattr(subprocess, "CREATE_NO_WINDOW"), "Windows process flags")
    def test_windowed_helpers_keep_pipes_options_and_process_contract(self):
        original, selected, calls = self.runtime()
        self.assertTrue(issubclass(selected, original))
        process = selected(["where", "ccache"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           cwd="fixture", text=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertEqual(process.communicate(), (b"output", b"errors"))
        self.assertEqual(calls[0][0], (["where", "ccache"],))
        self.assertEqual(calls[0][1], dict(stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         cwd="fixture", text=True,
                                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW))

    @unittest.skipUnless(hasattr(subprocess, "CREATE_NO_WINDOW"), "Windows process flags")
    def test_explicit_console_and_detached_launches_are_preserved(self):
        _, selected, calls = self.runtime()
        for flags in (subprocess.CREATE_NEW_CONSOLE, subprocess.DETACHED_PROCESS,
                      subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP):
            selected("helper", creationflags=flags)
            self.assertEqual(calls[-1][1]["creationflags"], flags)

    @unittest.skipUnless(hasattr(subprocess, "CREATE_NO_WINDOW"), "Windows process flags")
    def test_positional_creation_flags_and_startupinfo_are_preserved(self):
        _, selected, calls = self.runtime()
        startup = object()
        arguments = ["helper", -1, None, None, None, None, None, True, False, None, None, None, startup, 0]
        selected(*arguments)
        self.assertIs(calls[0][0][12], startup)
        self.assertEqual(calls[0][0][13], subprocess.CREATE_NO_WINDOW)
        self.assertEqual(calls[0][1], {})

    def test_cli_source_and_macos_keep_original_process_class(self):
        for platform, stdout in (("win32", io.StringIO()), ("darwin", None), ("linux", None)):
            with self.subTest(platform=platform):
                original, selected, _ = self.runtime(platform, stdout)
                self.assertIs(selected, original)
