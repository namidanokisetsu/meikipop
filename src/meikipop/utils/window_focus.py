"""Give explicitly requested popup windows native keyboard focus."""
import sys


def _native_macos_window(window):
    """Return the AppKit window behind a Qt window, when available."""
    from PyQt6.QtWidgets import QApplication
    if sys.platform != "darwin" or QApplication.platformName() == "offscreen":
        return None
    import ctypes
    import objc
    view = objc.objc_object(c_void_p=ctypes.c_void_p(int(window.winId())))
    return view.window()


def configure_macos_popup(window):
    from PyQt6.QtWidgets import QApplication
    if sys.platform != "darwin" or QApplication.platformName() == "offscreen":
        return
    import AppKit
    native = _native_macos_window(window)
    # A regular Dock app's panel needs this style to join another app's
    # fullscreen Space without activating Meikipop or leaving the game.
    native.setStyleMask_(int(native.styleMask()) | AppKit.NSWindowStyleMaskNonactivatingPanel)
    behavior = int(native.collectionBehavior())
    behavior &= ~(AppKit.NSWindowCollectionBehaviorMoveToActiveSpace
                  | AppKit.NSWindowCollectionBehaviorFullScreenPrimary
                  | AppKit.NSWindowCollectionBehaviorFullScreenNone)
    behavior |= (AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                 | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
    all_apps = getattr(AppKit, "NSWindowCollectionBehaviorCanJoinAllApplications", 0)
    if all_apps and AppKit.NSProcessInfo.processInfo().operatingSystemVersion()[0] >= 13:
        behavior &= ~(AppKit.NSWindowCollectionBehaviorPrimary | AppKit.NSWindowCollectionBehaviorAuxiliary)
        behavior |= all_apps
    native.setCollectionBehavior_(behavior)


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


def activate_application():
    from PyQt6.QtWidgets import QApplication
    if sys.platform == "darwin" and QApplication.platformName() != "offscreen":
        from AppKit import NSApplication
        application = NSApplication.sharedApplication()
        if hasattr(application, "activate"):
            application.activate()
        else:
            application.activateIgnoringOtherApps_(True)


def reduce_motion_enabled():
    """Return the user's native reduced-motion preference when available."""
    from PyQt6.QtWidgets import QApplication
    if QApplication.platformName() == "offscreen":
        return False
    if sys.platform == "darwin":
        try:
            from AppKit import NSWorkspace
            value = NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion
            return bool(value() if callable(value) else value)
        except Exception:
            return False
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            animation = ctypes.c_int()
            # SPI_GETCLIENTAREAANIMATION returns whether client-area
            # animations are enabled; reduced motion is its inverse.
            if not user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(animation), 0):
                return False
            return not bool(animation.value)
        except Exception:
            return False
    return False


def _focus_native_window(window):
    """Raise and focus a Qt window using the platform's native focus API."""
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


def focus_pinned_popup(window, focus_widget=None):
    """Give a pinned popup keyboard focus without activating macOS globally."""
    from PyQt6.QtWidgets import QApplication
    if sys.platform == "darwin" and QApplication.platformName() != "offscreen":
        configure_macos_popup(window)
        native = _native_macos_window(window)
        if native is not None:
            # A nonactivating panel can become key while the source app remains
            # frontmost. This keeps arrow keys and wheel events in the popup.
            native.orderFrontRegardless()
            native.makeKeyWindow()
        window.raise_()
    else:
        _focus_native_window(window)
    if focus_widget is not None:
        focus_widget.setFocus()


def focus_search(window):
    from PyQt6.QtWidgets import QApplication
    activate_application()
    _focus_native_window(window)
    window.search.setFocus()
    window.search.selectAll()
