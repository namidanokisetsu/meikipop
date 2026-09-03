"""Per-user operating-system startup registration."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "meikipop"


def startup_command() -> str:
    """Return the command that starts this exact packaged or source install."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    if sys.platform.startswith("win"):
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return f'"{executable}" -m meikipop.main'


def is_startup_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except FileNotFoundError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    if not sys.platform.startswith("win"):
        return
    import winreg

    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        return

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def refresh_startup_registration(enabled: bool) -> None:
    """Refresh an enabled entry after an executable is moved or upgraded."""
    if enabled:
        try:
            set_startup_enabled(True)
        except OSError:
            logger.exception("Could not refresh the Windows startup registration")
