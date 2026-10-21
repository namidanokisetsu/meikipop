import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meikipop.utils.window_focus import (configure_macos_popup, focus_pinned_popup,
                                        foreground_is_fullscreen, reduce_motion_enabled)


class PopupSpaceTests(unittest.TestCase):
    def test_windows_fullscreen_uses_monitor_bounds_and_excludes_desktop(self):
        user32 = Mock()
        user32.GetForegroundWindow.return_value = 42
        user32.GetDesktopWindow.return_value = 1
        user32.GetShellWindow.return_value = 2
        user32.MonitorFromWindow.return_value = 3

        def bounds(output, values):
            for side, value in zip(("left", "top", "right", "bottom"), values):
                setattr(output, side, value)
            return 1

        monitor = (-2560, 0, 0, 1440)
        user32.GetMonitorInfoW.side_effect = lambda handle, output: bounds(output._obj.monitor, monitor)
        with patch('sys.platform', 'win32'), \
                patch('PyQt6.QtWidgets.QApplication.platformName', return_value='windows'), \
                patch('ctypes.WinDLL', return_value=user32, create=True):
            for rect, expected in ((monitor, True), ((-2560, 0, 0, 1400), False),
                                   ((-2568, -8, 8, 1448), False)):
                with self.subTest(rect=rect):
                    user32.GetWindowRect.side_effect = lambda handle, output: bounds(output._obj, rect)
                    self.assertEqual(foreground_is_fullscreen(), expected)
            user32.GetForegroundWindow.return_value = 2
            self.assertFalse(foreground_is_fullscreen())
            user32.GetForegroundWindow.return_value = 42
            user32.GetWindowRect.side_effect = None
            user32.GetWindowRect.return_value = 0
            self.assertFalse(foreground_is_fullscreen())

    def test_popup_joins_fullscreen_spaces_without_moving_the_source_app(self):
        constants = dict(CanJoinAllSpaces=1, MoveToActiveSpace=2, FullScreenPrimary=128,
                         FullScreenAuxiliary=256, FullScreenNone=512, Primary=65536,
                         Auxiliary=131072, CanJoinAllApplications=262144)
        for version in (12, 26):
            native = Mock()
            native.collectionBehavior.return_value = 258
            native.styleMask.return_value = 0
            appkit = SimpleNamespace(**{'NSWindowCollectionBehavior' + k: v for k, v in constants.items()},
                                     NSProcessInfo=Mock(), NSWindowStyleMaskNonactivatingPanel=128)
            appkit.NSProcessInfo.processInfo.return_value.operatingSystemVersion.return_value = (version, 0, 0)
            objc = Mock()
            objc.objc_object.return_value.window.return_value = native
            with self.subTest(version=version), patch('sys.platform', 'darwin'), \
                    patch('PyQt6.QtWidgets.QApplication.platformName', return_value='cocoa'), \
                    patch.dict(sys.modules, {'objc': objc, 'AppKit': appkit}):
                configure_macos_popup(Mock(winId=Mock(return_value=42)))
            native.setCollectionBehavior_.assert_called_once_with(257 | (262144 if version >= 13 else 0))
            native.setStyleMask_.assert_called_once_with(128)

    def test_other_platforms_do_not_touch_native_window(self):
        window = Mock()
        with patch('sys.platform', 'win32'):
            configure_macos_popup(window)
        window.winId.assert_not_called()

    def test_pinned_popup_becomes_key_without_activating_macos_app(self):
        constants = dict(CanJoinAllSpaces=1, MoveToActiveSpace=2, FullScreenPrimary=128,
                         FullScreenAuxiliary=256, FullScreenNone=512, Primary=65536,
                         Auxiliary=131072, CanJoinAllApplications=262144)
        native = Mock()
        native.collectionBehavior.return_value = 258
        native.styleMask.return_value = 0
        appkit = SimpleNamespace(**{'NSWindowCollectionBehavior' + k: v for k, v in constants.items()},
                                 NSProcessInfo=Mock(), NSWindowStyleMaskNonactivatingPanel=128)
        appkit.NSProcessInfo.processInfo.return_value.operatingSystemVersion.return_value = (14, 0, 0)
        objc = Mock()
        objc.objc_object.return_value.window.return_value = native
        window = Mock(winId=Mock(return_value=42))
        browser = Mock()
        with patch('sys.platform', 'darwin'), \
                patch('PyQt6.QtWidgets.QApplication.platformName', return_value='cocoa'), \
                patch.dict(sys.modules, {'objc': objc, 'AppKit': appkit}):
            focus_pinned_popup(window, browser)
        native.orderFrontRegardless.assert_called_once_with()
        native.makeKeyWindow.assert_called_once_with()
        window.activateWindow.assert_not_called()
        browser.setFocus.assert_called_once_with()

    def test_reduced_motion_uses_macos_accessibility_preference(self):
        workspace = Mock()
        workspace.sharedWorkspace.return_value.accessibilityDisplayShouldReduceMotion.return_value = True
        with patch('sys.platform', 'darwin'), \
                patch('PyQt6.QtWidgets.QApplication.platformName', return_value='cocoa'), \
                patch.dict(sys.modules, {'AppKit': SimpleNamespace(NSWorkspace=workspace)}):
            self.assertTrue(reduce_motion_enabled())
        workspace.sharedWorkspace.return_value.accessibilityDisplayShouldReduceMotion.assert_called_once_with()

    def test_reduced_motion_uses_windows_client_animation_preference(self):
        user32 = Mock()
        user32.SystemParametersInfoW.return_value = 1
        user32.SystemParametersInfoW.side_effect = lambda action, param, output, flags: setattr(output._obj, 'value', 1) or 1
        with patch('sys.platform', 'win32'), \
                patch('PyQt6.QtWidgets.QApplication.platformName', return_value='windows'), \
                patch('ctypes.WinDLL', return_value=user32, create=True):
            self.assertFalse(reduce_motion_enabled())
        user32.SystemParametersInfoW.assert_called_once()
