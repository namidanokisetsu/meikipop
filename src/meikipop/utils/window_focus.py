"""Activate an explicitly requested search window from a global shortcut."""
import sys


def foreground_window():
    if sys.platform != "win32":
        return None
    import ctypes
    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    return user32.GetForegroundWindow()


def restore_foreground(handle):
    if sys.platform != "win32" or not handle:
        return
    import ctypes
    user32 = ctypes.WinDLL("user32")
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    if user32.IsWindow(handle):
        user32.SetForegroundWindow(handle)


def focus_search(window):
    from PyQt6.QtWidgets import QApplication
    window.raise_()
    window.activateWindow()
    if sys.platform == "win32" and QApplication.platformName() != "offscreen":
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetFocus.argtypes = [wintypes.HWND]
        target = int(window.winId())
        if not user32.SetForegroundWindow(target):
            foreground = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = foreground_thread != current_thread and user32.AttachThreadInput(current_thread, foreground_thread, True)
            try:
                user32.SetForegroundWindow(target)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
        user32.SetFocus(target)
    window.search.setFocus()
    window.search.selectAll()
