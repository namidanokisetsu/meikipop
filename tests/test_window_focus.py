import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meikipop.utils.window_focus import configure_macos_popup


class PopupSpaceTests(unittest.TestCase):
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
