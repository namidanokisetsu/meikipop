import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from meikipop.config.config import config
from meikipop.gui.settings_dialog import SettingsDialog
from meikipop.gui.themes import THEMES


class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original = dict(config.__dict__)
        self.ocr = Mock(available_providers={config.ocr_provider: object()})
        popup = Mock(shared_state=SimpleNamespace(clipboard_lookup=None))
        self.dialog = SettingsDialog(self.ocr, popup, Mock(), Mock(audio_service=None), Mock())

    def tearDown(self):
        self.dialog.deleteLater()
        self.app.processEvents()
        config.__dict__.clear()
        config.__dict__.update(self.original)

    def test_cancel_discards_theme_and_color_changes(self):
        self.dialog.theme_combo.setCurrentText("Light")
        with patch("meikipop.gui.settings_dialog.QColorDialog.getColor", return_value=QColor("#123456")):
            self.dialog.pick_color("color_background", self.dialog.color_widgets["color_background"])
        self.dialog.reject()
        self.assertEqual(config.__dict__, self.original)

    def test_save_applies_preset_without_marking_it_custom(self):
        self.dialog.theme_combo.setCurrentText("Monochrome Dark")
        self.assertEqual(self.dialog.theme_combo.currentText(), "Monochrome Dark")
        with patch.object(config, "save"), patch("meikipop.gui.settings_dialog.IS_WINDOWS", False):
            self.dialog.save_and_accept()
        for key, value in THEMES["Monochrome Dark"].items():
            self.assertEqual(getattr(config, key), value)

    def test_missing_activation_does_not_silently_restore_shift(self):
        self.dialog.hotkey_combo.setCurrentText("None")
        self.dialog.middle_activation_check.setChecked(False)
        with patch("meikipop.gui.settings_dialog.QMessageBox.warning") as warning, patch.object(config, "save") as save:
            self.dialog.save_and_accept()
            warning.assert_called_once()
            save.assert_not_called()
        self.assertEqual(config.__dict__, self.original)
        self.ocr.switch_provider.assert_not_called()
