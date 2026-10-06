import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QDialog

from meikipop.gui.desktop_access import DesktopAccess


class DesktopAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Mock()
        self.access = DesktopAccess(self.window, self.app)
        self.dialog = QDialog()

    def tearDown(self):
        self.app.applicationStateChanged.disconnect(self.access.state_changed)
        self.dialog.close()
        self.dialog.deleteLater()
        self.access.menu_bar.deleteLater()
        self.access.deleteLater()
        self.app.processEvents()

    def test_repeated_dock_activation_opens_settings_with_no_windows(self):
        for _ in range(2):
            self.access.state_changed(Qt.ApplicationState.ApplicationActive)
            self.app.processEvents()
        self.assertEqual(self.window.open_settings.call_count, 2)

    def test_inactive_application_does_not_open_settings(self):
        self.access.state_changed(Qt.ApplicationState.ApplicationInactive)
        self.app.processEvents()
        self.window.open_settings.assert_not_called()

    def test_existing_search_or_setup_is_not_interrupted(self):
        self.dialog.show()
        self.access.reopen()
        self.window.open_settings.assert_not_called()

    def test_minimized_dialog_is_restored(self):
        self.dialog.showMinimized()
        self.access.reopen()
        self.assertFalse(self.dialog.isMinimized())
        self.window.open_settings.assert_not_called()

    def test_native_settings_action_works_without_a_window(self):
        self.assertIsNone(self.access.menu_bar.parent())
        self.assertEqual(self.access.settings_action.menuRole(), QAction.MenuRole.PreferencesRole)
        self.access.settings_action.trigger()
        self.window.open_settings.assert_called_once_with(False)

    def test_launch_intent_is_forwarded_to_existing_instance(self):
        from meikipop.scripts.quick_lookup import main
        for platform, arguments, background in (
            ("darwin", [], False),
            ("darwin", ["--background"], True),
            ("win32", [], True),
        ):
            with self.subTest(platform=platform, arguments=arguments), \
                    patch("meikipop.scripts.quick_lookup.sys.platform", platform), \
                    patch("meikipop.utils.logger.setup_logging"), \
                    patch("meikipop.gui.single_instance.SingleInstance") as instance:
                instance.return_value.start.return_value = False
                self.assertEqual(main(arguments), 0)
                instance.return_value.start.assert_called_once_with("", background)
