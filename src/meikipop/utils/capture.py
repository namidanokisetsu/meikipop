"""Temporarily exclude the popup without hiding it on supported Windows builds."""
import sys


def exclude_from_capture(window, enabled):
    if sys.platform != "win32" or sys.getwindowsversion().build < 19041:
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    changed = bool(user32.SetWindowDisplayAffinity(int(window.winId()), 0x11 if enabled else 0))
    if changed:
        ctypes.WinDLL("dwmapi").DwmFlush()
    return changed
