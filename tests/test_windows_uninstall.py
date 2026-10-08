"""Exercise the real uninstall script with isolated registry and directory fixtures."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


@unittest.skipUnless(sys.platform == "win32", "Windows installer")
class WindowsUninstallTests(unittest.TestCase):
    def test_upgrade_and_default_uninstall_keep_data_but_explicit_cleanup_removes_it(self):
        compiler = Path(os.environ["LOCALAPPDATA"]) / "Programs/Inno Setup 6/ISCC.exe"
        if not compiler.is_file():
            self.skipTest("Inno Setup 6 is not installed")
        import winreg
        repository = Path(__file__).resolve().parents[1]
        key = "Software\\Meikipop-UninstallTest-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="meikipop-uninstall-") as folder:
            root = Path(folder).resolve()
            code = (repository / "packaging/meikipop.iss").read_text().split("[Code]", 1)[1]
            code = code.replace("Software\\Meikipop'", key + "'")
            code = code.replace("{localappdata}\\meikipop", str(root / "local"))
            code = code.replace("{userappdata}\\meikipop", str(root / "roaming"))
            fixture = root / "fixture.txt"
            fixture.write_text("application file")
            script = root / "test.iss"
            script.write_text(f'''[Setup]
AppId={key.split(chr(92))[-1]}
AppName=Meikipop uninstall test
AppVersion=1
DefaultDirName={root / "app"}
PrivilegesRequired=lowest
Uninstallable=yes
CreateUninstallRegKey=no
OutputDir={root}
OutputBaseFilename=fixture-setup
[Files]
Source: "{fixture}"; DestDir: "{{app}}"
[Code]
{code}
''')
            subprocess.run([str(compiler), "/Q", str(script)], check=True, capture_output=True)
            flags = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
            def run(executable, *extra):
                log = root / (uuid.uuid4().hex + ".log")
                result = subprocess.run([str(executable), *flags, f"/LOG={log}", *extra], timeout=30)
                deadline = time.monotonic() + 10
                # The original uninstaller exits before its copied second phase.
                while result.returncode == 0 and time.monotonic() < deadline:
                    if log.exists() and "Log closed." in log.read_text(errors="replace"):
                        break
                    time.sleep(.05)
                output = log.read_text(errors="replace") if log.exists() else "No installer log"
                self.assertEqual(result.returncode, 0, output)
                self.assertIn("Log closed.", output)
            installer = root / "fixture-setup.exe"
            uninstaller = root / "app/unins000.exe"
            try:
                for name in ("local", "roaming"):
                    directory = root / name
                    self.assertTrue(directory.resolve().is_relative_to(root))
                    directory.mkdir()
                    (directory / "model.bin").write_bytes(b"model")
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as settings:
                    winreg.SetValueEx(settings, "profile", 0, winreg.REG_SZ, "en")
                for _ in range(2):
                    run(installer)
                run(uninstaller)
                self.assertTrue((root / "local/model.bin").is_file())
                self.assertTrue((root / "roaming/model.bin").is_file())
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as settings:
                    self.assertEqual(winreg.QueryValueEx(settings, "profile")[0], "en")
                run(installer)
                run(uninstaller, "/REMOVEUSERDATA=1")
                self.assertFalse((root / "local").exists())
                self.assertFalse((root / "roaming").exists())
                with self.assertRaises(FileNotFoundError):
                    winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)
            finally:
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
                except FileNotFoundError:
                    pass
