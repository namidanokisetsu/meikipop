"""Locate an explicitly installed Chrome Screen AI component; never download it.

Google packages: https://chrome-infra-packages.appspot.com/p/chromium/third_party/screen-ai
macOS package layout verified against Meikikai's component.py at 50efb401.
"""
import ctypes
import os
from pathlib import Path
import platform
import re
import sys


PACKAGE_ROOT = "https://chrome-infra-packages.appspot.com/p/chromium/third_party/screen-ai"


def library_names():
    if sys.platform == "win32":
        return ("chrome_screen_ai.dll",)
    if sys.platform == "darwin":
        # Google's macOS package contains a Mach-O binary with a .so suffix.
        return ("libchromescreenai.so", "libchromescreenai.dylib")
    return ("libchromescreenai.so",)


def component_url():
    if sys.platform == "win32":
        target = "windows-amd64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "windows-386"
    elif sys.platform == "darwin":
        target = "mac-arm64" if platform.machine().lower() in ("arm64", "aarch64") else "mac-amd64"
    else:
        target = "linux"
    return PACKAGE_ROOT + "/" + target


def find_in_directory(directory):
    base = Path(directory).expanduser()
    candidates = [base, base / "resources"]
    try:
        versions = sorted((p for p in base.iterdir() if p.is_dir()),
                          key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.name)), reverse=True)
        for version in versions:
            candidates.extend((version, version / "resources"))
    except OSError:
        pass
    for candidate in candidates:
        if any((candidate / name).is_file() for name in library_names()):
            return candidate.resolve()
    return None


def default_directories():
    from meikipop.utils.paths import paths
    home = Path.home()
    result = [Path(paths.data_dir) / "screen_ai", Path(paths.data_dir) / "screenai", home / ".config/screen_ai"]
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        result.extend(local / browser / "User Data/screen_ai" for browser in ("Google/Chrome", "Microsoft/Edge"))
    elif sys.platform == "darwin":
        support = home / "Library/Application Support"
        result.extend((support / "Google/Chrome/screen_ai", support / "meikikai/screen_ai"))
    else:
        result.extend(home / ".config" / browser / "screen_ai" for browser in ("google-chrome", "chromium"))
    return result


def find_component_directory(directory=None):
    candidates = [directory] if directory else default_directories()
    for candidate in candidates:
        found = find_in_directory(candidate)
        if found:
            return found
    raise RuntimeError("Chrome Screen AI is not installed. In Settings → OCR, choose its extracted component folder.")
