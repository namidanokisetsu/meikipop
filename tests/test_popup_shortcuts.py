import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from unittest.mock import Mock

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication

from meikipop.gui.dictionary_manager import SetupDialog
from meikipop.gui.popup_shortcuts import native_chord, popup_bindings


class PopupShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = QSettings(self.temp.name + "/settings.ini", QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/target", "en")

    def test_defaults_saved_bindings_and_disabled_actions(self):
        self.assertEqual(popup_bindings(self.settings, "ja"),
                         {"replay": "R", "anki": "Shift+A", "copy": "Shift+C",
                          "copy_text": "Ctrl+C", "back": "Alt+Left"})
        self.settings.setValue("profiles/ja/anki/shortcut", "Ctrl+Shift+A")
        self.settings.setValue("profiles/ja/popup/replay_shortcut", "")
        self.assertEqual(popup_bindings(self.settings, "ja")["anki"], "Ctrl+Shift+A")
        self.assertEqual(popup_bindings(self.settings, "ja")["replay"], "")
        self.assertEqual(popup_bindings(self.settings, "tr")["replay"], "R")
        self.settings.setValue("profiles/ja/popup/copy_text_shortcut", "Ctrl+Insert")
        self.assertEqual(popup_bindings(self.settings, "ja")["copy_text"], "Ctrl+Insert")
        self.settings.setValue("profiles/ja/popup/copy_text_shortcut", "")
        self.assertEqual(popup_bindings(self.settings, "ja")["copy_text"], "")
        self.assertEqual(popup_bindings(self.settings, "ja")["copy"], "Shift+C")

    def test_native_chords_keep_letters_stable_and_modifiers_exact(self):
        for value, expected in (("R", (0x52, 0)), ("Shift+A", (0x41, 1)),
                                ("Shift+C", (0x43, 1)), ("Alt+Left", (0x25, 4)),
                                ("Ctrl+F2", (0x71, 2)), ("", None)):
            with self.subTest(value=value):
                self.assertEqual(native_chord(value), expected)

    def test_shortcuts_tab_reuses_controls_and_saves_independent_actions(self):
        dialog = SetupDialog(self.temp.name, self.settings, Mock())
        try:
            self.assertGreaterEqual(dialog.tabs.indexOf(dialog.shortcuts_tab), 0)
            self.assertTrue(dialog.shortcuts_tab.isAncestorOf(dialog.scan_key))
            self.assertTrue(dialog.shortcuts_tab.isAncestorOf(dialog.shortcut))
            self.assertTrue(dialog.shortcuts_tab.isAncestorOf(dialog.anki.shortcut))
            replay = dialog.popup_shortcuts["replay"]
            replay.recorder.setKeySequence(QKeySequence("F2"))
            dialog.save_popup_shortcuts()
            self.assertEqual(popup_bindings(self.settings, "ja")["replay"], "F2")
            replay.enabled.setChecked(False)
            self.assertEqual(popup_bindings(self.settings, "ja")["replay"], "")
            self.assertEqual(popup_bindings(self.settings, "ja")["copy"], "Shift+C")
            self.assertEqual(self.settings.value("profiles/ja/popup/replay_shortcut_preset"), "F2")
            selection_copy = dialog.popup_shortcuts["copy_text"]
            selection_copy.recorder.setKeySequence(QKeySequence("Ctrl+Insert"))
            dialog.save_popup_shortcuts()
            self.assertEqual(QKeySequence(popup_bindings(self.settings, "ja")["copy_text"]),
                             QKeySequence("Ctrl+Insert"))
            selection_copy.enabled.setChecked(False)
            self.assertEqual(popup_bindings(self.settings, "ja")["copy_text"], "")
            dialog.popup_shortcuts["copy"].recorder.setKeySequence(QKeySequence("Shift+A"))
            dialog.save_popup_shortcuts()
            self.assertIn("different shortcut", dialog.status.text())
            self.assertEqual(popup_bindings(self.settings, "ja")["copy"], "Shift+C")
            dialog.popup_shortcuts["anki"].recorder.setKeySequence(QKeySequence("F3"))
            dialog.anki._save()
            self.assertEqual(popup_bindings(self.settings, "ja")["anki"], "Shift+A")
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()
