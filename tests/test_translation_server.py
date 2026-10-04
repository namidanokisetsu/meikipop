import hashlib
from io import BytesIO
import json
from pathlib import Path, PureWindowsPath
import subprocess
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from meikipop.scripts import translation_server as server


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_hash_preserves_existing_file_and_removes_partial(self):
        source, target = self.root / "source", self.root / "target"
        source.write_bytes(b"corrupted download")
        target.write_bytes(b"previous model")
        with self.assertRaisesRegex(ValueError, "verification failed"):
            server._download("https://example.invalid", target, "0" * 64, local=source)
        self.assertEqual(target.read_bytes(), b"previous model")
        self.assertFalse(list(self.root.glob(".download-*")))

    def test_cancellation_does_not_publish_partial_model(self):
        source, target = self.root / "source", self.root / "target"
        content = b"fixture model"
        source.write_bytes(content)
        stop = threading.Event()
        with self.assertRaises(InterruptedError):
            server._download("https://example.invalid", target, hashlib.sha256(content).hexdigest(),
                             progress=lambda _: stop.set(), cancelled=stop, local=source, size=len(content))
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".download-*")))

    def test_verified_existing_download_never_contacts_network(self):
        target = self.root / "model.gguf"
        target.write_bytes(b"fixture model")
        with patch.object(server, "urlopen", side_effect=AssertionError("network")):
            self.assertEqual(server._download("https://example.invalid", target,
                                             hashlib.sha256(target.read_bytes()).hexdigest()), target)

    def test_zip_cannot_escape_runtime_directory(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../escaped.exe", b"bad")
        with self.assertRaisesRegex(ValueError, "Unsafe path"):
            server._extract_archive(archive, self.root / "runtime")
        self.assertFalse((self.root / "escaped.exe").exists())

    def test_tar_rejects_external_symlinks(self):
        archive = self.root / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            item = tarfile.TarInfo("lib.dylib")
            item.type, item.linkname = tarfile.SYMTYPE, "../../outside"
            output.addfile(item)
        with self.assertRaisesRegex(ValueError, "Unsafe link"):
            server._extract_archive(archive, self.root / "runtime")

    def test_tar_retains_internal_library_links_and_executable_mode(self):
        archive = self.root / "runtime.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            link = tarfile.TarInfo("libalias.dylib")
            link.type, link.linkname = tarfile.LNKTYPE, "libreal.dylib"
            output.addfile(link)
            item = tarfile.TarInfo("libreal.dylib")
            item.size, item.mode = 7, 0o755
            output.addfile(item, BytesIO(b"library"))
        server._extract_archive(archive, self.root / "runtime")
        self.assertEqual((self.root / "runtime/libalias.dylib").read_bytes(), b"library")

    def test_macos_selects_native_architecture(self):
        with patch.object(server.sys, "platform", "darwin"):
            for machine, expected in (("arm64", "mac-arm64"), ("x86_64", "mac-x64")):
                with self.subTest(machine=machine), patch.object(server.platform, "machine", return_value=machine):
                    self.assertEqual(server._platform_key(), expected)

    def test_explicit_bootstrap_install_publishes_complete_manifest_without_network(self):
        downloads = self.root / "downloads"
        downloads.mkdir()
        archive = downloads / "runtime.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("llama-server.exe", b"server")
            output.writestr("runtime.dll", b"dll")
        model = downloads / "model.gguf"
        model.write_bytes(b"model")
        models = {"quality": dict(file=model.name, repo="fixture", revision="revision", size=5,
                                   sha256=hashlib.sha256(model.read_bytes()).hexdigest())}
        runtimes = {"win-x64": ((archive.name, hashlib.sha256(archive.read_bytes()).hexdigest()),)}
        with patch.object(server, "MODELS", models), patch.object(server, "RUNTIMES", runtimes), \
                patch.object(server, "_platform_key", return_value="win-x64"), \
                patch.object(server, "urlopen", side_effect=AssertionError("network")):
            registry = server.install_model(directory=self.root / "installed", downloads=downloads)
        installed = self.root / "installed"
        self.assertEqual((installed / registry["models"]["quality"]["path"]).read_bytes(), b"model")
        self.assertTrue((installed / registry["executable"]).is_file())
        self.assertEqual(server.installation(installed), registry)
        self.assertFalse(list(installed.glob(".runtime-*")))
        self.assertNotIn("\\", registry["executable"])
        self.assertNotIn("\\", registry["models"]["quality"]["path"])
        self.assertEqual(server._installed_paths("quality", installed),
                         (installed / registry["executable"], installed / registry["models"]["quality"]["path"]))
        # Existing manifests produced on Windows remain usable without copying
        # or rehashing an eight-gigabyte model during application startup.
        registry["executable"] = str(PureWindowsPath(registry["executable"]))
        registry["models"]["quality"]["path"] = str(PureWindowsPath(registry["models"]["quality"]["path"]))
        server._write_installation(installed, registry)
        executable, installed_model = server._installed_paths("quality", installed)
        self.assertTrue(executable.is_file())
        self.assertEqual(installed_model.read_bytes(), b"model")


class ManagedServerTests(unittest.TestCase):
    def setUp(self):
        server.shutdown_server()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.executable = self.root / "llama-server.exe"
        self.executable.write_bytes(b"server")
        models = {}
        for profile in ("quality", "lightweight"):
            path = self.root / f"{profile}.gguf"
            path.write_bytes(b"model")
            models[profile] = dict(path=path.name, size=5)
        (self.root / "installation.json").write_text(json.dumps(dict(executable=self.executable.name, models=models)))
        self.process = Mock()
        self.process.poll.return_value = None

    def tearDown(self):
        server.shutdown_server()
        self.temp.cleanup()

    def test_managed_endpoint_is_strictly_loopback(self):
        for endpoint in ("http://example.com:8766/v1", "http://0.0.0.0:8766/v1",
                         "http://user@127.0.0.1:8766/v1", "http://127.0.0.1:8766/v1?redirect=remote"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                server.ensure_server(endpoint, directory=self.root)

    def test_missing_model_does_not_download_or_spawn(self):
        (self.root / "quality.gguf").unlink()
        with patch.object(server, "urlopen", side_effect=AssertionError("network")), \
                patch.object(server.subprocess, "Popen") as spawn, self.assertRaisesRegex(RuntimeError, "Install"):
            server.ensure_server(directory=self.root)
        spawn.assert_not_called()

    def test_start_once_with_idle_unload_and_hidden_windows_process(self):
        with patch.object(server, "_ready", side_effect=[False, True, True]), \
                patch.object(server.subprocess, "Popen", return_value=self.process) as spawn, \
                patch.dict(server.os.environ, {"LLAMA_ARG_HF_REPO": "unexpected/download"}), \
                patch.object(server.sys, "platform", "win32"), \
                patch.object(server.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            server.ensure_server(directory=self.root)
            server.ensure_server(directory=self.root)
        spawn.assert_called_once()
        arguments, options = spawn.call_args.args[0], spawn.call_args.kwargs
        self.assertIn("--sleep-idle-seconds", arguments)
        self.assertEqual(arguments[arguments.index("--sleep-idle-seconds") + 1], "60")
        self.assertEqual(arguments[arguments.index("--host") + 1], "127.0.0.1")
        self.assertEqual(arguments[arguments.index("--cache-ram") + 1], "0")
        self.assertIn("--jinja", arguments)
        self.assertIn("--no-context-shift", arguments)
        self.assertEqual(options["creationflags"], 0x08000000)
        self.assertNotIn("LLAMA_ARG_HF_REPO", options["env"])
        server.shutdown_server()
        self.process.terminate.assert_called_once()

    def test_startup_timeout_stops_only_owned_process(self):
        with patch.object(server, "_ready", return_value=False), \
                patch.object(server.subprocess, "Popen", return_value=self.process), \
                self.assertRaisesRegex(RuntimeError, "too long"):
            server.ensure_server(directory=self.root, timeout=0)
        self.process.terminate.assert_called_once()
        self.assertIsNone(server._process)

    def test_another_model_on_default_port_is_not_replaced_or_terminated(self):
        with patch.object(server, "_ready", return_value=True), \
                patch.object(server, "_local_json", return_value={"model_path": str(self.root / "other.gguf")}), \
                patch.object(server.subprocess, "Popen") as spawn, \
                self.assertRaisesRegex(RuntimeError, "another model"):
            server.ensure_server(directory=self.root)
        spawn.assert_not_called()
        server.shutdown_server()
        self.process.terminate.assert_not_called()

    def test_switch_profile_replaces_owned_model(self):
        second = Mock()
        second.poll.return_value = None
        with patch.object(server, "_ready", side_effect=[False, True, False, True]), \
                patch.object(server.subprocess, "Popen", side_effect=[self.process, second]) as spawn:
            server.ensure_server(directory=self.root)
            server.ensure_server(profile="lightweight", directory=self.root)
        self.process.terminate.assert_called_once()
        self.assertEqual(spawn.call_count, 2)
        self.assertIn(str(self.root / "lightweight.gguf"), spawn.call_args.args[0])

    def test_shutdown_escalates_only_if_owned_process_ignores_termination(self):
        server._process = self.process
        self.process.wait.side_effect = [subprocess.TimeoutExpired("server", 5), 0]
        server.shutdown_server()
        self.process.kill.assert_called_once()

    def test_application_quit_prevents_late_worker_from_restarting_server(self):
        with patch.object(server, "_closed", threading.Event()), patch.object(server.subprocess, "Popen") as spawn:
            server.shutdown_server(permanent=True)
            with self.assertRaisesRegex(RuntimeError, "shutting down"):
                server.ensure_server(directory=self.root)
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
