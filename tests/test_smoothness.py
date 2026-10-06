import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest.mock import Mock, patch
from test_quick_lookup import QuickLookupTests, entry
from meikipop.dictionary.search import SearchResult
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from meikipop.gui.interaction_preferences import migrate, enabled


class PendingTests(QuickLookupTests):
    # Reuse the small fake engine and lifetime helpers without re-running its suite.
    def test_clear_rejects_late_results_and_audio(self):
        self.window.show_entries((entry(),), "猫")
        self.window.set_context("猫です。")
        old = self.window.revision
        self.window.audio = Mock()
        self.window.search.clear()
        self.window.deliver(old, SearchResult("猫", "ja", "en", (entry(),)))
        self.window.play_audio()
        self.assertIsNone(self.window._result)
        self.assertFalse(self.window.audio_button.isEnabled())
        self.assertFalse(self.window.copy_button.isEnabled())
        self.window.audio.play.assert_not_called()
        self.window.audio.cancel.assert_called_once()

    def test_selection_policy_and_double_click_are_one_gesture(self):
        self.window.show_entries((entry(language="en", term="cat"),), "cat", source="en")
        browser = self.window.browser
        browser.selection_lookup = True
        selected = Mock()
        browser.word_selected.disconnect()
        browser.word_selected.connect(selected)
        browser.setPlainText("cat house")
        point = QPoint(10, 10)
        QTest.mouseDClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(selected.call_count, 1)
        browser.selection_lookup = False
        QTest.mouseDClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(selected.call_count, 1)
        self.assertTrue(browser.selected_text())

    def test_migration_preserves_existing_only_once(self):
        self.settings.clear()
        self.settings.setValue("profiles/tr/target", "en")
        self.settings.setValue("profiles/ja/selection_lookup", False)
        migrate(self.settings)
        self.assertTrue(enabled(self.settings, "tr", "auto_translate_miss"))
        self.assertFalse(enabled(self.settings, "ja", "selection_lookup"))
        self.settings.setValue("profiles/de/target", "en")
        migrate(self.settings)
        self.assertFalse(enabled(self.settings, "de", "auto_translate_sentence"))
        self.assertFalse(self.settings.value("profiles/tr/selected_text", False, bool))

    def test_new_install_defaults_off(self):
        self.assertFalse(enabled(self.settings, "ja", "auto_translate_sentence"))
        self.assertFalse(self.window.browser.selection_lookup)

    def test_nested_lookup_is_one_transaction_and_keeps_old_content(self):
        self.window.show_entries((entry(),), "猫")
        with patch.object(self.window.worker, "request") as request, patch.object(self.window, "_edited") as edited:
            self.window.lookup_word("犬")
        request.assert_called_once()
        edited.assert_not_called()
        self.assertIn("猫", self.window.browser.toPlainText())
        self.assertFalse(self.window.audio_button.isEnabled())


# Only inherit setup/teardown/helpers; inherited tests belong to their original module.
for _name in list(vars(QuickLookupTests)):
    if _name.startswith("test_") and _name not in PendingTests.__dict__:
        setattr(PendingTests, _name, None)
del QuickLookupTests
