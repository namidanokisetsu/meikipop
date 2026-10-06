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
        self.assertFalse(enabled(self.settings, "de", "auto_translate_miss"))
        self.assertFalse(self.settings.value("profiles/tr/selected_text", False, bool))

    def test_new_install_defaults_off(self):
        self.assertFalse(enabled(self.settings, "ja", "auto_translate_miss"))
        self.assertFalse(self.window.browser.selection_lookup)

    def test_keep_warm_setting_preserves_inflight_request_and_setup_edits_save(self):
        self.window.open_settings()
        dialog = self.window._setup
        with patch.object(self.window, "_edited") as edited:
            dialog.translation_warm.click()
            edited.assert_not_called()
        from meikipop.dictionary.translation import load_profile_settings
        self.assertTrue(load_profile_settings(self.settings, "ja").keep_warm)
        dialog.operation = Mock()
        try:
            dialog.selection_lookup.click()
            self.assertTrue(self.settings.value("profiles/ja/selection_lookup", False, bool))
        finally:
            dialog.operation = None
            dialog.hide()

    def test_stream_chunks_are_batched_and_cancel_restores_useful_result(self):
        self.window.show_entries((entry(),), "猫")
        original = self.window._result
        with patch.object(self.window.worker, "request"):
            self.window.submit(translate=False)
        self.window._translation_busy = True
        self.window._translation_base = original
        self.window._translation_previous = original
        revision = self.window.revision
        with patch.object(self.window.browser, "setHtml", wraps=self.window.browser.setHtml) as render:
            for text in ("a", "ab", "abc"):
                self.window._translation_progress(revision, SearchResult("猫", "ja", "en", translation=text))
            render.assert_not_called()
            self.window._flush_translation()
            render.assert_called_once()
            self.assertIn("abc", self.window.browser.toPlainText())
            self.assertIn("cat", self.window.browser.toPlainText())
            self.window._translate_clicked()
            self.assertEqual(self.window._result, original)
            self.window._translation_progress(revision, SearchResult("猫", "ja", "en", translation="late"))
            self.window._flush_translation()
            self.assertNotIn("late", self.window.browser.toPlainText())

    def test_disabled_routing_never_starts_translation_and_fallback_keeps_entries(self):
        from dataclasses import replace
        self.window.search.setText("猫です")
        partial = SearchResult("猫です", "ja", "en", (entry(),), matched_length=1)
        self.window.deliver(self.window.revision, partial)
        self.assertIsNone(self.window.translation_worker)
        self.settings.setValue("profiles/ja/auto_translate_miss", True)
        with patch.object(self.window, "submit") as submit:
            self.window.deliver(self.window.revision, partial)
            submit.assert_called_once_with(translate=True, context=True, remember=False)
        self.assertIn("cat", self.window.browser.toPlainText())
        self.window._last_request_translate = True
        self.window._translation_base = partial
        self.window.deliver(self.window.revision, replace(partial, entries=(), message="fixture failure"))
        self.assertIn("cat", self.window.browser.toPlainText())
        self.assertTrue(self.window.translate.isEnabled())

    def test_right_press_preserves_preview_and_search_is_resizable(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.app.processEvents()
        with patch.object(self.window.browser, "setHtml", wraps=self.window.browser.setHtml) as render:
            QTest.mousePress(self.window.browser.viewport(), Qt.MouseButton.RightButton, pos=QPoint(15, 15))
            self.assertFalse(self.window.is_pinned)
            render.assert_not_called()
        self.window.open_search()
        self.assertTrue(self.window.isSizeGripEnabled())

    def test_render_identity_preserves_selection_and_invalidates_metadata(self):
        from dataclasses import replace
        from PyQt6.QtGui import QTextCursor
        self.window.show_entries((entry(),), "猫", peek=True)
        self.app.processEvents()
        cursor = self.window.browser.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.window.browser.setTextCursor(cursor)
        selected = self.window.browser.selected_text()
        with patch.object(self.window.browser, "setHtml", wraps=self.window.browser.setHtml) as render:
            for _ in range(5):
                self.window._render()
            render.assert_not_called()
            self.assertEqual(self.window.browser.selected_text(), selected)
            self.window._result = replace(self.window._result, entries=(entry(definitions=("new sense",)),))
            self.window._render()
            render.assert_called_once()
        self.assertIn("new sense", self.window.browser.toPlainText())

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
