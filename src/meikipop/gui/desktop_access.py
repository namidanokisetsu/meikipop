"""macOS menu and Dock access for the background dictionary app."""
import sys

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QApplication, QDialog, QMenuBar


class DesktopAccess(QObject):
    def __init__(self, window, app):
        super().__init__(app)
        self.window = window
        # A parentless menu bar remains available when every window is hidden.
        self.menu_bar = QMenuBar()
        menu = self.menu_bar.addMenu("Meikipop")
        self.settings_action = menu.addAction("Settings…")
        self.settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(window.open_settings)
        menu.addAction("Search", window.open_search)
        quit_action = menu.addAction("Quit Meikipop", app.quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        if sys.platform == "darwin" and QApplication.platformName() != "offscreen":
            # Qt installs its Apple-event handlers as the native loop starts.
            QTimer.singleShot(0, self._install_reopen_handler)

    def _install_reopen_handler(self):
        from meikipop.gui.macos_reopen import install_reopen_handler
        self._reopen_handler = install_reopen_handler(self.dock_clicked)

    def dock_clicked(self):
        QTimer.singleShot(0, self.reopen)

    def reopen(self):
        if QApplication.activePopupWidget() is not None:
            return
        dialogs = [dialog for dialog in QApplication.topLevelWidgets()
                   if isinstance(dialog, QDialog) and dialog.isVisible()]
        if any(not dialog.isMinimized() for dialog in dialogs):
            return
        if dialogs:
            dialogs[0].showNormal()
            dialogs[0].raise_()
            dialogs[0].activateWindow()
            return
        self.window.open_settings()
