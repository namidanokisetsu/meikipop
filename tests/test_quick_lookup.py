import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from PyQt6.QtCore import QEvent, QPoint, QRect, QSettings, QSize, Qt, QUrl
from PyQt6.QtGui import QKeyEvent, QTextCursor, QTextFormat
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from meikipop.dictionary.library import Entry, Library
from meikipop.dictionary.kanji import KanjiEntry
from meikipop.dictionary.metadata import Frequency
from meikipop.dictionary.search import SearchResult
from meikipop.gui.dictionary_manager import SetupDialog, SetupOperation
from meikipop.gui.quick_lookup import LookupWorker, QuickLookupWindow, render_result


def entry(term="猫", source="Dictionary", definitions=("cat",), language="ja"):
    return Entry(f"{source}:{term}", term, "ねこ" if language == "ja" else "", source,
                 language, tuple(definitions))


def disclosure(body, lead="first meaning"):
    return {"type": "structured-content", "content": [lead, {
        "tag": "details", "content": [{"tag": "summary", "content": "More"}, body]}]}


class FakeEngine:
    def __init__(self):
        self.library = SimpleNamespace(packs=[(None, {"language": "de"}, None)])
        self.calls = []
        self.contexts = []
        self.closed = False

    def search(self, text, source="auto", foreign="ja", translate=False, target=None, pair=None, translation_settings=None,
               context=None, morphology=False, exact_only=False):
        self.calls.append((text, source, foreign, translate, threading.get_ident()))
        self.contexts.append(context)
        return SearchResult(text, "ja" if source == "auto" else source, "en",
                            () if translate or exact_only else (entry(text),), translation="translated" if translate else "")

    def refresh(self):
        pass

    def close(self):
        self.closed = True


class QuickLookupTests(unittest.TestCase):
    def test_translation_restores_original_child_focus_without_stealing_focus(self):
        handle = int(self.window.winId())
        with patch('PyQt6.QtWidgets.QApplication.platformName', return_value='windows'), \
                patch('meikipop.utils.window_focus.foreground_window', return_value=987654) as foreground, \
                patch('meikipop.utils.window_focus.focused_child', return_value=987655), \
                patch('meikipop.utils.window_focus.focus_pinned_popup'), \
                patch('meikipop.utils.window_focus.restore_foreground') as restore:
            self.window.remember_foreground()
            foreground.return_value = handle
            self.window.open_translation()
            self.window.remember_foreground()
            self.window.hide()
            restore.assert_called_once_with(987654, 987655)
            restore.reset_mock()
            foreground.return_value = 987656
            self.window.hide()
            restore.assert_not_called()

    def test_ocr_dismissal_restores_source_even_when_click_activated_before_pin(self):
        handle = int(self.window.winId())
        with patch('PyQt6.QtWidgets.QApplication.platformName', return_value='windows'), \
                patch('meikipop.utils.window_focus.foreground_is_fullscreen', return_value=False), \
                patch('meikipop.utils.window_focus.focus_pinned_popup'), \
                patch('meikipop.utils.window_focus.foreground_window') as foreground, \
                patch('meikipop.utils.window_focus.restore_foreground') as restore:
            for source, dismiss_foreground in ((123, handle), (456, 789)):
                with self.subTest(source=source):
                    foreground.return_value = source
                    self.window.show_entries((entry(),), peek=True)
                    foreground.return_value = handle
                    self.window.pin.setChecked(True)
                    self.assertEqual(self.window._previous_foreground, source)
                    foreground.return_value = dismiss_foreground
                    restore.reset_mock()
                    self.window.hide()
                    if dismiss_foreground == handle:
                        restore.assert_called_once_with(source)
                    else:
                        restore.assert_not_called()

    def test_capture_visibility_does_not_replace_source_or_restore_focus(self):
        self.window._previous_foreground = 123
        self.window._capture_visibility = True
        try:
            with patch.object(self.window, 'remember_foreground') as remember, \
                    patch('meikipop.utils.window_focus.restore_foreground') as restore:
                self.window.show()
                self.window.hide()
                remember.assert_not_called()
                restore.assert_not_called()
                self.assertEqual(self.window._previous_foreground, 123)
        finally:
            self.window._capture_visibility = False

    def test_translation_dismissal_and_new_hover_never_restore_old_sentence(self):
        self.window.translation_worker = Mock()
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("前の猫です。")
        self.window.pin.setChecked(True)
        self.window.submit(translate=True, context=True)
        old_revision = self.window.revision
        self.window.deliver(old_revision, SearchResult("前の猫です。", "ja", "en", translation="Old sentence"))
        self.window.hide()
        self.assertFalse(self.window._translation_view)
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("次の猫です。")
        self.window.pin.setChecked(True)
        self.window.submit(translate=True, context=True)
        self.assertEqual(self.window.translation_worker.request.call_args.args[1], "次の猫です。")
        self.window.deliver(old_revision, SearchResult("前の猫です。", "ja", "en", translation="Late old sentence"))
        self.assertEqual(self.window.translation_panel.source.toPlainText(), "次の猫です。")
        self.assertEqual(self.window.translation_browser.toPlainText(), "")

    def test_standalone_translation_edit_copy_swap_and_layout(self):
        self.window.translation_worker = Mock()
        self.window.open_translation()
        panel = self.window.translation_panel
        self.assertEqual(panel.source.toPlainText(), "")
        long_text = "A long source.\n" * 200
        panel.source.setPlainText(long_text)
        panel.copy_source.click()
        self.assertEqual(QApplication.clipboard().text(), long_text)
        panel.translate.click()
        revision = self.window.revision
        self.assertEqual(self.window.translation_worker.request.call_args.args[1], long_text.strip())
        self.window.deliver(revision, SearchResult(long_text.strip(), "en", "ja", translation="長い翻訳。"))
        panel.copy_output.click()
        self.assertEqual(QApplication.clipboard().text(), "長い翻訳。")
        selection = panel.source.textCursor()
        selection.select(QTextCursor.SelectionType.WordUnderCursor)
        panel.source.setTextCursor(selection)
        before = panel.source.selected_text()
        panel.set_side_by_side(True)
        self.assertEqual(panel.source.selected_text(), before)
        self.assertEqual(panel.splitter.orientation(), Qt.Orientation.Horizontal)
        panel.swap.click()
        self.assertEqual(panel.source.toPlainText(), "長い翻訳。")
        self.assertEqual(self.window._translation_content.source, "ja")
        self.assertEqual(self.window._translation_content.target, "en")
        self.assertEqual(panel.output.toPlainText(), "")

    def test_editing_source_cancels_stream_and_preserves_edit_cursor(self):
        self.window.translation_worker = Mock()
        self.window.open_translation()
        panel = self.window.translation_panel
        panel.source.setPlainText("old")
        panel.translate.click()
        old_revision = self.window.revision
        panel.source.setPlainText("new")
        panel.source.moveCursor(QTextCursor.MoveOperation.End)
        self.window._translation_progress(old_revision, SearchResult("old", "en", "ja", translation="obsolete"))
        self.window.deliver(old_revision, SearchResult("old", "en", "ja", translation="obsolete"))
        self.assertEqual(panel.source.toPlainText(), "new")
        self.assertEqual(panel.source.textCursor().position(), 3)
        self.assertFalse(self.window._translation_busy)
        self.assertEqual(panel.output.toPlainText(), "")
        self.window.translation_worker.cancel.assert_called()

    def test_hover_shortcut_is_independent_and_checks_collisions(self):
        self.assertIsNone(self.window._hover_keys)
        with patch("meikipop.gui.text_shortcuts.TextHotKeys") as hotkeys:
            self.window.apply_hover_shortcut("<ctrl>+<shift>+h", "Ctrl+Shift+H")
            with self.assertRaises(ValueError):
                self.window.apply_translation_shortcut("<shift>+<ctrl>+h")
            self.window.apply_hover_shortcut("")
            hotkeys.return_value.stop.assert_called_once()
            self.assertIsNone(self.window._hover_keys)

    def test_translation_shortcut_is_independent_recordable_and_disabled_by_default(self):
        self.assertIsNone(self.window._translation_keys)
        with patch("meikipop.gui.text_shortcuts.TextHotKeys") as hotkeys:
            self.window.apply_translation_shortcut("<ctrl>+<shift>+t", "Ctrl+Shift+T")
            self.assertIsNone(self.window._keys)
            self.assertEqual(self.settings.value("translation_hotkey"), "<ctrl>+<shift>+t")
            with self.assertRaises(ValueError):
                self.window.apply_shortcut("<shift>+<ctrl>+t")
            self.window.apply_translation_shortcut("")
            hotkeys.return_value.stop.assert_called_once()
            self.assertIsNone(self.window._translation_keys)

    def test_translation_settings_round_trip_and_shortcut_do_not_enable_ocr(self):
        dialog = SetupDialog(self.temp.name, self.settings, self.window.apply_shortcut, self.window)
        dialog.translation_split.setChecked(True)
        self.assertTrue(self.settings.value("translation_side_by_side", False, bool))
        self.assertEqual(self.window.translation_panel.splitter.orientation(), Qt.Orientation.Horizontal)
        with patch("meikipop.gui.text_shortcuts.TextHotKeys") as listener:
            dialog.translation_shortcut.enabled.setChecked(True)
            import sys
            self.assertEqual(self.settings.value("translation_hotkey"),
                             "<cmd>+<shift>+t" if sys.platform == "darwin" else "<ctrl>+<shift>+t")
            self.assertIsNone(self.window._keys)
            dialog.translation_shortcut.enabled.setChecked(False)
            listener.return_value.stop.assert_called_once()
        dialog.translation_chunk_size.setValue(512)
        from meikipop.dictionary.translation import load_profile_settings
        self.assertEqual(load_profile_settings(self.settings, self.window.preferred_foreign).chunk_size, 512)
        dialog.hide()

    def test_language_search_accepts_native_english_and_code(self):
        from meikipop.gui.language_chooser import LanguageChooser
        dialog = LanguageChooser(self.window, {"ja": "日本語", "tr": "Türkçe"})
        for query in ("ja", "Japanese", "日本語"):
            dialog.search.setText(query)
            self.assertEqual(dialog.selected_code(), "ja")
        dialog.search.setText("Turkish")
        self.assertEqual(dialog.selected_code(), "tr")

    def test_close_on_cursor_leave_respects_geometry_and_interaction(self):
        self.window.show()
        self.window._peek = True
        self.window.pin.setChecked(True)
        leave = QEvent(QEvent.Type.Leave)
        with patch("meikipop.gui.quick_lookup.QCursor.pos", return_value=QPoint(-500, -500)), \
                patch.object(self.window, "hide") as hide:
            self.window.leaveEvent(leave)
            hide.assert_not_called()
            self.settings.setValue("close_on_cursor_leave", True)
            with patch.object(QApplication, "activePopupWidget", return_value=Mock()):
                self.window.leaveEvent(leave)
            hide.assert_not_called()
            with patch.object(QApplication, "mouseButtons", return_value=Qt.MouseButton.LeftButton):
                self.window.leaveEvent(leave)
            hide.assert_not_called()
            with patch("meikipop.gui.quick_lookup.QCursor.pos", return_value=self.window.geometry().center()):
                self.window.leaveEvent(leave)
            hide.assert_not_called()
            self.window.leaveEvent(leave)
            hide.assert_called_once_with()

    def test_corner_search_ignores_cursor_leave(self):
        self.window.open_search()
        self.settings.setValue("close_on_cursor_leave", True)
        with patch("meikipop.gui.quick_lookup.QCursor.pos", return_value=QPoint(-500, -500)), \
                patch.object(self.window, "hide") as hide:
            self.window.leaveEvent(QEvent(QEvent.Type.Leave))
            hide.assert_not_called()

    def test_cursor_grace_area_tracks_distance_return_and_resizing(self):
        self.window.show_entries((entry(),), peek=True)
        self.window.pin.setChecked(True)
        self.settings.setValue("close_on_cursor_leave", True)
        self.settings.setValue("cursor_close_margin", 36)
        frame = self.window.frameGeometry()
        near = QPoint(frame.right() + 36, frame.center().y())
        with patch('meikipop.gui.quick_lookup.QCursor.pos', return_value=near) as cursor, \
                patch.object(self.window, 'hide') as hide:
            self.window.leaveEvent(QEvent(QEvent.Type.Leave))
            hide.assert_not_called()
            self.assertTrue(self.window.cursor_leave_timer.isActive())
            self.window.resize(self.window.width() + 50, self.window.height())
            self.window._check_cursor_leave()
            hide.assert_not_called()
            self.assertFalse(self.window.cursor_leave_timer.isActive())
            frame = self.window.frameGeometry()
            cursor.return_value = QPoint(frame.right() + 37, frame.center().y())
            self.window.leaveEvent(QEvent(QEvent.Type.Leave))
            hide.assert_called_once_with()

    def test_zero_cursor_grace_area_closes_at_edge(self):
        self.window.show_entries((entry(),), peek=True)
        self.settings.setValue("close_on_cursor_leave", True)
        self.settings.setValue("cursor_close_margin", 0)
        frame = self.window.frameGeometry()
        with patch('meikipop.gui.quick_lookup.QCursor.pos', return_value=QPoint(frame.right() + 1, frame.center().y())), \
                patch.object(self.window, 'hide') as hide:
            self.window.leaveEvent(QEvent(QEvent.Type.Leave))
            hide.assert_called_once_with()

    def test_cursor_grace_area_setting_is_shared_and_saved(self):
        dialog = SetupDialog(self.temp.name, self.settings, self.window.apply_shortcut, self.window)
        self.assertFalse(dialog.cursor_close_margin.isEnabled())
        self.assertEqual(dialog.cursor_close_margin.value(), 24)
        dialog.close_on_cursor_leave.setChecked(True)
        self.assertTrue(dialog.cursor_close_margin.isEnabled())
        dialog.cursor_close_margin.setValue(48)
        self.assertEqual(self.settings.value('cursor_close_margin', type=int), 48)
        dialog.close_on_cursor_leave.setChecked(False)
        self.assertFalse(dialog.cursor_close_margin.isEnabled())
        self.assertEqual(self.settings.value('cursor_close_margin', type=int), 48)
        dialog.hide()

    def test_translation_loading_animates_without_rebuilding_content(self):
        self.window._show_translation("猫", "ja", "en")
        self.window._set_translation_busy(True)
        view = self.window.translation_browser
        before = view.toHtml()
        dots = view.loading.text()
        view._animate_loading()
        self.assertNotEqual(view.loading.text(), dots)
        self.assertEqual(view.toHtml(), before)
        self.assertTrue(view.loading_timer.isActive())
        self.assertEqual(self.window.translate.accessibleName(), "Cancel translation")
        self.window._place_actions()
        self.assertTrue(self.window.translate.isHidden())
        self.window._set_translation_busy(False)
        self.assertTrue(view.loading.isHidden())
        self.assertFalse(view.loading_timer.isActive())

    def test_translation_selection_shortcut_looks_up_instead_of_closing(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.pin.setChecked(True)
        self.window._show_translation("猫", "ja", "en")
        view = self.window.translation_browser
        view.set_content("cat")
        view.setTextCursor(view.document().find("cat"))
        self.settings.setValue("close_on_cursor_leave", True)
        with patch.object(self.window, "lookup_word") as lookup, patch.object(self.window, "hide") as hide, \
                patch("meikipop.gui.quick_lookup.QCursor.pos", return_value=QPoint(-500, -500)):
            self.window.leaveEvent(QEvent(QEvent.Type.Leave))
            self.window.toggle_lookup()
            lookup.assert_called_once_with("cat")
            hide.assert_not_called()

    def test_copy_shortcut_copies_headword_selection_and_leaves_input_copy_native(self):
        self.window.show_entries((entry("語彙力"),), "語彙力")
        self.window.activateWindow()
        self.window.browser.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.window.browser, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "語彙力")
        cursor = self.window.browser.document().find("cat")
        self.window.browser.setTextCursor(cursor)
        QTest.keyClick(self.window.browser, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "cat")
        self.window.search.setText("input")
        self.window.search.selectAll()
        self.window.search.setFocus()
        QTest.keyClick(self.window.search, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "input")

    def test_profile_removal_cleans_language_data_and_survives_library_refresh(self):
        self.settings.setValue("profiles/tr/target", "en")
        self.window.update_languages(("ja", "tr"))
        self.window.set_mode("tr")
        self.window._display(SearchResult("old", "tr", "en", (entry("old", language="tr"),)))
        self.window._display(SearchResult("new", "tr", "en", (entry("new", language="tr"),)))
        download = Path(self.temp.name) / "kept-model"
        download.write_bytes(b"download")
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            dialog.sync_profile("tr")
            with patch("meikipop.gui.dictionary_manager.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
                    patch("meikipop.data_assets.remove_language_data") as remove:
                dialog.remove_profile()
                self.wait_until(lambda: dialog.operation is None)
                self.assertEqual(remove.call_args.args[0], "tr")
            self.assertEqual(self.window.preferred_foreign, "ja")
            self.assertEqual(self.settings.value("profile"), "ja")
            self.assertFalse(self.settings.contains("profiles/tr/target"))
            self.assertFalse(self.window._history)
            self.assertIsNone(self.window._result)
            self.assertEqual(download.read_bytes(), b"download")
            self.window.update_languages(("ja", "tr"))
            pack = (Path("tr-pack"), {"language": "tr", "title": "Turkish", "entries": 1, "enabled": True}, None)
            with patch("meikipop.gui.dictionary_manager.Library", return_value=SimpleNamespace(
                    packs=[pack], errors=[], close=Mock())):
                dialog.reload()
            self.assertEqual(self.window.source.findData("tr"), -1)
            self.assertEqual(dialog.profile.findData("tr"), -1)
            with patch("meikipop.gui.first_run.offer_resources"):
                dialog.add_profile("tr")
            self.assertGreaterEqual(self.window.source.findData("tr"), 0)
            self.assertEqual(self.settings.value("removed_profiles", [], type=list), [])
        finally:
            dialog.deleteLater()

    def test_profile_removal_can_be_cancelled_and_keeps_one_language(self):
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            with patch("meikipop.gui.dictionary_manager.QMessageBox.question",
                       return_value=QMessageBox.StandardButton.No) as confirm:
                dialog.remove_profile()
                self.assertTrue(self.settings.contains("profiles/ja/target"))
                while dialog.profile.count() > 1:
                    dialog.profile.removeItem(dialog.profile.count() - 1)
                remaining = dialog.profile.currentData()
                confirm.reset_mock()
                dialog.remove_profile()
                confirm.assert_not_called()
                self.assertEqual(dialog.profile.currentData(), remaining)
        finally:
            dialog.deleteLater()

    def test_pinned_meanings_are_unlimited_even_with_old_limit_settings(self):
        senses = [f"Meaning {i}" for i in range(8)]
        structured = {"type": "structured-content", "content": {"tag": "ol", "content": [
            {"tag": "li", "content": text} for text in senses]}}
        for definitions in (senses, [structured]):
            result = SearchResult('test', 'tr', 'en', (entry(language='tr', definitions=definitions),))
            self.settings.setValue("profiles/ja/pinned_definitions", 2)
            self.window.show_entries(result.entries, "test", peek=True)
            self.window.pin.setChecked(True)
            for sense in senses:
                self.assertIn(sense, self.window.browser.toPlainText())
            self.assertNotIn('href="expand:', self.window.browser.toHtml())

    def test_default_preview_and_pin_preferences_preserve_full_context(self):
        from meikipop.gui.quick_lookup import audio_autoplay_mode
        self.settings.remove("profiles/ja/audio_autoplay_mode")
        self.window.audio = Mock()
        word = entry(definitions=("first", "second", "third", "fourth"))
        self.window.show_entries((word,), "cat", peek=True)
        self.window.set_context("Original sentence")
        text = self.window.browser.toPlainText()
        self.assertIn("first", text)
        self.assertNotIn("second", text)
        self.window.audio.play.assert_not_called()
        self.window.pin.setChecked(True)
        self.assertIn("fourth", self.window.browser.toPlainText())
        self.assertEqual(audio_autoplay_mode(self.settings, "ja"), "pin")
        self.window.audio.play.assert_called_once()
        self.assertNotIn("Original sentence", self.window.browser.toPlainText())
        self.assertEqual(self.window._result_context, "Original sentence")

    def test_more_click_keeps_window_geometry_and_scroll_position(self):
        words = tuple(entry(source=f"Source {index}", definitions=(disclosure([
            {"tag": "div", "content": f"Meaning {index}:{sense}"} for sense in range(9)]),))
            for index in range(6))
        self.window.show_entries(words, "cat")
        self.app.processEvents()
        browser = self.window.browser
        cursor = browser.document().find("More")
        browser.verticalScrollBar().setValue(20)
        cursor.setPosition(cursor.selectionStart() + 1)
        point = browser.cursorRect(cursor).center()
        self.assertEqual(browser.anchorAt(point), "details:0:0:0")
        geometry = self.window.geometry()
        scroll = browser.verticalScrollBar().value()
        scroll_changes = []
        browser.verticalScrollBar().valueChanged.connect(scroll_changes.append)
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertNotIn(0, scroll_changes)
        self.wait_until(lambda: not self.window.render_timer.isActive())
        self.app.processEvents()
        self.assertIn("Meaning 0:8", browser.toPlainText())
        self.assertEqual(browser.verticalScrollBar().value(), scroll)
        self.assertEqual(self.window.geometry(), geometry)
        self.assertFalse(self.window.fit_timer.isActive())

    def test_disclosure_waits_for_native_mouse_release(self):
        self.window.show_entries((entry(definitions=(disclosure(
            [{"tag": "div", "content": f"Meaning {i}"} for i in range(8)]),)),), "cat")
        self.app.processEvents()
        browser = self.window.browser
        cursor = browser.document().find("More")
        cursor.setPosition(cursor.selectionStart() + 1)
        point = browser.cursorRect(cursor).center()
        with patch.object(browser, "setHtml", wraps=browser.setHtml) as render:
            QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
            render.assert_not_called()
            self.assertNotIn("Meaning 7", browser.toPlainText())
            self.wait_until(lambda: not self.window.link_timer.isActive())
            render.assert_called_once()
            self.assertIn("Meaning 7", browser.toPlainText())

    def test_more_does_not_follow_text_displaced_by_expanding_earlier_entries(self):
        words = tuple(entry(language="en", definitions=(disclosure(
            [{"tag": "div", "content": f"Entry {index} meaning {sense}"} for sense in range(12)],
            lead=[{"tag": "div", "content": f"Lead {index}:{i}"} for i in range(8)]),))
            for index in range(5))
        self.window._reading_size_custom = True
        self.window.resize(480, 240)
        self.window.show_entries(words, "cat", source="en", peek=True)
        self.window.pin.setChecked(True)
        self.app.processEvents()
        browser = self.window.browser
        bar = browser.verticalScrollBar()
        cursor = browser.document().find("More")
        cursor.setPosition(cursor.selectionStart() + 1)
        bar.setValue(bar.value() + browser.cursorRect(cursor).center().y() - browser.viewport().height() // 2)
        point = browser.cursorRect(cursor).center()
        self.assertTrue(browser.viewport().rect().contains(point))
        self.assertGreater(bar.value(), 0)
        scroll, geometry = bar.value(), self.window.geometry()
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.wait_until(lambda: not self.window.link_timer.isActive())
        self.app.processEvents()
        self.assertIn("Entry 0 meaning 11", browser.toPlainText())
        self.assertEqual(bar.value(), scroll)
        self.assertEqual(self.window.geometry(), geometry)

    def test_queued_disclosure_cannot_change_a_new_document(self):
        self.window.show_entries((entry(definitions=("first", "second", "third", "fourth")),), "cat")
        self.window.browser.anchorClicked.emit(QUrl("expand:0:0"))
        self.window._display(SearchResult("new", "ja", "en", (entry("new"),)))
        self.app.processEvents()
        self.assertFalse(self.window._expanded)
        self.assertFalse(self.window._details_expanded)

    def test_first_preview_click_does_not_queue_a_disclosure(self):
        self.window.show_entries((entry(),), "cat", peek=True)
        self.window._pin_anchor_click = True
        self.window.browser.anchorClicked.emit(QUrl("details:0:0:0"))
        self.app.processEvents()
        self.assertFalse(self.window.link_timer.isActive())
        self.assertFalse(self.window._details_expanded)

    def test_preview_options_limit_first_dictionary_without_changing_pinned_results(self):
        from meikipop.dictionary.pitch import Pitch
        first = replace(entry(definitions=("first meaning", "second meaning", "third meaning")),
                        frequencies=(Frequency("Rank", 123, "123"),), pitches=(Pitch("Pitch", "ねこ", 1),))
        self.settings.setValue("profiles/ja/preview_frequency", False)
        self.settings.setValue("profiles/ja/preview_pitch", False)
        self.settings.setValue("profiles/ja/preview_definitions", 1)
        self.window.show_entries((first, entry(source="Other", definitions=("other meaning",))), "猫", peek=True)
        text = self.window.browser.toPlainText()
        self.assertIn("first meaning", text)
        for hidden in ("second meaning", "other meaning", "#123", "ねこ [1]"):
            self.assertNotIn(hidden, text)
        self.settings.setValue("profiles/ja/preview_definitions", 2)
        self.settings.setValue("profiles/ja/preview_pitch", True)
        self.window._render()
        text = self.window.browser.toPlainText()
        self.assertIn("second meaning", text)
        self.assertIn("ねこ [1]", text)
        self.assertNotIn("third meaning", text)
        self.window.pin.setChecked(True)
        text = self.window.browser.toPlainText()
        self.assertIn("other meaning", text)
        self.assertIn("#123", text)
        self.settings.setValue("profiles/ja/pinned_frequency", False)
        self.settings.setValue("profiles/ja/pinned_pitch", False)
        self.window._render()
        self.assertNotIn("#123", self.window.browser.toPlainText())
        self.assertNotIn("ねこ [1]", self.window.browser.toPlainText())

    def test_plain_kana_fallback_when_matching_pitch_is_missing_or_hidden(self):
        from meikipop.dictionary.pitch import Pitch
        word = entry()
        for pitches, preview_pitch in (((), True), ((Pitch("Pitch", "びょう", 1),), True),
                                        ((Pitch("Pitch", "ねこ", 1),), False)):
            with self.subTest(pitches=pitches, preview_pitch=preview_pitch):
                result = SearchResult("猫", "ja", "en", (replace(word, pitches=pitches),))
                self.window.browser.setHtml(render_result(result, preview=True, preview_pitch=preview_pitch))
                self.assertIn("猫 [ねこ]", self.window.browser.toPlainText())
        result = SearchResult("猫", "ja", "en", (replace(word, pitches=(Pitch("Pitch", "ねこ", 1),)),))
        self.window.browser.setHtml(render_result(result, preview=True))
        self.assertIn("ねこ [1]", self.window.browser.toPlainText())
        self.assertNotIn("[ねこ]", self.window.browser.toPlainText())

    def test_search_arrows_navigate_sticky_sections_without_editing_query(self):
        browser = self.window.browser
        browser.setHtml(render_result(SearchResult("猫", "ja", "en", tuple(
            entry(source=f"Source {i}", definitions=("meaning\n" * 20,)) for i in range(4))),
            expanded=tuple(f"Source {i}" for i in range(4))))
        self.window.search.setText("猫")
        self.window.search.selectAll()
        browser.section_scroll.set_enabled(True)
        browser.section_scroll.animation_enabled = False
        self.window.show()
        self.app.processEvents()
        self.window.search.setFocus()
        bar = browser.verticalScrollBar()
        bar.setValue(0)
        QTest.keyClick(self.window.search, Qt.Key.Key_Down)
        self.assertGreater(bar.value(), 0)
        self.assertEqual(self.window.search.text(), "猫")
        self.assertEqual(self.window.search.selectedText(), "猫")
        QTest.keyClick(self.window.search, Qt.Key.Key_Up)
        self.assertEqual(bar.value(), 0)
        QTest.keyClick(self.window.search, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(bar.value(), 0)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/target", "en")
        for profile in ("ja", "tr", "id"):
            self.settings.setValue(f"profiles/{profile}/audio_autoplay_mode", "off")
        self.model_status_patch = patch("meikipop.language.stanza_analyzer.model_status", return_value="Model needed")
        self.model_status = self.model_status_patch.start()
        self.addCleanup(self.model_status_patch.stop)
        self.engine = FakeEngine()
        self.window = QuickLookupWindow(self.temp.name, lambda: self.engine, self.settings)

    def tearDown(self):
        self.window.shutdown()
        self.window.worker._thread.join(timeout=2)
        if self.window.translation_worker is not None:
            self.window.translation_worker._thread.join(timeout=2)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for background operation")

    def test_edit_invalidates_old_result_before_debounce_dispatches(self):
        self.window.search.setText("old")
        revision = self.window.revision
        self.window.search.setText("new")
        self.assertGreater(self.window.revision, revision)
        self.assertTrue(self.window.debounce.isActive())
        self.window.deliver(revision, SearchResult("old", "ja", "en", (entry("OLD"),)))
        self.assertNotIn("OLD", self.window.browser.toPlainText())

    def test_dictionary_readings_use_ruby_unless_explicitly_disabled(self):
        definition = {"type": "structured-content", "content": {"tag": "ruby", "content": [
            "猫", {"tag": "rt", "content": "ねこ"}]}}
        result = entry(definitions=(definition,))
        self.window.show_entries((result,), "猫")
        self.assertIn('\ufffc', self.window.browser.document().toPlainText())
        self.settings.setValue("profiles/ja/definition_furigana", False)
        self.window._render()
        self.assertIn("猫 [ねこ]", self.window.browser.toPlainText())

    def test_empty_font_setting_uses_application_default_family(self):
        from PyQt6.QtGui import QFont
        self.settings.setValue("profiles/ja/font_family", "")
        self.window.reload_appearance()
        self.assertEqual(self.window.browser.font().family(), QFont().family())

    def test_snap_scrolling_saves_per_profile_without_replacing_the_document(self):
        self.window.show_entries((entry(),), "猫")
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            dialog.appearance.save()
            self.assertFalse(dialog.appearance.snap_scrolling.isChecked())
            self.assertFalse(self.window.browser.section_scroll.enabled)
            with patch.object(self.window.browser, "setHtml", wraps=self.window.browser.setHtml) as render:
                dialog.appearance.snap_scrolling.setChecked(True)
                render.assert_not_called()
            self.assertTrue(self.settings.value("profiles/ja/snap_scrolling", False, bool))
            self.assertTrue(self.window.browser.section_scroll.enabled)
            dialog.sync_profile("tr")
            self.assertFalse(dialog.appearance.snap_scrolling.isChecked())
            self.assertFalse(self.window.browser.section_scroll.enabled)
            dialog.sync_profile("ja")
            self.assertTrue(dialog.appearance.snap_scrolling.isChecked())
            self.assertTrue(self.window.browser.section_scroll.enabled)
        finally:
            dialog.deleteLater()

    def test_disabling_snap_adds_rules_between_headwords_only(self):
        from PyQt6.QtGui import QTextFormat
        self.settings.setValue("profiles/ja/snap_scrolling", True)
        self.window.reload_appearance()
        self.window.show_entries((entry(), entry("犬")), "猫")
        def rules():
            count, block = 0, self.window.browser.document().begin()
            while block.isValid():
                count += block.blockFormat().hasProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth)
                block = block.next()
            return count
        self.assertEqual(rules(), 0)
        self.settings.setValue("profiles/ja/snap_scrolling", False)
        self.window.reload_appearance()
        self.assertEqual(rules(), 1)
        self.settings.setValue("profiles/ja/snap_scrolling", True)
        self.window.reload_appearance()
        self.assertEqual(rules(), 0)

    def test_preview_and_pinned_grammar_are_independent_and_keep_lemma_label(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "span", "data": {"class": "tag"}, "content": "intransitive verb"}, "meaning"]}
        word = replace(entry(definitions=(definition,)), inflection=("lemma",))
        self.settings.setValue("profiles/ja/preview_grammar", True)
        self.settings.setValue("profiles/ja/pinned_grammar", False)
        self.window.show_entries((word,), "猫", peek=True)
        self.assertIn("[intransitive]", self.window.browser.toPlainText())
        self.assertIn("lemma", self.window.browser.toPlainText())
        tag = self.window.browser.document().find("[intransitive]")
        gloss = self.window.browser.document().find("meaning")
        self.assertNotEqual(tag.block().position(), gloss.block().position())
        self.window.pin.setChecked(True)
        self.assertNotIn("[intransitive]", self.window.browser.toPlainText())
        self.assertNotIn("lemma", self.window.browser.toPlainText())
        self.settings.setValue("profiles/ja/pinned_grammar", True)
        self.window._render()
        self.assertIn("[intransitive]", self.window.browser.toPlainText())
        self.assertIn("lemma", self.window.browser.toPlainText())

    def test_collapsed_dictionaries_keep_headings_and_compact_ocr_definitions(self):
        definition = {"type": "structured-content", "content": {"tag": "div", "content": [
            {"tag": "div", "data": {"class": "level1"}, "content": f"Meaning {index}"}
            for index in range(9)]}}
        mono = entry(source="Monolingual", definitions=(definition,))
        result = SearchResult("猫", "ja", "en", (entry(), mono))
        closed = render_result(result, expanded=("Dictionary", "Monolingual"), collapsed=("Monolingual",))
        self.assertIn("Monolingual", closed)
        self.assertIn('href="collapse:0:1" title="Expand"', closed)
        self.assertIn("cat", closed)
        self.assertNotIn("Meaning", closed)
        preview = render_result(SearchResult("猫", "ja", "en", (mono,)), preview=True, collapsed=("Monolingual",))
        self.assertIn("Meaning 0", preview)

    def test_pin_respects_dictionary_defaults_and_expansion_stays_local(self):
        self.settings.setValue("profiles/ja/collapsed_dictionaries", ["Monolingual"])
        mono = entry(source="Monolingual", definitions=("first meaning", "second meaning", "third meaning", "last meaning"))
        self.window.show_entries((entry(), mono), "猫", peek=True)
        self.window.pin.setChecked(True)
        self.assertIn("cat", self.window.browser.toPlainText())
        self.assertNotIn("first meaning", self.window.browser.toPlainText())
        self.window._link(QUrl("expand:1"))
        self.assertIn("last meaning", self.window.browser.toPlainText())
        self.window._render()
        self.assertIn("last meaning", self.window.browser.toPlainText())
        self.assertEqual(self.settings.value("profiles/ja/collapsed_dictionaries", [], type=list), ["Monolingual"])

        self.window._link(QUrl("expand:1"))
        self.assertNotIn("first meaning", self.window.browser.toPlainText())
        self.window.set_compact_preview(False)
        self.assertNotIn("first meaning", self.window.browser.toPlainText())

    def test_pin_keeps_expanded_preview_and_collapsed_dictionary_defaults(self):
        self.settings.setValue("profiles/ja/expanded_dictionaries", ["Full"])
        self.settings.setValue("profiles/ja/collapsed_dictionaries", ["Closed"])
        entries = tuple(entry(source=source, definitions=tuple(f"{source} meaning {i}" for i in range(6)))
                        for source in ("Full", "Preview", "Closed"))
        self.window.show_entries(entries, "猫", peek=True)
        self.window.pin.setChecked(True)
        text = self.window.browser.toPlainText()
        self.assertIn("Full meaning 5", text)
        self.assertIn("Preview meaning 0", text)
        self.assertIn("Preview meaning 5", text)
        self.assertNotIn("Closed meaning 0", text)
        self.window._link(QUrl("expand:1"))
        self.assertIn("Preview meaning 5", self.window.browser.toPlainText())
        self.window.pin.setChecked(False)
        self.window.pin.setChecked(True)
        self.assertIn("Preview meaning 5", self.window.browser.toPlainText())

    def test_pinned_dictionary_toggle_matches_display_and_preserves_scroll(self):
        active = patch.object(self.window, "isActiveWindow", return_value=True)
        active.start()
        self.addCleanup(active.stop)
        self.settings.setValue("profiles/ja/expanded_dictionaries", ['First', 'Second', 'Third'])
        for compact in (True, False):
            with self.subTest(compact=compact):
                self.window.hide()
                self.window.set_compact_preview(compact)
                lead = entry(source="First", definitions=tuple(f"Lead {i}" for i in range(20)))
                target = entry(source="Second", definitions=("one", "two", "three", "Fourth sense"))
                tail = entry(source="Third", definitions=tuple(f"Tail {i}" for i in range(30)))
                self.window.show_entries((lead, target, tail), "猫", peek=True)
                self.window.pin.setChecked(True)
                self.app.processEvents()
                browser = self.window.browser
                bar = browser.verticalScrollBar()
                bar.setValue(20)
                scroll = bar.value()
                self.assertGreater(scroll, 0)
                for expanded in (False, True, False):
                    before = browser.toHtml()
                    self.assertIn('href="collapse:0:1"', before)
                    self.assertEqual("Fourth sense" in browser.toPlainText(), not expanded)
                    self.window._link(QUrl("collapse:1"))
                    self.app.processEvents()
                    self.assertEqual("Second" in self.window._collapsed, not expanded)
                    self.assertEqual("Fourth sense" in browser.toPlainText(), expanded)
                    cursor = browser.document().find("Second")
                    cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)
                    self.assertEqual(cursor.selectedText(), "Second")
                    self.assertEqual(bar.value(), scroll)

    def test_dictionary_labels_collapse_independently_and_restore_full_content(self):
        self.settings.setValue("profiles/ja/expanded_dictionaries", ["First"])
        first = entry(source="First", definitions=tuple(f"sense {i}" for i in range(6)))
        second = entry(source="Second", definitions=("other meaning",))
        self.window.show_entries((first, second), "猫")
        self.assertIn("sense 5", self.window.browser.toPlainText())
        self.window._link(QUrl("collapse:0"))
        text = self.window.browser.toPlainText()
        self.assertIn("First", text)
        self.assertNotIn("sense 0", text)
        self.assertIn("other meaning", text)
        self.window._link(QUrl("collapse:1"))
        self.assertNotIn("other meaning", self.window.browser.toPlainText())
        self.window._link(QUrl("collapse:0"))
        self.assertIn("sense 5", self.window.browser.toPlainText())
        self.assertNotIn("other meaning", self.window.browser.toPlainText())
        self.assertEqual(self.settings.value("profiles/ja/expanded_dictionaries"), ["First"])

    def test_same_dictionary_sections_collapse_independently_between_readings(self):
        words = tuple(replace(entry("参", "Jitendex", tuple(f"{reading} sense {i}" for i in range(6))),
                              reading=reading) for reading in ("さん", "み", "しん"))
        self.settings.setValue("profiles/ja/expanded_dictionaries", ["Jitendex"])
        self.window.show_entries(words, "参")
        self.window._link(QUrl("collapse:1:0"))
        text = self.window.browser.toPlainText()
        self.assertIn("さん sense 5", text)
        self.assertNotIn("み sense 0", text)
        self.assertIn("しん sense 5", text)
        self.window._link(QUrl("collapse:1:0"))
        self.assertIn("み sense 5", self.window.browser.toPlainText())
        self.assertEqual(self.settings.value("profiles/ja/expanded_dictionaries"), ["Jitendex"])
        self.window.set_dictionary_display("Jitendex", "collapsed")
        self.window._link(QUrl("collapse:1:0"))
        text = self.window.browser.toPlainText()
        self.assertIn("み sense 0", text)
        self.assertNotIn("さん sense 0", text)
        self.assertNotIn("しん sense 0", text)
        self.window._display(SearchResult("参", "ja", "en", tuple(reversed(words))))
        text = self.window.browser.toPlainText()
        self.assertIn("み sense 0", text)
        self.assertNotIn("さん sense 0", text)
        self.assertNotIn("しん sense 0", text)

    def test_more_expands_only_its_reading_and_back_restores_section_states(self):
        words = tuple(replace(entry("参", "Jitendex", (disclosure(f"{reading} example"),)),
                              reading=reading) for reading in ("さん", "み"))
        self.window.show_entries(words, "参")
        self.window._link(QUrl("details:1:0:0"))
        text = self.window.browser.toPlainText()
        self.assertNotIn("さん example", text)
        self.assertIn("み example", text)
        self.window._display(SearchResult("犬", "ja", "en", (entry("犬"),)))
        self.window.go_back()
        text = self.window.browser.toPlainText()
        self.assertNotIn("さん example", text)
        self.assertIn("み example", text)

    def test_archive_owned_image_only_definition_is_retained(self):
        path = "meikipop-image:/ja-" + "a" * 64 + "/" + "b" * 64 + ".png"
        value = SearchResult("diagram", "ja", "en", (
            entry(definitions=({"type": "image", "path": path, "width": 600, "height": 300},)),))
        html = render_result(value, expanded=("Dictionary",))
        self.assertIn('<img src="' + path + '" width="320" height="160">', html)

    def test_back_restores_manual_dictionary_expansion_and_new_lookup_uses_defaults(self):
        self.settings.setValue("profiles/ja/collapsed_dictionaries", ["Dictionary"])
        self.window._display(SearchResult("猫", "ja", "en", (entry(),)))
        self.window._link(QUrl("expand:0"))
        self.assertIn("cat", self.window.browser.toPlainText())
        self.window._display(SearchResult("犬", "ja", "en", (entry("犬", definitions=("dog",)),)))
        self.assertNotIn("dog", self.window.browser.toPlainText())
        self.window.go_back()
        self.assertIn("cat", self.window.browser.toPlainText())
        self.window._link(QUrl("expand:0"))
        self.window._display(SearchResult("犬", "ja", "en", (entry("犬", definitions=("dog",)),)))
        self.window.go_back()
        self.assertNotIn("cat", self.window.browser.toPlainText())

    def test_dictionary_collapse_setting_is_independent_of_enablement_and_profile(self):
        from meikipop.dictionary.library import import_yomitan
        archive = Path(self.temp.name) / "monolingual.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("index.json", json.dumps(dict(title="Monolingual", format=3, sourceLanguage="ja")))
            zf.writestr("term_bank_1.json", json.dumps([["猫", "ねこ", "", "", 1, ["mono definition"]]]))
        import_yomitan(archive, self.temp.name)
        self.window.show_entries((entry(source="Monolingual", definitions=("mono definition",)),), "猫")
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            self.assertFalse(dialog.dictionary_display.isEnabled())
            dialog.packs.setCurrentRow(0)
            self.assertTrue(dialog.dictionary_display.isEnabled())
            dialog.dictionary_display.setCurrentIndex(dialog.dictionary_display.findData("collapsed"))
            self.assertEqual(self.settings.value("profiles/ja/collapsed_dictionaries", [], type=list), ["Monolingual"])
            self.assertEqual(dialog.packs.currentItem().checkState(), Qt.CheckState.Checked)
            self.assertNotIn("mono definition", self.window.browser.toPlainText())
            dialog.sync_profile("tr")
            self.assertFalse(dialog.dictionary_display.isEnabled())
            self.assertEqual(self.settings.value("profiles/tr/collapsed_dictionaries", [], type=list), [])
            dialog.sync_profile("ja")
            self.assertEqual(dialog.dictionary_display.currentData(), "collapsed")
            import_yomitan(archive, self.temp.name)
            dialog.reload()
            self.assertEqual(dialog.dictionary_display.currentData(), "collapsed")
            self.assertEqual(dialog.dictionary_display.findData("preview"), -1)
            dialog.dictionary_display.setCurrentIndex(dialog.dictionary_display.findData("expanded"))
            self.assertEqual(self.settings.value("profiles/ja/collapsed_dictionaries", [], type=list), [])
            self.assertIn("mono definition", self.window.browser.toPlainText())
            dialog.dictionary_display.setCurrentIndex(dialog.dictionary_display.findData("expanded"))
            self.assertEqual(self.settings.value("profiles/ja/expanded_dictionaries", [], type=list), ["Monolingual"])
            self.assertIn("Monolingual", self.window._expanded)
            dialog.reload()
            self.assertEqual(dialog.dictionary_display.currentData(), "expanded")
            dialog.dictionary_display.setCurrentIndex(dialog.dictionary_display.findData("collapsed"))
            self.assertEqual(self.settings.value("profiles/ja/expanded_dictionaries", [], type=list), [])
            self.assertNotIn("Monolingual", self.window._expanded)
        finally:
            dialog.deleteLater()

    def test_morphology_option_follows_profile_for_dictionary_lookup_only(self):
        self.settings.setValue("profiles/tr/morphology", False)
        self.model_status.return_value = "Installed"
        self.window.set_mode("tr")
        self.window.search.setText("kitaplarımdan")
        with patch.object(self.window.worker, "request") as request:
            self.window.submit(translate=False)
            self.assertTrue(request.call_args.kwargs["morphology"])
            self.window.set_mode("ja")
            self.window.submit(translate=False)
            self.assertFalse(request.call_args.kwargs["morphology"])

    def test_autoplay_remembers_all_words_until_scan_hold_ends(self):
        self.settings.setValue("profiles/ja/audio_autoplay_mode", "lookup")
        with patch.object(self.window, "play_audio") as play:
            self.window.scan_hold_changed(True)
            for word in ("猫", "犬", "猫", "犬"):
                self.window.show_entries((entry(word),), text=word, peek=True)
            self.assertEqual(play.call_count, 2)
            self.window.scan_hold_changed(False)
            self.window.scan_hold_changed(True)
            self.window.show_entries((entry("犬"),), text="犬", peek=True)
            self.assertEqual(play.call_count, 3)
            self.window.show_entries((entry("猫"),), text="猫", peek=True)
            self.assertEqual(play.call_count, 4)

    def test_manual_audio_can_repeat_during_hold(self):
        self.window.audio = Mock()
        self.window.scan_hold_changed(True)
        self.window.show_entries((entry(),), text="猫", peek=True)
        self.window.play_audio()
        self.window.play_audio()
        self.assertEqual(self.window.audio.play.call_count, 2)

    def test_cached_settings_follow_active_profile_and_live_theme(self):
        from meikipop.config.config import config
        self.settings.setValue("profiles/ja/theme_name", "Light")
        self.settings.setValue("profiles/tr/theme_name", "Dusk")
        self.window.open_settings()
        dialog = self.window._setup
        dialog.hide()
        self.window.set_mode("tr")
        self.window.open_settings()
        self.assertEqual(dialog.profile.currentData(), "tr")
        self.assertEqual(dialog.appearance.theme.currentText(), "Dark")
        self.assertEqual(config.color_background, "#000000")
        self.assertEqual(config.color_highlight_word, "#FFFFFF")
        dialog.appearance.theme.setCurrentText("Custom")
        dialog.appearance.set_color("color_highlight_word", "#eeeeee")
        dialog.appearance.save()
        self.assertEqual(config.color_highlight_word, "#eeeeee")
        dialog.profile.setCurrentIndex(dialog.profile.findData("ja"))
        self.assertEqual(self.window.preferred_foreign, "ja")
        self.assertEqual(dialog.appearance.theme.currentText(), "Light")
        self.assertEqual(config.color_background, "#FFFFFF")
        self.assertEqual(self.settings.value("profiles/tr/theme_name"), "Custom")
        dialog.hide()

    def test_back_restores_profile_appearance_and_saved_identity(self):
        from meikipop.config.config import config
        self.settings.setValue("profiles/ja/theme_name", "Light")
        self.settings.setValue("profiles/tr/theme_name", "Dusk")
        self.window.set_mode("tr")
        old = SearchResult("ev", "tr", "en", (entry("ev", language="tr"),))
        self.window.show_entries((entry(),), "猫")
        self.window.set_mode("ja")
        self.window._history = [(old, "ev", "tr", "en", (), 0)]
        self.window.go_back()
        self.assertEqual(self.window.preferred_foreign, "tr")
        self.assertEqual(self.settings.value("profile"), "tr")
        self.assertEqual(config.color_background, "#000000")
        self.assertEqual(config.color_highlight_word, "#FFFFFF")

    def test_translate_runs_off_main_thread_and_enter_search_is_local(self):
        self.window.search.setText("猫")
        self.window.submit(translate=True)
        self.assertTrue(self.window.translate.isEnabled())
        self.assertEqual(self.window.translate.toolTip(), "Cancel translation")
        self.wait_until(lambda: self.window._result is not None)
        self.assertTrue(self.window.translate.isEnabled())
        self.assertTrue(self.engine.calls[0][3])
        self.assertNotEqual(threading.get_ident(), self.engine.calls[0][4])
        self.assertIn("translated", self.window.translation_browser.toPlainText())
        self.window.search.returnPressed.emit()
        self.wait_until(lambda: len(self.engine.calls) == 2)
        self.assertFalse(self.engine.calls[1][3])

    def test_input_word_lookup_keeps_sentence_for_worker_translation_audio_copy_and_back(self):
        sentence = "Bu meslek zor."
        self.window.set_mode("tr")
        self.window.open_search(sentence)
        self.wait_until(lambda: self.window._result is not None)
        self.window.search.setSelection(sentence.index("meslek"), len("meslek"))
        self.window.search.returnPressed.emit()
        self.wait_until(lambda: self.window._result.text == "meslek")
        self.assertEqual(self.engine.calls[-1][0], "meslek")
        self.assertFalse(self.engine.calls[-1][3])
        self.assertEqual(self.engine.contexts[-1], (sentence, 3, 9))
        self.assertEqual(self.window.search.text(), sentence)
        self.assertEqual(self.window._context, sentence)
        self.window.audio = Mock()
        self.window.sentence_audio_button.click()
        self.assertEqual(self.window.audio.play_text.call_args.args[0], sentence)
        self.window.translate.click()
        self.wait_until(lambda: bool(self.window._result.translation))
        self.assertEqual(self.engine.calls[-1][0], sentence)
        self.assertTrue(self.engine.calls[-1][3])
        self.assertEqual(self.window._result.entries[0].term, "meslek")
        self.window.go_back()
        self.assertEqual(self.window._result.text, "meslek")
        self.assertEqual(self.window.search.text(), sentence)
        self.assertEqual(self.window._context, sentence)

        with patch("meikipop.gui.quick_lookup.QApplication.clipboard") as clipboard:
            self.window.copy_sentence()
            clipboard.return_value.setText.assert_called_once_with(sentence)
        self.assertFalse(self.window.isVisible())

    def test_input_selection_shortcut_and_menu_use_japanese_word_and_context(self):
        sentence = "公園で猫が寝ている。"
        self.window.open_search(sentence)
        self.wait_until(lambda: self.window._result is not None)
        self.window.search.setSelection(sentence.index("猫"), 1)
        with patch.object(self.window.search, "hasFocus", return_value=True):
            self.window.toggle_lookup()
        self.wait_until(lambda: self.window._result.text == "猫")
        self.assertEqual(self.engine.contexts[-1], (sentence, 3, 4))
        self.assertTrue(self.window.isVisible())
        self.window.search.setSelection(sentence.index("公園"), 2)
        with patch.object(self.window.search, "createStandardContextMenu") as menu:
            self.window._input_menu(QPoint(1, 1))
            label, action = menu.return_value.addAction.call_args.args
            self.assertEqual(label, "Look up")
            action()
        self.wait_until(lambda: self.window._result.text == "公園")
        self.assertEqual(self.window._context, sentence)

    def test_editing_invalidates_pending_input_context_and_cancel_restores_sentence(self):
        sentence = "Bu meslek zor."
        self.window.open_search(sentence)
        self.wait_until(lambda: self.window._result is not None)
        self.window.search.setSelection(3, 6)
        self.window.search.returnPressed.emit()
        self.wait_until(lambda: self.window._result.text == "meslek")
        with patch.object(self.window.worker, "request"):
            self.window.submit(selection=True)
            self.window._invalidate()
            self.window._restore_actions()
            self.assertEqual(self.window._context, sentence)
            self.window.submit(selection=True)
            revision = self.window.revision
            self.window.search.setText("new")
            self.window.deliver(revision, SearchResult("meslek", "tr", "en", (entry("meslek"),)))
            self.assertEqual(self.window._context, "")
            self.assertFalse(self.window.copy_button.isEnabled())

    def test_input_context_span_accounts_for_utf16_and_trimmed_whitespace(self):
        self.window.open_search("  😀 Bu meslek zor.  ")
        self.wait_until(lambda: self.window._result is not None)
        self.window.search.setSelection(7, 8)
        self.window.search.returnPressed.emit()
        self.wait_until(lambda: self.window._result.text == "meslek")
        self.assertEqual(self.engine.contexts[-1], ("😀 Bu meslek zor.", 5, 11))

    def test_slow_translation_does_not_block_new_lookup_or_overwrite_it(self):
        entered, release = threading.Event(), threading.Event()
        original = self.engine.search

        def slow(text, **kwargs):
            if kwargs.get("translate"):
                entered.set()
                release.wait(3)
            return original(text, **kwargs)

        self.engine.search = slow
        self.assertIsNone(self.window.translation_worker)
        try:
            self.window.search.setText("old")
            self.window.submit(translate=True)
            self.wait_until(entered.is_set)
            self.assertTrue(self.window.translate.isEnabled())
            self.window.search.setText("new")
            self.assertTrue(self.window.translate.isEnabled())
            self.window.submit()
            self.wait_until(lambda: self.window._result is not None and self.window._result.text == "new")
            self.assertFalse(release.is_set())
            release.set()
            self.wait_until(lambda: any(call[3] for call in self.engine.calls))
            self.app.processEvents()
            self.assertEqual(self.window._result.text, "new")
            self.assertNotIn("translated", self.window.browser.toPlainText())
        finally:
            release.set()

    def test_pending_and_active_translation_are_cancelled_on_edit(self):
        translator = SimpleNamespace(cancel=Mock())
        engine = FakeEngine()
        engine.translator = translator
        self.window.translation_worker = LookupWorker(engine_factory=lambda: engine)
        self.window.translation_worker.start()
        self.wait_until(lambda: self.window.translation_worker._engine is engine)
        self.window.search.setText("new query")
        translator.cancel.assert_called_once()

    def test_installed_languages_are_available_as_source_and_english_target(self):
        self.wait_until(lambda: self.window.source.findData("de") >= 0)
        self.assertGreaterEqual(self.window.foreign.findData("de"), 0)
        self.window.set_mode("de")
        self.assertEqual(self.window.preferred_foreign, "de")

    def test_dictionary_only_profiles_do_not_enable_managed_translation(self):
        self.window.update_languages(("de", "yi"))
        self.assertGreaterEqual(self.window.source.findData("yi"), 0)
        self.assertEqual(self.window.foreign.findData("yi"), -1)
        self.window.set_mode("yi")
        self.window.search.setText("ייִדיש")
        self.assertFalse(self.window.translate.isEnabled())
        self.assertIn("does not support", self.window.translate.toolTip())
        self.window.update_languages()
        self.assertGreaterEqual(self.window.source.findData("yi"), 0)

    def test_saved_unsupported_translation_partner_is_preserved(self):
        self.settings.setValue("profiles/ja/target", "yi")
        self.window.update_translation_languages("yi")
        self.assertEqual(self.window.foreign.currentData(), "yi")
        item = self.window.foreign.model().item(self.window.foreign.findData("yi"))
        self.assertFalse(item.isEnabled())
        self.assertEqual(self.settings.value("profiles/ja/target"), "yi")

    def test_custom_translation_targets_follow_configured_and_imported_profiles(self):
        from meikipop.dictionary.translation import TranslationSettings, save_profile_settings
        save_profile_settings(self.settings, "ja", TranslationSettings(provider="custom"))
        self.window.update_languages(("yi", "de"))
        self.assertGreaterEqual(self.window.foreign.findData("yi"), 0)
        self.assertEqual(self.window.foreign.findData("ru"), -1)
        self.assertIn("depends on", self.window.foreign.toolTip())

    def test_pin_preserves_ocr_result_and_enables_resizing(self):
        self.window.show_entries((entry("猫"),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        self.window.pin.setChecked(True)
        self.assertTrue(self.window.isSizeGripEnabled())
        self.assertFalse(self.window.show_entries((entry("犬"),), "犬", peek=True))
        self.assertEqual(self.window._result.text, "猫")
        self.assertEqual(self.window._context, "猫がいる。")

    def test_short_preview_fits_content_and_pin_restores_reading_size(self):
        self.window.resize(500, 420)
        self.settings.setValue("preview_max_height", 300)
        self.window.show_entries((entry(definitions=("cat",)),), "猫", peek=True)
        self.app.processEvents()
        self.assertLess(self.window.height(), 300)
        self.assertEqual(self.window.width(), 500)
        self.assertEqual(self.window.browser.verticalScrollBar().maximum(), 0)
        self.window.pin.setChecked(True)
        self.app.processEvents()
        self.assertEqual(self.window.height(), 420)
        self.assertTrue(self.window.browser.hasFocus())
        self.window.pin.setChecked(False)
        self.app.processEvents()
        self.window.open_search()
        self.assertEqual(self.window.height(), 340)

    def test_default_reading_window_fits_short_content_and_keeps_manual_size(self):
        self.window._manual_at_cursor = True
        self.window.show_entries((entry(definitions=("cat",)),), "猫")
        self.app.processEvents()
        self.assertLess(self.window.height(), 340)
        self.assertEqual(self.window.browser.verticalScrollBar().maximum(), 0)
        self.window._reading_size_custom = True
        self.window.resize(480, 420)
        self.window._display(SearchResult("dog", "ja", "en", (entry("犬", definitions=("dog",)),)))
        self.app.processEvents()
        self.assertEqual(self.window.height(), 420)

    def test_short_auto_fitted_result_does_not_shrink_later_pinned_content(self):
        self.window.show_entries((entry(),), "cat", peek=True)
        self.app.processEvents()
        self.window.pin.setChecked(True)
        self.app.processEvents()
        self.assertLess(self.window.height(), self.window._normal_size.height())
        self.window.hide()
        self.assertEqual(self.window._normal_size, QSize(480, 340))
        word = entry("long", language="en", definitions=("A longer definition line.\n" * 30,))
        self.window.show_entries((word,), "long", source="en", peek=True)
        self.app.processEvents()
        preview_height = self.window.browser.viewport().height()
        self.assertGreater(preview_height, 190)
        self.window.pin.setChecked(True)
        self.app.processEvents()
        self.assertGreaterEqual(self.window.browser.viewport().height(), preview_height)
        self.window.hide()
        self.assertEqual(self.window._normal_size, QSize(480, 340))

    def test_bounded_preview_does_not_expose_a_partial_bottom_line(self):
        self.settings.setValue("preview_max_height", 190)
        self.window.show_entries((entry(definitions=("feline animal " * 90,)),), "猫", peek=True)
        self.app.processEvents()
        self.window._fit_preview()
        document = self.window.browser.document()
        height = self.window.browser.viewport().height()
        block = document.begin()
        while block.isValid():
            top = document.documentLayout().blockBoundingRect(block).top()
            for index in range(block.layout().lineCount()):
                line = block.layout().lineAt(index)
                y = top + line.y()
                self.assertFalse(y < height < y + line.height(), (y, height, y + line.height()))
            block = block.next()

    def test_compact_preview_keeps_complete_senses_with_a_bounded_height(self):
        self.window.set_mode("tr")
        self.settings.setValue("profiles/tr/preview_definitions", 3)
        self.settings.setValue("profiles/tr/expanded_dictionaries", ['Turkish Monolingual'])
        long_sense = "A complete definition with several clauses. " * 12
        for list_tag in ("ol", "div"):
            with self.subTest(list_tag=list_tag):
                child_tag = "li" if list_tag == "ol" else "div"
                definition = {"type": "structured-content", "content": {
                    "tag": list_tag, "content": [
                        {"tag": child_tag, "content": [f"{i}. {meaning}"]}
                        for i, meaning in enumerate((long_sense, "Second meaning", "Third meaning", "Fourth meaning"), 1)]}}
                self.settings.setValue("preview_max_height", 300)
                self.window.show_entries((entry("meslek", source="Turkish Monolingual",
                                               definitions=(definition,), language="tr"),),
                                         "meslek", source="tr", peek=True)
                self.app.processEvents()
                text = self.window.browser.toPlainText()
                for meaning in (long_sense.strip(), "Second meaning", "Third meaning"):
                    self.assertIn(meaning, text)
                self.assertNotIn("Fourth meaning", text)
                self.assertNotIn("…", text)
                self.assertLessEqual(self.window.height(), 300)
                self.window.pin.setChecked(True)
                self.assertIn("Fourth meaning", self.window.browser.toPlainText())
                self.window.pin.setChecked(False)

    def test_pinned_translate_uses_original_sentence_and_retains_copy_and_history(self):
        self.settings.setValue("profiles/tr/pinned_sentence", True)
        self.window.set_mode("tr")
        self.window.show_entries((entry(),), "猫", source="ja", peek=True)
        sentence = "公園で猫が寝ている。"
        self.window.set_context(sentence)
        self.assertFalse(self.window.translate_sentence.isVisible())
        self.window.pin.setChecked(True)
        self.assertTrue(self.window.browser.toPlainText().startswith(sentence))
        self.assertTrue(self.window.translate_sentence.isVisible())
        self.window.translate_sentence.click()
        self.wait_until(lambda: self.window._result.translation)
        self.assertEqual(self.engine.calls[-1][:4], (sentence, "ja", "tr", True))
        self.assertEqual(self.window._context, sentence)
        self.assertEqual(self.window.browser.toPlainText().count(sentence), 1)
        self.assertIn(sentence, self.window.copy_button.toolTip())
        self.window.go_back()
        self.assertEqual(self.window._result.text, "猫")
        self.assertEqual(self.window._context, sentence)
        self.assertTrue(self.window.browser.toPlainText().startswith(sentence))
        self.window.search.setText("manual")
        self.assertTrue(self.window.translate.isEnabled())
        self.assertEqual(self.window._context, "")

    def test_translation_screen_languages_and_back_preserve_dictionary_document(self):
        sentence = ("The full original sentence. " * 12).strip()
        self.window.show_entries((entry(definitions=("dictionary definition " * 100,)),), "cat", peek=True)
        self.window.set_context(sentence)
        self.window.pin.setChecked(True)
        self.app.processEvents()
        browser = self.window.browser
        cursor = browser.document().find("dictionary definition")
        browser.setTextCursor(cursor)
        selection = browser.selected_text()
        scroll = browser.verticalScrollBar().value()
        geometry = self.window.geometry()
        self.window.translation_worker = Mock()
        with patch.object(browser, "setHtml", wraps=browser.setHtml) as render:
            self.window.translate.click()
            self.assertTrue(self.window._translation_view)
            self.assertIs(self.window.content_stack.currentWidget(), self.window.translation_panel)
            self.assertEqual(sentence, self.window.translation_panel.source.toPlainText())
            self.assertNotIn("dictionary definition", self.window.translation_browser.toPlainText())
            revision = self.window.revision
            self.window.deliver(revision, SearchResult(sentence, "ja", "en", translation="Full translated sentence."))
            self.assertEqual("English", self.window.translation_panel.target_label.text())
            self.assertIn("Full translated sentence.", self.window.translation_browser.toPlainText())
            self.assertEqual("日本語", self.window.translation_panel.source_label.text())
            self.assertTrue(self.window.translation_panel.copy_output.isEnabled())
            self.window._set_translation_language("target", "tr")
            self.assertEqual(self.window.translation_worker.request.call_args.kwargs["target"], "tr")
            self.assertEqual(self.window.translation_worker.request.call_args.args[1], sentence)
            self.window._set_translation_language("source", "de")
            self.assertEqual(self.window.translation_worker.request.call_args.args[2], "de")
            stale = self.window.revision
            self.window.go_back()
            render.assert_not_called()
            self.assertFalse(self.window._translation_view)
            self.assertIs(self.window.content_stack.currentWidget(), browser)
            self.assertEqual(browser.selected_text(), selection)
            self.assertEqual(browser.verticalScrollBar().value(), scroll)
            self.assertEqual(self.window.geometry(), geometry)
            self.window.deliver(stale, SearchResult(sentence, "de", "tr", translation="stale"))
            self.assertEqual(self.window._result.text, "cat")

    def test_pinned_sentence_shares_its_line_with_actions(self):
        self.settings.setValue("profiles/ja/pinned_sentence", True)
        self.window.show_entries((entry(),), "cat", peek=True)
        self.window.set_context("This is the original sentence.")
        self.window.pin.setChecked(True)
        self.app.processEvents()
        block = self.window._action_heading
        self.assertIn("original sentence", block.text().replace("\u2028", " "))
        browser = self.window.browser
        rect = browser.document().documentLayout().blockBoundingRect(block)
        controls = self.window.audio_actions.geometry()
        self.assertLessEqual(rect.right(), controls.left())
        self.assertLess(controls.top(), browser.document().documentLayout().blockBoundingRect(block.next()).top())
        self.assertFalse(self.window.header.isVisible())

        self.window.translation_worker = Mock()
        self.window._link(QUrl("sentence:translate"))
        self.assertEqual(self.window.translation_worker.request.call_args.args[1], "This is the original sentence.")
        self.assertTrue(self.window._translation_view)

    def test_preview_word_click_only_pins_even_when_sentence_moves_under_pointer(self):
        self.settings.setValue("profiles/ja/pinned_sentence", True)
        self.window.show_entries((entry(),), "cat", peek=True)
        self.window.set_context("The original sentence.")
        self.app.processEvents()
        browser = self.window.browser
        point = browser.cursorRect(QTextCursor(browser.document())).center()
        self.assertFalse(browser.anchorAt(point))
        self.window.translation_worker = Mock()
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()
        self.assertTrue(self.window.is_pinned)
        self.assertFalse(self.window._translation_view)
        self.window.translation_worker.request.assert_not_called()
        cursor = browser.document().find("original")
        cursor.setPosition(cursor.selectionStart() + 1)
        point = browser.cursorRect(cursor).center()
        self.assertEqual(browser.anchorAt(point), "sentence:translate")
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()
        self.assertTrue(self.window._translation_view)
        self.window.translation_worker.request.assert_called_once()

    def test_preview_cannot_follow_sentence_link_and_reading_stack_has_no_frame(self):
        self.window.show_entries((entry(),), "cat", peek=True)
        self.window.set_context("The original sentence.")
        self.window.translation_worker = Mock()
        self.window._link(QUrl("sentence:translate"))
        self.assertFalse(self.window._translation_view)
        self.window.translation_worker.request.assert_not_called()
        self.window.pin.setChecked(True)
        self.app.processEvents()
        self.assertEqual(self.window.content_stack.frameWidth(), 0)
        self.window._link(QUrl("sentence:translate"))
        self.app.processEvents()
        self.assertEqual(self.window.content_stack.frameWidth(), 0)

    def test_jitendex_preview_reduces_nesting_and_separates_tags(self):
        self.settings.setValue("profiles/ja/preview_grammar", False)
        self.settings.setValue("profiles/ja/expanded_dictionaries", ['Dictionary'])
        definitions = ({"type": "structured-content", "content": [
            {"tag": "ul", "data": {"content": "sense-groups"}, "content": {
                "tag": "li", "data": {"content": "sense-group"}, "content": [
                    {"tag": "span", "data": {"class": "tag"}, "content": "noun"},
                    {"tag": "span", "data": {"class": "tag"}, "content": "archaic"},
                    {"tag": "ol", "content": [{"tag": "li", "content": {
                        "tag": "ul", "data": {"content": "glossary"}, "content": [
                            {"tag": "li", "content": "first gloss"},
                            {"tag": "li", "content": "second gloss"}]}}]}]}},
            {"tag": "div", "data": {"content": "forms"}, "content": "alternate form"},
            {"tag": "div", "data": {"content": "attribution"}, "content": "JMdict footer"},
        ]},)
        self.window.show_entries((entry(definitions=definitions),), "猫", peek=True)
        self.app.processEvents()
        text = self.window.browser.toPlainText()
        self.assertNotIn("[noun · archaic]", text)
        self.assertIn("first gloss; second gloss", text)
        self.assertNotIn("alternate form", text)
        cursor = self.window.browser.document().find("first gloss")
        cursor.setPosition(cursor.selectionStart())
        self.assertLess(self.window.browser.cursorRect(cursor).x(), 80)
        self.window.pin.setChecked(True)
        self.assertIn("[noun · archaic]", self.window.browser.toPlainText())
        self.assertIn("alternate form", self.window.browser.toPlainText())
        self.assertNotIn("JMdict footer", self.window.browser.toPlainText())

    def test_copy_is_explicit_and_manual_search_clears_live_context(self):
        with patch.object(QApplication, "clipboard") as clipboard:
            self.window.show_entries((entry(),), "猫", peek=True)
            self.window.set_context("猫がいる。", 0, 1)
            clipboard.assert_not_called()
            self.window.copy_sentence()
            clipboard.return_value.setText.assert_called_once_with("猫がいる。")
            self.window.search.setText("犬")
            self.assertFalse(self.window.copy_button.isEnabled())
            self.window.copy_sentence()
            clipboard.return_value.setText.assert_called_once()

    def test_back_restores_sentence_after_nested_lookup(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        self.window.lookup_word("犬")
        self.wait_until(lambda: self.window._result.text == "犬")
        self.window.go_back()
        self.assertEqual(self.window.search.text(), "猫")
        self.assertEqual(self.window._context, "猫がいる。")
        self.assertTrue(self.window.copy_button.isEnabled())

    def test_translation_keeps_sentence_for_later_history(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        self.window.deliver(self.window.revision, SearchResult("猫", "ja", "en", (entry(),), translation="cat"))
        self.window.lookup_word("犬")
        self.wait_until(lambda: self.window._result.text == "犬")
        self.window.go_back()
        self.assertEqual(self.window._context, "猫がいる。")

    def test_switching_to_english_selects_its_own_profile(self):
        self.window.set_mode("tr")
        self.window.set_mode("en")
        self.assertEqual(self.window.preferred_foreign, "en")
        self.assertEqual(self.settings.value("profile"), "en")

    def test_selected_sentence_waits_for_explicit_translation(self):
        self.window.lookup_selected("Yesterday I skipped breakfast.")
        self.wait_until(lambda: self.window._result is not None)
        self.assertEqual([call[3] for call in self.engine.calls], [False])
        self.assertIsNone(self.window.translation_worker)
        self.window.submit(translate=True)
        self.wait_until(lambda: bool(self.window._result.translation))
        self.assertEqual([call[3] for call in self.engine.calls], [False, True])

    def test_short_typed_sentence_never_translates_while_typing(self):
        self.settings.setValue("profiles/ja/auto_translate_miss", True)
        self.window.open_search()
        for text in ("Cats", "Cats sleep.", "Cats sleep. Sometimes for hours."):
            self.window.search.setText(text)
            self.wait_until(lambda: self.window._result is not None and self.window._result.text == text)
            self.assertFalse(self.window._result.translation)
            self.assertFalse(self.window._translation_view)
            self.assertTrue(self.window.search.isEnabled())
        self.assertTrue(all(not call[3] for call in self.engine.calls))
        self.assertIsNone(self.window.translation_worker)

    def test_typed_phrases_use_installed_entries_before_translation(self):
        from meikipop.dictionary.library import import_yomitan
        from meikipop.dictionary.search import SearchEngine
        phrases = (("tr", "her ne kadar"), ("de", "nach wie vor"), ("en", "as soon as"),
                   ("en", "e.g."), ("ja", "おはよう。"))
        for index, (language, phrase) in enumerate(phrases):
            archive = Path(self.temp.name) / f"phrase-{index}.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("index.json", json.dumps(dict(title=f"Phrase {index}", format=3, sourceLanguage=language)))
                zf.writestr("term_bank_1.json", json.dumps([[phrase, "", "", "", 0, ["fixture meaning"], -1, ""]]))
            import_yomitan(archive, self.temp.name)
        translator = Mock(last_model="fixture")
        translator.translate.return_value = "explicit translation"
        def search(text, **options):
            self.engine.calls.append((text, options))
            engine = SearchEngine(self.temp.name, translator=translator)
            try:
                with patch.object(engine, "_lemma_lookup", side_effect=AssertionError("Unexpected morphology")):
                    return engine.search(text, **options)
            finally:
                engine.close()
        self.engine.search = search
        for language, phrase in phrases:
            with self.subTest(phrase=phrase):
                self.window.set_mode(language)
                self.window.open_search(phrase)
                self.wait_until(lambda: self.window._result is not None and self.window._result.text == phrase)
                self.assertEqual([item.term for item in self.window._result.entries], [phrase])
                self.assertEqual(self.window._result.source, language)
                self.assertTrue(self.engine.calls[-1][1]["exact_only"])
                translator.translate.assert_not_called()
                self.assertIsNone(self.window.translation_worker)
        self.window.submit(translate=True)
        self.wait_until(lambda: self.window._result.translation)
        translator.translate.assert_called_once()

    def test_manual_japanese_search_handles_romaji_and_english_translation(self):
        from meikipop.dictionary.library import import_yomitan
        from meikipop.dictionary.search import SearchEngine
        archive = Path(self.temp.name) / "japanese-input.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("index.json", json.dumps(dict(title="Japanese", format=3, sourceLanguage="ja")))
            zf.writestr("term_bank_1.json", json.dumps([
                ["猫", "ねこ", "", "", 0, ["cat"], -1, ""],
                ["おはようございます", "", "", "", 0, ["good morning"], -1, ""]]))
        import_yomitan(archive, self.temp.name)
        translator = Mock(last_model="fixture")
        translator.translate.return_value = "水をください"
        window = QuickLookupWindow(self.temp.name, lambda: SearchEngine(self.temp.name, translator), self.settings)
        try:
            for text, term in (("neko", "猫"), ("cat", "猫"), ("o hayou gozaimasu", "おはようございます")):
                window.open_search(text)
                self.wait_until(lambda: window._result is not None and window._result.text == text)
                self.assertEqual([e.term for e in window._result.entries], [term])
                self.assertEqual(window.search.text(), text)
            translator.translate.assert_not_called()
            window.open_search("I would like some water")
            self.wait_until(lambda: window._result is not None and window._result.text == "I would like some water")
            translator.translate.assert_not_called()
            window.submit(translate=True)
            self.wait_until(lambda: window._result is not None and bool(window._result.translation))
            translator.translate.assert_called_with("I would like some water", "en", "ja")
            window.open_search("cat")
            self.wait_until(lambda: window._result is not None and window._result.text == "cat")
            window.submit(translate=True)
            self.wait_until(lambda: window._result is not None and bool(window._result.translation))
            translator.translate.assert_called_with("cat", "en", "ja")
        finally:
            window.shutdown()
            window.worker._thread.join(timeout=2)
            if window.translation_worker is not None:
                window.translation_worker._thread.join(timeout=2)
            window.hide()
            window.deleteLater()

    def test_word_miss_keeps_suggestions_until_explicit_translation(self):
        self.settings.setValue("profiles/ja/auto_translate_miss", False)
        original = self.engine.search
        def missing(text, **options):
            result = original(text, **options)
            return result if options.get("translate") else replace(result, entries=(), suggestions=("known",))
        self.engine.search = missing
        self.window.open_search("unknown")
        self.wait_until(lambda: self.window._result is not None)
        self.assertEqual(self.window._result.suggestions, ("known",))
        self.assertIn("known", self.window.browser.toPlainText())
        self.assertIsNone(self.window.translation_worker)
        self.window.submit(translate=True)
        self.wait_until(lambda: bool(self.window._result.translation))
        self.assertEqual([call[3] for call in self.engine.calls], [False, True])
        self.assertNotIn("No entry", self.window.browser.toPlainText())

    def test_incidental_turkish_gloss_matches_require_explicit_translation(self):
        from meikipop.dictionary.library import import_yomitan
        from meikipop.dictionary.search import SearchEngine
        archive = Path(self.temp.name) / "fixture.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("index.json", json.dumps(dict(title="Turkish", format=3, sourceLanguage="tr")))
            zf.writestr("term_bank_1.json", json.dumps([
                ["ev", "", "", "", 0, ["house", "My house is small."], -1, ""]]))
        import_yomitan(archive, self.temp.name)
        translator = Mock(last_model="fixture")
        translator.translate.return_value = "benim evim"
        def search(text, **options):
            self.engine.calls.append((text, options.get("translate")))
            engine = SearchEngine(self.temp.name, translator=translator)
            try:
                return engine.search(text, **options)
            finally:
                engine.close()
        self.engine.search = search
        self.window.set_mode("tr")
        self.window.open_search("my house")
        self.wait_until(lambda: self.window._result is not None)
        translator.translate.assert_not_called()
        self.window.submit(translate=True)
        self.wait_until(lambda: bool(self.window._result.translation))
        self.assertEqual(self.engine.calls, [("my house", False), ("my house", True)])
        translator.translate.assert_called_once_with("my house", "en", "tr")
        self.assertFalse(self.window._result.entries)
        self.assertEqual(self.window._result.translation, "benim evim")

    def test_partial_japanese_match_remains_available_without_translation(self):
        original = self.engine.search
        self.engine.search = lambda text, **options: replace(original(text, **options), matched_length=1)
        self.window.open_search("猫がいる")
        self.wait_until(lambda: self.window._result is not None)
        self.assertEqual([call[3] for call in self.engine.calls], [False])

    def test_dictionary_free_lookup_requires_translation_and_failure_is_retryable(self):
        from meikipop.dictionary.search import SearchEngine
        self.settings.setValue("profiles/ja/auto_translate_miss", False)
        def search(text, **options):
            self.engine.calls.append((text, options.get("translate")))
            translator = Mock()
            translator.translate.side_effect = RuntimeError("Install translation model.")
            engine = SearchEngine(self.temp.name, translator=translator)
            try:
                return engine.search(text, **options)
            finally:
                engine.close()
        self.engine.search = search
        self.window.open_search("hello")
        self.wait_until(lambda: self.window._result is not None)
        self.assertEqual(self.engine.calls, [("hello", False)])
        self.window.submit(translate=True)
        self.wait_until(lambda: self.window._result.message == "Install translation model.")
        self.assertIn("Install translation model.", self.window.translation_browser.toPlainText())
        self.assertEqual(self.engine.calls, [("hello", False), ("hello", True)])
        self.assertTrue(self.window.translate.isEnabled())
        self.window._translate_clicked()
        self.wait_until(lambda: len(self.engine.calls) == 3 and self.window._pending_revision is None)
        self.assertEqual(self.engine.calls[-1], ("hello", True))
        self.assertIn("Install translation model.", self.window.translation_browser.toPlainText())

    def test_translation_worker_failure_keeps_partial_text_and_allows_retry(self):
        self.window.translation_worker = Mock()
        self.window.search.setText("A sentence to translate.")
        self.window.submit(translate=True)
        revision = self.window.revision
        self.window._translation_progress(revision, SearchResult(
            "A sentence to translate.", "en", "ja", translation="Partial translation"))
        self.window._flush_translation()
        self.window._failed(revision, "Connection interrupted.")
        visible = self.window.translation_browser.toPlainText()
        self.assertIn("Partial translation", visible)
        self.assertIn("Connection interrupted.", visible)
        self.assertFalse(self.window._translation_busy)
        self.window._translate_clicked()
        self.assertTrue(self.window._translation_busy)
        self.assertNotIn("Connection interrupted.", self.window.translation_browser.toPlainText())
        self.window.translation_worker.request.assert_called()

    def test_partial_match_in_explicit_word_lookup_does_not_translate_sentence(self):
        original = self.engine.search
        self.engine.search = lambda text, **options: replace(original(text, **options), matched_length=1)
        self.window.search.setText("猫科の動物です。")
        self.window.search.setSelection(0, 2)
        self.window.submit(selection=True)
        self.wait_until(lambda: self.window._result is not None)
        self.assertEqual([call[0] for call in self.engine.calls], ["猫科"])
        self.assertEqual([call[3] for call in self.engine.calls], [False])
        self.assertIsNone(self.window.translation_worker)

    def test_hover_sentence_context_does_not_start_translation(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("公園で猫が寝ている。")
        self.app.processEvents()
        self.assertIsNone(self.window.translation_worker)
        self.assertEqual(self.engine.calls, [])

    def test_profile_appearance_is_independent_and_audio_action_is_connected(self):
        self.settings.setValue("profiles/ja/font_size_definitions", 19)
        self.settings.setValue("profiles/tr/font_size_definitions", 14)
        self.window.set_mode("tr")
        self.assertEqual(self.window.browser.font().pixelSize(), 14)
        self.window.set_mode("ja")
        self.assertEqual(self.window.browser.font().pixelSize(), 19)
        self.assertEqual(self.window.foreign.currentData(), "en")
        self.window.audio = Mock()
        self.window.show_entries((entry(),), "猫")
        self.window.audio_button.click()
        self.window.audio.play.assert_called_once()

    def test_sentence_audio_reads_source_or_translation_in_its_language(self):
        self.window.set_mode("tr")
        self.window.audio = Mock()
        result = SearchResult("Bugün hava çok güzel.", "tr", "en", translation="The weather is lovely today.")
        self.window._display(result)
        self.window.sentence_audio_button.click()
        self.window.audio.play_text.assert_called_with(result.text, "tr", self.window.revision,
                                                       self.settings, profile="tr")
        self.window.play_audio(translation=True)
        self.window.audio.play_text.assert_called_with(result.translation, "en", self.window.revision,
                                                       self.settings, profile="tr")
        plain = self.window.browser.toPlainText()
        self.assertNotIn(result.text, plain)
        self.assertIn(result.translation, plain)
        self.assertIn("</p><hr>", render_result(result))

    def test_translation_partner_without_dictionary_survives_save_switch_and_reload(self):
        self.window.set_mode("tr")
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            dialog.translation_partner.setCurrentIndex(dialog.translation_partner.findData("ru"))
            self.assertTrue(dialog.save_translation())
            self.assertEqual(self.settings.value("profiles/tr/target"), "ru")
            self.assertEqual(self.window.foreign.currentData(), "ru")
            self.window.set_mode("ja")
            self.window.set_mode("tr")
            self.window.update_languages(("ja", "tr"))
            self.assertEqual(self.window.foreign.currentData(), "ru")
            self.window.translation_worker = Mock()
            self.window.search.setText("Bugün hava çok güzel.")
            self.window.submit(translate=True)
            options = self.window.translation_worker.request.call_args.kwargs
            self.assertIsNone(options["target"])
            self.assertEqual(options["pair"], ("tr", "ru"))
            self.window.show_entries((entry("ev", language="tr"),), "ev", "tr", peek=True)
            self.assertEqual(self.window._result.target, "ru")
        finally:
            self.window.translation_worker = None
            dialog.deleteLater()

    def test_added_profiles_survive_refresh_without_dictionaries(self):
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            dialog.add_profile("de")
            self.assertEqual(self.window.preferred_foreign, "de")
            self.window.update_languages(("ja", "tr"))
            self.assertGreaterEqual(self.window.source.findData("de"), 0)
            self.assertEqual(self.settings.value("profiles/de/scan_bindings"), "shift,middle")
            dialog.add_profile("en")
            self.assertEqual(self.window.preferred_foreign, "en")
            self.assertEqual(self.window.foreign.currentData(), "ja")
            reopened = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
            self.assertGreaterEqual(reopened.profile.findData("de"), 0)
            self.assertEqual(reopened.profile.currentData(), "en")
            reopened.deleteLater()
        finally:
            dialog.deleteLater()

    def test_settings_save_immediately_without_leaking_across_profiles(self):
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            dialog.translation_target.setCurrentIndex(dialog.translation_target.findData("ru"))
            self.assertEqual(self.settings.value("profiles/ja/translation_target"), "ru")
            dialog.audio_volume.setValue(42)
            self.assertEqual(self.settings.value("profiles/ja/audio_volume", type=int), 42)
            dialog.appearance.compact_preview.setChecked(False)
            self.assertFalse(self.settings.value("profiles/ja/compact_preview", True, bool))
            dialog.sync_profile("tr")
            self.assertEqual(dialog.translation_target.currentData(), "auto")
            self.assertEqual(dialog.audio_sources.order(), ["tts", "online"])
            self.assertTrue(dialog.audio_form.isRowVisible(dialog.audio_sources))
            self.assertTrue(dialog.audio_form.isRowVisible(dialog.audio_database_row))
            dialog.pin_gesture.setCurrentIndex(dialog.pin_gesture.findData("middle"))
            self.assertEqual(self.settings.value("profiles/tr/pin_gesture"), "middle")
            dialog.audio_sources.items.setCurrentRow(1)
            dialog.audio_sources.move(-1)
            self.assertEqual(self.settings.value("profiles/tr/audio_priority"), ["online", "tts"])
            dialog.sync_profile("ja")
            self.assertEqual(dialog.audio_volume.value(), 42)
            self.assertEqual(dialog.audio_sources.order(), ["tts", "online"])
            self.assertTrue(dialog.audio_form.isRowVisible(dialog.audio_database_row))
            self.assertEqual(dialog.translation_target.currentData(), "ru")
            self.assertFalse(dialog.appearance.compact_preview.isChecked())
            dialog.sync_profile("tr")
            self.assertEqual(dialog.audio_sources.order(), ["online", "tts"])
        finally:
            dialog.deleteLater()

    def test_translation_direction_is_manual_or_automatic_without_changing_profile(self):
        self.window.translation_worker = Mock()
        dialog = SetupDialog(self.temp.name, self.settings, Mock(), self.window)
        try:
            self.assertIsNone(self.window.translate.menu())
            self.assertEqual(dialog.translation_source.currentData(), "auto")
            self.assertEqual(dialog.translation_target.currentData(), "auto")
            dialog.translation_source.setCurrentIndex(dialog.translation_source.findData("en"))
            dialog.translation_target.setCurrentIndex(dialog.translation_target.findData("ru"))
            self.assertTrue(dialog.save_translation())
            self.window.search.setText("The weather is lovely today.")
            self.window.submit(translate=True)
            request = self.window.translation_worker.request.call_args
            self.assertEqual(request.args[2], "en")
            self.assertEqual(request.kwargs["target"], "ru")
            self.assertEqual(self.window.preferred_foreign, "ja")
            dialog.sync_profile("tr")
            self.assertEqual(dialog.translation_source.currentData(), "auto")
            dialog.sync_profile("ja")
            self.assertEqual(dialog.translation_source.currentData(), "en")
            self.assertEqual(dialog.translation_target.currentData(), "ru")
        finally:
            self.window.translation_worker = None
            dialog.deleteLater()

    def test_automatic_sentence_translation_does_not_reuse_a_matching_target(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        self.settings.setValue("profiles/ja/translation_target", "ja")
        with patch.object(self.window, "translation_worker", Mock()):
            self.window.submit(translate=True, context=True)
            request = self.window.translation_worker.request.call_args
            self.assertEqual(request.args[2], "ja")
            self.assertIsNone(request.kwargs["target"])
            self.assertEqual((self.window._translation_content.source, self.window._translation_content.target), ("ja", "en"))
        self.assertEqual(self.settings.value("profiles/ja/translation_target"), "ja")

    def test_typed_results_are_silent_for_all_autoplay_modes(self):
        self.window.audio = Mock()
        for mode in ("lookup", "pin", "off"):
            self.settings.setValue("profiles/ja/audio_autoplay_mode", mode)
            self.window.open_search()
            self.window._display(SearchResult("猫", "ja", "en", (entry(),)))
            self.window._display(SearchResult("猫がいる。", "ja", "en", translation="There is a cat."))
        self.window.audio.play.assert_not_called()
        self.window.audio.play_text.assert_not_called()

    def test_translation_and_back_do_not_replay_word_audio(self):
        self.window.audio = Mock()
        for mode in ("lookup", "pin", "off"):
            with self.subTest(mode=mode):
                self.settings.setValue("profiles/ja/audio_autoplay_mode", mode)
                self.window.pin.setChecked(False)
                self.window.show_entries((entry(),), "猫", peek=True)
                self.window.pin.setChecked(True)
                self.window.set_context("猫がいる。")
                self.window.audio.reset_mock()
                with patch.object(self.window, "translation_worker", Mock()):
                    self.window.translate.setEnabled(True)
                    QTest.mouseClick(self.window.translate, Qt.MouseButton.LeftButton)
                    self.window.deliver(self.window.revision, SearchResult(
                        "猫がいる。", "ja", "en", translation="There is a cat."))
                    self.window.go_back()
                self.window._display(SearchResult("犬", "ja", "en", (entry("犬"),)))
                self.window.go_back()
                self.window.audio.play.assert_not_called()
                self.window.audio.play_text.assert_not_called()

    def test_audio_buttons_play_only_the_requested_audio_with_autoplay_off(self):
        self.window.audio = Mock()
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        self.window.pin.setChecked(True)
        self.app.processEvents()
        self.window.audio.play.assert_not_called()
        self.window.audio.play_text.assert_not_called()
        QTest.mouseClick(self.window.audio_button, Qt.MouseButton.LeftButton)
        self.window.audio.play.assert_called_once()
        self.window.audio.play_text.assert_not_called()
        QTest.mouseClick(self.window.sentence_audio_button, Qt.MouseButton.LeftButton)
        self.window.audio.play.assert_called_once()
        self.window.audio.play_text.assert_called_once()
        QTest.mouseClick(self.window.copy_button, Qt.MouseButton.LeftButton)
        self.window.audio.play.assert_called_once()
        self.window.audio.play_text.assert_called_once()

    def test_ocr_translation_keeps_source_when_input_is_hidden(self):
        self.settings.setValue("profiles/ja/pinned_sentence", True)
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.pin.setChecked(True)
        self.window._display(SearchResult("猫がいる。", "ja", "en", translation="There is a cat."))
        self.assertIn("猫がいる。", self.window.browser.toPlainText())

    def test_pinned_sentence_is_optional_per_profile_and_reuses_unchanged_document(self):
        self.settings.setValue("profiles/ja/pinned_sentence", True)
        self.settings.setValue("profiles/tr/pinned_sentence", True)
        sentence = "公園で猫が寝ている。 <&>"
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context(sentence)
        self.assertNotIn(sentence, self.window.browser.toPlainText())
        self.window.pin.setChecked(True)
        self.assertTrue(self.window.browser.toPlainText().startswith(sentence))
        self.assertIn("cat", self.window.browser.toPlainText())
        with patch.object(self.window.browser, "setHtml", wraps=self.window.browser.setHtml) as render:
            for _ in range(5):
                self.window.set_context(sentence)
                self.window._render()
            render.assert_not_called()
            self.window.set_context("別の文。")
            render.assert_called_once()
        self.window.open_settings()
        appearance = self.window._setup.appearance
        self.assertTrue(appearance.pinned_sentence.isChecked())
        appearance.pinned_sentence.click()
        self.assertNotIn("別の文。", self.window.browser.toPlainText())
        self.assertEqual(self.window._context, "別の文。")
        self.assertFalse(self.settings.value("profiles/ja/pinned_sentence", True, bool))
        self.window.set_mode("tr")
        self.assertTrue(appearance.pinned_sentence.isChecked())
        self.window.set_mode("ja")
        self.assertFalse(appearance.pinned_sentence.isChecked())

    def test_long_pinned_sentence_keeps_definitions_visible_and_full_context(self):
        self.settings.setValue("profiles/ja/pinned_sentence", True)
        sentence = "猫 <&> 😀 " + "長い文の中に猫がいる。\n" * 80
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context(sentence)
        self.window.pin.setChecked(True)
        browser = self.window.browser
        lengths = []
        for scale, width in ((100, 480), (200, 340), (200, 650)):
            with self.subTest(scale=scale, width=width):
                self.settings.setValue("profiles/ja/scale", scale)
                self.window.reload_appearance()
                self.window.resize(width, 420)
                self.app.processEvents()
                self.wait_until(lambda: not self.window.render_timer.isActive())
                block = browser.document().begin()
                self.assertLessEqual(block.layout().lineCount(), 2)
                self.assertIn("…", block.text())
                self.assertNotIn(sentence, browser.toPlainText())
                lengths.append(len(block.text()))
                definition = browser.cursorRect(browser.document().find("cat"))
                self.assertGreaterEqual(definition.top(), 0)
                self.assertLess(definition.bottom(), browser.viewport().height())
        self.assertGreater(lengths[-1], lengths[-2])
        self.assertEqual(self.window._result_context, sentence.strip())
        self.window.audio = Mock()
        self.window.play_audio(sentence=True)
        self.assertEqual(self.window.audio.play_text.call_args.args[0], sentence.strip())
        with patch.object(self.window, "translation_worker") as worker:
            self.window.submit(translate=True, context=True)
            self.assertEqual(worker.request.call_args.args[1], sentence.strip())
        with patch("meikipop.gui.quick_lookup.QApplication.clipboard") as clipboard:
            self.window.copy_sentence()
            clipboard.return_value.setText.assert_called_once_with(sentence.strip())

    def test_pinned_translation_hides_source_when_disabled_and_keeps_copy(self):
        sentence = "猫がいる。"
        self.settings.setValue("profiles/ja/pinned_sentence", False)
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.pin.setChecked(True)
        self.window._display(SearchResult(sentence, "ja", "en", translation="There is a cat."))
        self.window.set_context(sentence)
        self.assertNotIn(sentence, self.window.browser.toPlainText())
        self.assertIn("There is a cat.", self.window.browser.toPlainText())
        with patch("meikipop.gui.quick_lookup.QApplication.clipboard") as clipboard:
            self.window.copy_sentence()
            clipboard.return_value.setText.assert_called_once_with(sentence)

    def test_pinned_audio_control_reads_full_ocr_context(self):
        self.window.audio = Mock()
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("公園で猫が寝ている。")
        self.window.pin.setChecked(True)
        self.assertTrue(self.window.audio_button.isVisible())
        self.assertFalse(self.window.header.isVisible())
        self.assertTrue(self.window.search.isHidden())
        self.assertEqual(self.window.audio_actions.parentWidget(), self.window.browser.viewport())
        self.assertEqual(self.window.actions_row.layout().indexOf(self.window.translate), 2)
        self.assertEqual(self.window.audio_actions.layout().indexOf(self.window.sentence_audio_button), 1)
        self.assertEqual(self.window.audio_actions.layout().indexOf(self.window.audio_button), 2)
        self.assertEqual(self.window.actions_row.layout().indexOf(self.window.audio_button), -1)
        self.assertTrue(self.window.pin.isHidden())
        self.assertEqual(self.window.actions_row.layout().indexOf(self.window.copy_button), 3)
        self.assertEqual(self.window.actions_row.layout().indexOf(self.window.dismiss_button), 4)
        self.window.sentence_audio_button.click()
        self.window.audio.play_text.assert_called_once_with("公園で猫が寝ている。", "ja", self.window.revision,
                                                            self.settings, profile="ja")

    def test_pin_autoplay_keeps_hover_silent_and_plays_when_expanded(self):
        self.settings.setValue("profiles/ja/audio_autoplay_mode", "pin")
        self.window.audio = Mock()
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.audio.play.assert_not_called()
        self.window.pin.setChecked(True)
        self.window.audio.play.assert_called_once()
        self.window.pin.setChecked(False)
        self.window.audio.play.assert_called_once()
        self.window.set_mode("tr")
        self.window.show_entries((entry("araç", language="tr"),), "araç", "tr", peek=True)
        self.window.pin.setChecked(True)
        self.window.audio.play.assert_called_once()

    def test_turkish_grammar_is_compact_and_preserves_qualifiers(self):
        self.settings.setValue(f"profiles/{self.window.preferred_foreign}/preview_grammar", True)
        result = SearchResult("oğlum", "tr", "en", (replace(entry("oğul", language="tr"),
                                                            inflection=("my (possessive)",)),))
        self.window.show_entries(result.entries, result.text, "tr", peek=True)
        self.assertIn("my (possessive)", self.window.browser.toPlainText())
        self.window.show_entries((entry("geldim", language="tr"),
                                  replace(entry("gelmek", language="tr"), inflection=("past", "I"))),
                                 "geldim", "tr", peek=True)
        self.assertNotIn("gelmek · past · I", self.window.browser.toPlainText())
        self.window.pin.setChecked(True)
        self.assertIn("gelmek", self.window.browser.toPlainText())
        self.assertIn("past · I", self.window.browser.toPlainText())

    def test_ekim_preview_does_not_borrow_other_headwords_inflections(self):
        alternatives = " OR ".join(f"first-person singular form {index}" for index in range(30))
        words = (entry("ekim", definitions=("sowing",), language="tr"),
                 replace(entry("ek", definitions=("appendix",), language="tr"), inflection=(alternatives,)))
        self.window.show_entries(words, "ekim", "tr", peek=True)
        self.assertIn("sowing", self.window.browser.toPlainText())
        self.assertNotIn("first-person", self.window.browser.toPlainText())
        self.window.pin.setChecked(True)
        self.assertIn("first-person singular form 0 (+29)", self.window.browser.toPlainText())

    def test_long_turkish_form_variants_keep_gloss_visible_and_full_tooltip(self):
        variants = [f"their (poss.) · locative · relative form · adj. · variant {index}" for index in range(32)]
        full = "(" + " OR ".join(variants) + ")"
        word = replace(entry("avcı", definitions=("hunter",), language="tr"), inflection=(full,))
        self.window.show_entries((word,), "avcılarındakileri", "tr")
        browser = self.window.browser
        text = browser.toPlainText()
        self.assertIn(variants[0] + " (+31)", text)
        self.assertIn("hunter", text)
        self.assertLess(len(text), 200)
        tooltips = []
        block = browser.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                tooltips.append(iterator.fragment().charFormat().toolTip())
                iterator += 1
            block = block.next()
        self.assertIn(full, tooltips)
        browser.selectAll()
        self.assertEqual(browser.createMimeDataFromSelection().text(), text)
        japanese = replace(entry(), inflection=tuple(f"negative past variant {index}" for index in range(12)))
        self.window.show_entries((japanese,), "猫")
        self.assertIn(" · ".join(japanese.inflection), browser.toPlainText())

    def test_semantic_tooltips_show_escaped_descriptions_without_link_paths(self):
        from PyQt6.QtGui import QHelpEvent
        browser = self.window.browser
        browser.setHtml('<a href="meikipop-tag:Full%20%3Cdescription%3E">summary</a> '
                        '<a href="file:///private/path" title="private/path">other</a>')
        self.window.show()
        self.app.processEvents()
        def event_for(text):
            cursor = browser.document().find(text)
            cursor.setPosition(cursor.selectionStart())
            point = browser.cursorRect(cursor).center() + QPoint(2, 0)
            return QHelpEvent(QEvent.Type.ToolTip, point, browser.viewport().mapToGlobal(point))
        with patch("meikipop.gui.quick_lookup.QToolTip.showText") as show:
            QApplication.sendEvent(browser.viewport(), event_for("summary"))
            self.assertEqual(show.call_args.args[1], "<p>Full &lt;description&gt;</p>")
            show.reset_mock()
            with patch("meikipop.gui.quick_lookup.QToolTip.hideText") as hide:
                QApplication.sendEvent(browser.viewport(), event_for("other"))
                show.assert_not_called()
                hide.assert_called_once()

    def test_nested_history_trail_restores_context_expansion_and_profile(self):
        self.window.set_mode("tr")
        self.window.show_entries((entry("ev", language="tr"),), "ev", "tr", peek=True)
        self.window.set_context("Ev çok büyük.")
        self.window.pin.setChecked(True)
        self.window._expanded.add("Dictionary")
        self.window.lookup_word("house")
        self.wait_until(lambda: self.window._result.text == "house")
        self.window.lookup_word("home")
        self.wait_until(lambda: self.window._result.text == "home")
        self.assertIn("ev", self.window.title.text())
        self.assertIn("house", self.window.title.text())
        self.assertIn("home", self.window.title.text())
        self.window.go_back()
        self.assertEqual(self.window._result.text, "house")
        self.assertNotIn("home", self.window.title.text())
        self.window.title.linkActivated.emit("0")
        self.assertEqual(self.window._result.text, "ev")
        self.assertEqual(self.window._context, "Ev çok büyük.")
        self.assertEqual(self.window.preferred_foreign, "tr")
        self.assertIn("Dictionary", self.window._expanded)
        self.assertFalse(self.window._history)

    def test_new_search_starts_a_separate_history_chain(self):
        self.window.show_entries((entry(),), "猫")
        self.window.lookup_word("犬")
        self.wait_until(lambda: self.window._result.text == "犬")
        self.assertTrue(self.window._history)
        self.window.open_search("鳥")
        self.wait_until(lambda: self.window._result.text == "鳥")
        self.assertFalse(self.window._history)
        self.assertEqual(self.window.title.text(), "")

    def test_typing_replaces_result_without_adding_partial_words_to_history(self):
        self.window.open_search()
        self.wait_until(lambda: not self.window._opening_search)
        for fragment in ("k", "o", "yun"):
            QTest.keyClicks(self.window.search, fragment)
            text = self.window.search.text()
            self.wait_until(lambda: self.window._result is not None and self.window._result.text == text)
            self.assertFalse(self.window._history)
            self.assertEqual(self.window.title.text(), "")
        self.window.search.returnPressed.emit()
        self.wait_until(lambda: len(self.engine.calls) == 4)
        self.assertFalse(self.window._history)
        self.window.lookup_word("sheep")
        self.wait_until(lambda: self.window._result.text == "sheep")
        self.assertEqual([state[0].text for state in self.window._history], ["koyun"])
        QTest.keyClicks(self.window.search, "s")
        self.wait_until(lambda: self.window._result.text == "sheeps")
        self.assertEqual([state[0].text for state in self.window._history], ["koyun"])
        self.window.go_back()
        self.assertEqual(self.window._result.text, "koyun")
        self.assertFalse(self.window._history)

    def test_reverse_results_never_create_a_combined_frequency_tooltip(self):
        entries = tuple(replace(entry(str(i)), frequencies=(Frequency("Jiten", i, str(i)),)) for i in range(80))
        self.window.show_entries(entries, "spouse", source="en")
        self.assertNotIn("Jiten:", self.window.browser.toolTip())
        self.assertLess(len(self.window.browser.toolTip()), 200)

    def test_search_opens_near_tray_and_selected_text_near_cursor(self):
        self.window.open_search()
        self.assertFalse(self.window._manual_at_cursor)
        self.window.lookup_selected("猫")
        self.assertTrue(self.window._manual_at_cursor)

    def test_corner_size_survives_short_results_reopening_and_ocr(self):
        self.window.open_search()
        size = QSize(560, 420)
        self.window.resize(size)
        self.window._display(SearchResult("猫", "ja", "en", (entry(),)))
        self.window._fit_preview()
        self.assertEqual(self.window.size(), size)
        self.window.hide()
        self.assertEqual(self.settings.value("corner_size", type=QSize), size)
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.open_search()
        self.assertEqual(self.window.size(), size)

    def test_macos_search_anchors_below_menu_bar_and_windows_stays_at_bottom(self):
        area = QRect(1440, 38, 1440, 840)
        screen = Mock()
        screen.availableGeometry.return_value = area
        for platform in ("darwin", "win32"):
            for tray in (QRect(2550, 0, 24, 24), QRect()):
                with self.subTest(platform=platform, tray=tray), \
                        patch("meikipop.gui.quick_lookup.sys.platform", platform), \
                        patch.object(QApplication, "screenAt", return_value=screen):
                    self.window.tray_geometry = lambda: tray
                    self.window._place()
                    expected = area.top() + 8 if platform == "darwin" else area.bottom() + 1 - self.window.height()
                    self.assertEqual(self.window.y(), expected)
                    edge = self.window.geometry().top() if platform == "darwin" else self.window.geometry().bottom()
                    self.window._resize_expanded(QSize(self.window.width(), 240))
                    self.assertEqual(self.window.geometry().top() if platform == "darwin" else self.window.geometry().bottom(), edge)
                    self.assertGreaterEqual(self.window.x(), area.left())
                    self.assertLessEqual(self.window.geometry().right(), area.right())

    def test_macos_pin_survives_focus_loss_while_native_activation_is_pending(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        with patch("meikipop.gui.quick_lookup.sys.platform", "darwin"), \
                patch.object(QApplication, "platformName", return_value="cocoa"), \
                patch("meikipop.utils.window_focus.focus_pinned_popup") as focus, \
                patch("meikipop.gui.quick_lookup.QTimer.singleShot") as timer, \
                patch.object(self.window, "isActiveWindow", return_value=False):
            self.window.pin.setChecked(True)
            self.window._dismiss_if_inactive()
        focus.assert_called_once_with(self.window, self.window.browser)
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.is_pinned)
        callback = next(call.args[1] for call in timer.call_args_list if call.args[0] == 300)
        callback()
        self.assertFalse(self.window._opening_search)
        with patch("meikipop.gui.quick_lookup.sys.platform", "darwin"), \
                patch.object(self.window, "isActiveWindow", return_value=False):
            self.window._dismiss_if_inactive()
        self.assertTrue(self.window.isVisible())

    def test_windows_pinned_ocr_still_dismisses_on_focus_loss(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        with patch("meikipop.gui.quick_lookup.sys.platform", "win32"), \
                patch.object(self.window, "isActiveWindow", return_value=False):
            self.window.pin.setChecked(True)
            self.window._dismiss_if_inactive()
        self.assertFalse(self.window.isVisible())

    def test_fullscreen_ocr_pin_and_clicks_keep_source_active(self):
        import ctypes
        from ctypes import wintypes
        with patch("meikipop.utils.window_focus.foreground_is_fullscreen", return_value=True), \
                patch("meikipop.utils.window_focus.focus_pinned_popup") as focus:
            self.window.show_entries((entry(),), "cat", peek=True)
            message = wintypes.MSG()
            message.message = 0x0021
            address = ctypes.addressof(message)
            self.assertEqual(self.window.nativeEvent(b"windows_generic_MSG", address), (True, 3))
            self.window.pin.setChecked(True)
            focus.assert_not_called()
            self.assertTrue(self.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
            self.assertEqual(self.window.nativeEvent(b"windows_generic_MSG", address), (True, 3))
            with patch.object(self.window, "isActiveWindow", return_value=False), \
                    patch("meikipop.gui.quick_lookup.QCursor.pos", return_value=QPoint(-500, -500)):
                self.window._dismiss_if_inactive()
            self.assertTrue(self.window.isVisible())
            self.assertTrue(self.window.is_pinned)
            self.window.open_search()
            self.assertFalse(self.window._fullscreen_overlay)
            self.assertFalse(self.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))

    def test_fullscreen_keyboard_and_side_buttons_navigate_snap_stops(self):
        self.settings.setValue("profiles/ja/snap_scrolling", True)
        self.window.reload_appearance()
        with patch("meikipop.utils.window_focus.foreground_is_fullscreen", return_value=True):
            self.window.show_entries((entry(definitions=("Meaning\n" * 100,)),), "cat", peek=True)
            self.window.pin.setChecked(True)
        self.app.processEvents()
        browser = self.window.browser
        scroller = browser.section_scroll
        scroller.animation_enabled = False
        bar = browser.verticalScrollBar()
        self.window.navigate_overlay(0x22)
        self.assertEqual(bar.value(), scroller.stops()[1])
        self.window.navigate_overlay(0x24)
        self.assertEqual(bar.value(), 0)
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.ForwardButton)
        self.assertEqual(bar.value(), scroller.stops()[1])
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.BackButton)
        self.assertEqual(bar.value(), 0)
        self.settings.setValue("profiles/ja/side_button_scrolling", False)
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.ForwardButton)
        self.assertEqual(bar.value(), 0)
        self.window.hide()
        self.window.navigate_overlay(0x22)
        self.assertEqual(bar.value(), 0)

    def test_popup_actions_reuse_existing_commands_without_stealing_typing(self):
        self.window.show_entries((entry(),), "cat")
        self.window.activateWindow()
        self.window.browser.setFocus()
        self.app.processEvents()
        with patch.object(self.window, "play_audio") as replay, patch.object(self.window, "add_to_anki") as anki, \
                patch.object(self.window, "copy_sentence") as copy:
            QTest.keyClick(self.window.browser, Qt.Key.Key_R)
            replay.assert_called_once_with()
            self.window.popup_action("anki")
            anki.assert_called_once_with()
            QTest.keyClick(self.window.browser, Qt.Key.Key_C, Qt.KeyboardModifier.ShiftModifier)
            copy.assert_called_once_with()
            self.window.search.setFocus()
            QTest.keyClick(self.window.search, Qt.Key.Key_R)
            self.assertEqual(replay.call_count, 1)
            self.assertIn("r", self.window.search.text())
            self.settings.setValue("profiles/ja/popup/replay_shortcut", "")
            self.window.reload_popup_shortcuts()
            self.assertTrue(self.window._popup_shortcuts["replay"].key().isEmpty())

    def test_escape_hides_and_invalidates_pending_results(self):
        self.window.open_search()
        self.window.search.setText("猫")
        revision = self.window.revision
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.window.keyPressEvent(event)
        self.assertFalse(self.window.isVisible())
        self.assertGreater(self.window.revision, revision)
        self.window.deliver(revision, SearchResult("stale", "ja", "en", (entry("STALE"),)))
        self.assertNotIn("STALE", self.window.browser.toPlainText())

    def test_reading_shows_every_dictionary_and_full_structured_glosses(self):
        definitions = ({"type": "structured-content", "content": {
            "tag": "div", "content": [{"tag": "span", "content": "Turkdict example " + "long " * 150},
                                       {"tag": "p", "data": {"content": "example"}, "content": "Final example"}]}},)
        result = SearchResult("arac", "tr", "en", (
            entry("araç", "Turkdict", definitions, "tr"),
            entry("araç", "Other", ("vehicle",), "tr")))
        self.window.show_entries(result.entries, "arac", "tr")
        self.assertIn("Turkdict", self.window.browser.toPlainText())
        self.assertIn("Other", self.window.browser.toPlainText())
        self.assertIn("long " * 150, self.window.browser.toPlainText())
        self.assertIn("Final example", self.window.browser.toPlainText())
        self.window._link(QUrl("expand:0"))
        self.assertIn("Final example", self.window.browser.toPlainText())
        self.assertIn("Turkdict", self.window._expanded)
        self.window._link(QUrl("collapse:0"))
        self.assertNotIn("Final example", self.window.browser.toPlainText())

    def test_dictionary_markup_and_external_resources_are_not_executed(self):
        result = SearchResult("word", "ja", "en", (entry("<script>", "<source>", ("<img src='file:///secret'>",)),))
        html = render_result(result)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;source&gt;", html)
        self.assertNotIn("<img", html)
        self.assertIsNone(self.window.browser.loadResource(2, QUrl("file:///secret")))
        self.assertFalse(self.window.browser.openExternalLinks())

    def test_shared_headword_metadata_and_dictionary_order(self):
        first = replace(entry(source="Preferred"), frequencies=(Frequency("Corpus", 123, "123"),),
                        inflection=("negative", "past", "(unstressed infinitive)"))
        second = replace(first, source="Secondary", definitions=("feline",))
        html = render_result(SearchResult("猫", "ja", "en", (first, second)))
        self.assertEqual(html.count("<h2>"), 1)
        self.assertLess(html.index("Preferred"), html.index("Secondary"))
        self.assertEqual(html.count("Corpus"), 1)
        self.assertIn("#123", html)
        self.assertIn("negative · past", html)
        self.assertNotIn("unstressed infinitive", html)

    def test_compact_preview_omits_semantic_tags_and_retains_lookup_metadata(self):
        from meikipop.dictionary.pitch import Pitch
        definition = {"type": "structured-content", "content": [
            {"tag": "span", "data": {"class": "tag"}, "content": "interjection"},
            {"tag": "span", "data": {"content": "tag"}, "content": "kana"},
            "interjection meaning written in kana"]}
        word = replace(entry(definitions=(definition,)), inflection=("past",),
                       frequencies=(Frequency("Corpus", 123, "123"),), pitches=(Pitch("Pitch", "ねこ", 1),))
        result = SearchResult("猫", "ja", "en", (word,))
        self.window.browser.setHtml(render_result(result, preview=True))
        preview = self.window.browser.toPlainText()
        self.assertNotIn("[interjection · kana]", preview)
        for retained in ("interjection meaning written in kana", "past", "#123", "ねこ [1]"):
            self.assertIn(retained, preview)
        self.window.browser.setHtml(render_result(result))
        self.assertIn("[interjection · kana]", self.window.browser.toPlainText())

    def test_frequency_defaults_to_one_harmonic_rank_with_optional_details(self):
        word = replace(entry(), frequencies=(Frequency("A", 100, "100"), Frequency("A", 900, "900㋕"),
                                            Frequency("B", 400, "400")))
        self.window.show_entries((word,), "猫")
        text = self.window.browser.toPlainText()
        self.assertIn("#160", text)
        self.assertNotIn("900", text)
        self.assertNotIn("#400", text)
        self.settings.setValue("profiles/ja/combine_frequencies", False)
        self.window._render()
        self.assertIn("#100", self.window.browser.toPlainText())
        self.assertIn("#400", self.window.browser.toPlainText())
        self.assertIn("A #100/900㋕ B #400", self.window.browser.toPlainText().replace("\xa0", " "))

    def test_structured_preview_keeps_lists_and_hides_examples_and_extra_senses(self):
        # Mirrors Turkdict's export_prototype.Structured output (classes become styles).
        definition = {"type": "structured-content", "content": {"tag": "ol", "content": [
            {"tag": "li", "content": ["vehicle", {"tag": "div", "style": {
                "fontSize": "0.9em", "marginTop": "0.1em"}, "content": "Hidden example"}]},
            {"tag": "li", "content": "means"},
            {"tag": "li", "content": "Third sense"}]}}
        result = SearchResult("araç", "tr", "en", (
            entry("araç", "Turkdict", (definition,), "tr"),
            entry("araç", "Other", ("vehicle", "device", "tool", "Fourth sense"), "tr")))
        preview = render_result(result, preview=True, preview_definitions=2)
        self.assertIn("<ol><li>vehicle", preview)
        self.assertNotIn("Hidden example", preview)
        self.assertNotIn("Third sense", preview)
        expanded = render_result(result, {"Turkdict"})
        self.assertIn("Hidden example", expanded)
        self.assertIn("Third sense", expanded)
        self.assertIn("Fourth sense", expanded)
        self.assertNotIn('href="expand:0:1"', expanded)

    def test_dictionary_styles_cannot_inject_markup_when_expanded(self):
        definition = {"type": "structured-content", "content": {"tag": "span", "style": {
            "fontSize": '12px\"><img src="file:///secret"', "fontWeight": "bold"}, "content": "safe"}}
        html = render_result(SearchResult("word", "tr", "en", (
            entry("word", "Dictionary", (definition,), "tr"),)), {"Dictionary"})
        self.assertNotIn("<img", html)
        self.assertNotIn("file:///secret", html)
        self.assertIn("font-weight:bold", html)

    def test_hover_shows_preferred_source_and_click_pins_all_details(self):
        records = (entry(source="Preferred"), entry(source="Secondary", definitions=("feline",)))
        kanji = (KanjiEntry("猫", source="Kanji pack", meanings=("cat",), stats=(("strokes", 11),)),)
        self.window.show_entries(records, "猫", peek=True, kanji=kanji)
        self.window.set_context("猫がいる。")
        self.assertTrue(self.window.search.isHidden())
        self.assertTrue(self.window.mode_row.isHidden())
        self.assertEqual(self.window.browser.toolTip(), "")
        self.assertIn("cat", self.window.browser.toPlainText())
        self.assertNotIn("Secondary", self.window.browser.toPlainText())
        self.assertNotIn("Kanji", self.window.browser.toPlainText())
        QTest.mouseClick(self.window.browser.viewport(), Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.is_pinned)
        self.assertIn("Secondary", self.window.browser.toPlainText())
        self.assertNotIn("Strokes 11", self.window.browser.toPlainText())
        self.assertEqual(self.window._context, "猫がいる。")

    def test_copy_click_closes_after_copy_and_dismiss_does_not_pin(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        QTest.mouseClick(self.window.browser.viewport(), Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.copy_button.isVisible())
        with patch.object(QApplication, "clipboard") as clipboard:
            clipboard.return_value.setText.side_effect = lambda _: self.assertTrue(self.window.is_pinned)
            QTest.mouseClick(self.window.copy_button, Qt.MouseButton.LeftButton)
            clipboard.return_value.setText.assert_called_once_with("猫がいる。")
        self.assertFalse(self.window.is_pinned)
        self.assertFalse(self.window.isVisible())
        self.window.show_entries((entry(),), "猫", peek=True)
        QTest.mouseClick(self.window.dismiss_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.is_pinned)
        self.assertFalse(self.window.isVisible())

    def test_manual_search_restores_controls_and_all_dictionaries(self):
        self.window.show_entries((entry(source="First"), entry(source="Second")), "猫", peek=True)
        self.window.open_search()
        self.assertFalse(self.window.search.isHidden())
        self.assertTrue(self.window.mode_row.isHidden())
        self.assertFalse(self.window._peek)
        self.window._display(SearchResult("猫", "ja", "en", (entry(source="First"), entry(source="Second"))))
        self.assertIn("Second", self.window.browser.toPlainText())

    def test_hover_has_no_chrome_and_pinned_actions_use_accessible_icons(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        self.app.processEvents()
        self.assertFalse(self.window.actions_row.isVisible())
        self.assertFalse(self.window.mode_row.isVisible())
        self.assertFalse(self.window.scan_toggle.isVisible())
        self.assertFalse(self.window.status.isVisible())
        self.assertFalse(self.window.context_label.isVisible())
        self.window.pin.setChecked(True)
        self.assertTrue(self.window.actions_row.isVisible())
        for button in (self.window.pin, self.window.copy_button, self.window.translate_sentence,
                       self.window.dismiss_button, self.window.back, self.window.settings_button):
            self.assertTrue(button.accessibleName())
            self.assertFalse(button.icon().isNull())
            self.assertEqual(button.text(), "")

    def test_popup_keeps_model_in_tooltip_and_preserves_copy_preview(self):
        record = replace(entry(source="Jitendex.org [2026-10-03]"),
                         frequencies=(Frequency("Jiten", 186, "186"),))
        self.window.deliver(self.window.revision, SearchResult("猫", "ja", "en", (record,),
                            translation="A cat.", translation_model="Hy-MT2-7B Q8_0"))
        rendered = self.window.browser.toPlainText()
        self.assertIn("#186", rendered)
        self.assertIn("Jitendex", rendered)
        self.assertNotIn("Jiten #", rendered)
        self.assertNotIn("2026-10-03", rendered)
        self.assertNotIn("Hy-MT2", rendered)
        self.assertNotIn("Jiten", self.window.browser.toolTip())
        self.assertIn("Hy-MT2", self.window.translate.toolTip())
        self.assertNotIn("Hy-MT2", self.window.browser.toHtml())
        self.assertFalse(self.window.eventFilter(self.window.translate, QEvent(QEvent.Type.ToolTip)))
        self.assertFalse(self.window.eventFilter(self.window.copy_button, QEvent(QEvent.Type.ToolTip)))
        self.assertIn("猫", self.window.copy_button.toolTip())

    def test_pinning_keeps_dictionary_disclosures_collapsed_and_independent(self):
        def details(label, body):
            return {"tag": "details", "content": [{"tag": "summary", "content": label}, body]}
        definition = {"type": "structured-content", "content": [
            "profession", details("More", ["Outer text", details("Nested", "Inner text")]),
            details("Other", "Other text")]}
        self.window.show_entries((entry("meslek", "Turkish Bilingual", (definition,), "tr"),),
                                 "meslek", source="tr", peek=True)
        self.assertNotIn("More", self.window.browser.toPlainText())
        self.window.pin.setChecked(True)
        text = self.window.browser.toPlainText()
        self.assertIn("More", text)
        self.assertNotIn("Outer text", text)
        self.assertNotIn("Other text", text)
        self.window._link(QUrl("details:0:0:2"))
        self.assertIn("Other text", self.window.browser.toPlainText())
        self.assertNotIn("Outer text", self.window.browser.toPlainText())
        self.window._link(QUrl("details:0:0:0"))
        self.assertIn("Outer text", self.window.browser.toPlainText())
        self.assertNotIn("Inner text", self.window.browser.toPlainText())
        self.window._link(QUrl("details:0:0:1"))
        self.assertIn("Inner text", self.window.browser.toPlainText())
        self.window._link(QUrl("details:0:0:0"))
        self.assertNotIn("Inner text", self.window.browser.toPlainText())
        self.assertIn("Other text", self.window.browser.toPlainText())
        original = self.window._result
        self.window._display(replace(original, translation="profession"))
        self.assertIn("Other text", self.window.browser.toPlainText())
        self.window._display(SearchResult("ev", "tr", "en", (entry("ev", language="tr"),)))
        self.assertFalse(self.window._details_expanded)
        self.window.go_back()
        self.assertIn("Other text", self.window.browser.toPlainText())
        self.assertNotIn("Outer text", self.window.browser.toPlainText())
        self.window._link(QUrl("details:0:0:0"))
        self.assertIn("Inner text", self.window.browser.toPlainText())

    def test_disclosure_clicks_preserve_viewport_at_top_and_midway(self):
        def details(label, body):
            return {"tag": "details", "content": [{"tag": "summary", "content": label}, body]}

        browser = self.window.browser
        for leading_lines in (0, 12):
            with self.subTest(leading_lines=leading_lines):
                self.window.pin.setChecked(False)
                definition = {"type": "structured-content", "content": [
                    *({"tag": "div", "content": f"Lead {i}"} for i in range(leading_lines)),
                    details("Grammar", ["Plural form", details("Example", "Nested example")]),
                    details("Etymology", "Word origin"),
                    *({"tag": "div", "content": f"Definition {i}"} for i in range(30))]}
                self.window.show_entries((entry("bahasa", definitions=(definition,), language="id"),),
                                         "bahasa", source="id", peek=True)
                self.window.pin.setChecked(True)
                self.app.processEvents()
                bar = browser.verticalScrollBar()
                bar.setValue(0)
                if leading_lines:
                    bar.setValue(browser.cursorRect(browser.document().find("Lead 10")).top())
                    self.assertGreater(bar.value(), 0)
                self.assertGreater(bar.maximum(), bar.value())
                for label in ("Grammar", "Example", "Example", "Grammar", "Etymology", "Etymology"):
                    cursor = browser.document().find(label)
                    cursor.setPosition(cursor.selectionStart() + 1)
                    point = browser.cursorRect(cursor).center()
                    self.assertTrue(browser.viewport().rect().contains(point))
                    self.assertTrue(browser.anchorAt(point).startswith("details:"))
                    scroll, opened = bar.value(), set(self.window._details_expanded)
                    QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
                    self.wait_until(lambda: not self.window.render_timer.isActive())
                    self.assertNotEqual(self.window._details_expanded, opened)
                    self.assertEqual(bar.value(), scroll)
                    cursor = browser.document().find(label)
                    cursor.setPosition(cursor.selectionStart() + 1)
                    self.assertLessEqual(abs(browser.cursorRect(cursor).center().y() - point.y()), 1)

    def test_disclosures_in_short_final_snap_page_keep_their_position(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "details", "content": [{"tag": "summary", "content": label}, "Extra detail"]}
            for label in ("Grammar", "Etymology")]}
        browser = self.window.browser
        self.settings.setValue("profiles/ja/snap_scrolling", True)
        self.window.reload_appearance()
        with patch.object(self.window, "isActiveWindow", return_value=True):
            self.window.show_entries((entry("first", definitions=("Earlier definition\n" * 30,)),
                                      entry("last", definitions=(definition,))), "last", peek=True)
            self.window.pin.setChecked(True)
            self.app.processEvents()
            bar = browser.verticalScrollBar()
            bar.setValue(browser.section_scroll.boundaries()[-1][0])
            for label in ("Grammar", "Grammar", "Etymology", "Etymology"):
                cursor = browser.document().find(label)
                cursor.setPosition(cursor.selectionStart() + 1)
                point = browser.cursorRect(cursor).center()
                self.assertTrue(browser.viewport().rect().contains(point))
                scroll = bar.value()
                QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
                self.wait_until(lambda: not self.window.render_timer.isActive())
                self.app.processEvents()
                self.assertEqual(bar.value(), scroll)
                cursor = browser.document().find(label)
                cursor.setPosition(cursor.selectionStart() + 1)
                self.assertLessEqual(abs(browser.cursorRect(cursor).center().y() - point.y()), 1)

    def test_japanese_disclosures_keep_shared_ruby_and_escape_summary(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "ruby", "content": ["猫", {"tag": "rt", "content": "ねこ"}]},
            {"tag": "details", "content": [{"tag": "summary", "content": "<More &>"}, "Hidden sense"]}]}
        result = SearchResult("猫", "ja", "en", (entry(definitions=(definition,)),))
        closed = render_result(result, expanded=("Dictionary",))
        opened = render_result(result, expanded=("Dictionary",), details_expanded={"0:0:0"})
        self.assertIn("&lt;More &amp;&gt;", closed)
        self.assertIn("ねこ", closed)
        self.assertNotIn("Hidden sense", closed)
        self.assertIn("Hidden sense", opened)

    def test_turkdict_source_is_shown_once_only_after_pinning(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "div", "content": ["Tureng"], "style": {"fontWeight": "bold", "fontSize": "0.75em"}},
            {"tag": "div", "content": ["vehicle; tool"]},
            {"tag": "div", "content": ["Wiktionary"], "style": {"fontWeight": "bold", "fontSize": "0.75em"}},
            {"tag": "div", "content": ["Another source's definition"]}]}
        self.window.show_entries((entry("araç", source="Turkish Bilingual",
                                definitions=(definition,), language="tr"),), "araç", source="tr", peek=True)
        self.assertNotIn("Tureng", self.window.browser.toPlainText())
        self.assertIn("vehicle; tool", self.window.browser.toPlainText())
        self.assertNotIn("Another source's definition", self.window.browser.toPlainText())
        self.window.pin.setChecked(True)
        self.assertEqual(self.window.browser.toPlainText().count("Tureng"), 1)
        self.assertNotIn("Turkish Bilingual", self.window.browser.toPlainText())
        self.assertIn("Wiktionary", self.window.browser.toPlainText())
        self.assertIn("Another source's definition", self.window.browser.toPlainText())

    def test_turkdict_homonyms_share_heading_without_losing_senses_or_variants(self):
        def lexical_group(term, meaning):
            return {"tag": "div", "content": [
                {"tag": "div", "content": [term],
                 "style": {"fontWeight": "bold", "marginTop": "0.3em"}},
                {"tag": "div", "content": [meaning]}]}

        definition = {"type": "structured-content", "content": [
            {"tag": "div", "content": ["Wiktionary"], "style": {"fontWeight": "bold"}},
            lexical_group("koyun", "1. sheep"),
            lexical_group("koyun", "1. embrace"),
            lexical_group("koynu", "possessive form"),
            {"tag": "div", "content": ["koyun means sheep"]},
            {"tag": "div", "content": ["koyun"], "style": {"fontStyle": "italic"}},
        ]}
        result = SearchResult("koyun", "tr", "en", (
            entry("koyun", source="Turkish Bilingual", definitions=(definition,), language="tr"),
            entry("koyun", source="Other dictionary", definitions=("ewe",), language="tr"),
            entry("koymak", source="Turkish Bilingual", definitions=("put",), language="tr")))
        for preview, expanded in ((True, ()), (False, ()), (False, ("Turkish Bilingual",))):
            with self.subTest(preview=preview, expanded=expanded):
                html = render_result(result, preview=preview, expanded=expanded)
                self.window.browser.setHtml(html)
                text = self.window.browser.toPlainText()
                self.assertEqual(html.count(">koyun</h2>"), 1)
                # One shared heading and one legitimate occurrence in the example.
                self.assertEqual(text.splitlines().count("koyun"), 2)
                for meaning in ("sheep", "embrace", "koynu", "possessive form", "koyun means sheep"):
                    self.assertIn(meaning, text)
                if not preview:
                    for label in ("Wiktionary", "Other dictionary", "ewe", "koymak", "put"):
                        self.assertIn(label, text)

    def test_settings_menu_keeps_search_open(self):
        self.window.open_search()
        self.window.settings_menu.popup(self.window.settings_button.mapToGlobal(self.window.settings_button.rect().bottomLeft()))
        self.app.processEvents()
        self.window._dismiss_if_inactive()
        self.assertTrue(self.window.isVisible())
        self.window.settings_menu.hide()

    def test_closing_pinned_result_releases_scan_lock(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.pin.setChecked(True)
        QTest.mouseClick(self.window.dismiss_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.is_pinned)
        self.assertTrue(self.window.show_entries((entry("犬"),), "犬", peek=True))
        self.assertEqual(self.window._result.text, "犬")

    def test_always_expanded_hover_setting_retains_unpinned_state(self):
        self.window.set_compact_preview(False)
        self.window.show_entries((entry(source="First"),
                                  entry(source="Second", definitions=("one", "two", "three", "Fourth sense"))),
                                 "猫", peek=True)
        self.assertFalse(self.window.is_pinned)
        self.assertIn("Second", self.window.browser.toPlainText())
        self.assertIn("Fourth sense", self.window.browser.toPlainText())
        self.window.set_compact_preview(True)
        self.assertNotIn("Second", self.window.browser.toPlainText())
        self.assertEqual(len(self.window._result.entries), 2)

    def test_kanji_and_dictionary_expansion_are_independent(self):
        kanji = (KanjiEntry("猫", source="Kanji pack", meanings=("cat",), stats=(("strokes", 11),)),)
        self.window.show_entries((entry(definitions=("one", "two", "three", "Fourth sense")),),
                                 "猫", kanji=kanji)
        self.assertNotIn("Strokes", self.window.browser.toPlainText())
        self.assertNotIn("Kanji", self.window.browser.toPlainText())
        self.assertNotIn("Details", self.window.browser.toPlainText())
        self.assertNotIn("Show less", self.window.browser.toPlainText())
        self.window._link(QUrl("kanji:toggle"))
        self.assertNotIn("Strokes 11", self.window.browser.toPlainText())
        self.assertIn("Fourth sense", self.window.browser.toPlainText())
        self.window._link(QUrl("expand:0"))
        self.assertIn("Fourth sense", self.window.browser.toPlainText())
        self.assertNotIn("Strokes 11", self.window.browser.toPlainText())
        self.window._link(QUrl("kanji:toggle"))
        self.assertNotIn("Strokes", self.window.browser.toPlainText())
        self.assertIn("Fourth sense", self.window.browser.toPlainText())

    def test_kanji_click_reveals_all_sources_and_back_restores_details(self):
        kanji = (KanjiEntry("猫", source="Kanji A", meanings=("cat",), stats=(("strokes", 11),)),
                 KanjiEntry("猫", source="Kanji B", meanings=("feline",), stats=(("grade", 8),)),
                 KanjiEntry("犬", source="Kanji A", meanings=("dog",), stats=(("strokes", 4),)))
        self.window.show_entries((entry("猫犬"),), "猫犬", kanji=kanji)
        self.assertNotIn("Strokes 11", self.window.browser.toPlainText())
        self.window._link(QUrl("kanji:%E7%8C%AB"))
        text = self.window.kanji_browser.toPlainText()
        self.assertIn("Kanji A", text)
        self.assertIn("Kanji B", text)
        self.assertIn("Strokes 11", text)
        self.assertNotIn("Grade", text)
        self.window.kanji_more.click()
        self.assertIn("Grade", self.window.kanji_browser.toPlainText())
        self.assertNotIn("Strokes 4", text)
        self.window._display(SearchResult("犬", "ja", "en", (entry("犬"),)))
        self.assertTrue(self.window.kanji_panel.isHidden())
        self.window.go_back()
        self.assertIn("Strokes 11", self.window.kanji_browser.toPlainText())
        self.window._link(QUrl("kanji:%E7%8C%AB"))
        self.assertTrue(self.window.kanji_panel.isHidden())

    def test_later_headword_kanji_clicks_work_with_snap_and_sticky_ruby(self):
        self.settings.setValue("profiles/ja/snap_scrolling", True)
        for ruby in (False, True):
            with self.subTest(ruby=ruby):
                self.settings.setValue("profiles/ja/headword_furigana", ruby)
                self.window.reload_appearance()
                entries = (replace(entry("猫", definitions=("Meaning\n" * 30,)), reading="ねこ"),
                           replace(entry("犬", definitions=("Meaning\n" * 30,)), reading="いぬ"))
                self.window.show_entries(entries, "かな", kanji=(KanjiEntry("猫"), KanjiEntry("犬")))
                self.app.processEvents()
                browser = self.window.browser
                scroller = browser.section_scroll
                bar = browser.verticalScrollBar()
                bar.setValue(scroller._top(scroller._headings[1]) + 5)
                header = scroller.header
                self.assertTrue(header.isVisible())
                points = [QPoint(x, y) for y in range(header.viewport().height())
                          for x in range(min(80, header.viewport().width()))
                          if QUrl(header.anchorAt(QPoint(x, y))).path() == "1:犬"]
                self.assertTrue(points)
                point = QPoint((min(p.x() for p in points) + max(p.x() for p in points)) // 2,
                               (min(p.y() for p in points) + max(p.y() for p in points)) // 2)
                QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=point)
                self.app.processEvents()
                self.assertIn("犬", self.window.kanji_browser.toPlainText())
                self.assertTrue(self.window.kanji_panel.isVisible())

    def test_headword_kanji_opens_pane_without_rebuilding_or_widening(self):
        kanji = (KanjiEntry("猫", source="Kanji A", meanings=("cat",), stats=(("strokes", 11),)),)
        self.window.show_entries((entry("猫", definitions=("Meaning " * 200,)),), "猫", kanji=kanji)
        self.window._expanded.add("Dictionary")
        self.window._render()
        self.app.processEvents()
        result, revision = self.window._result, self.window.revision
        geometry = self.window.geometry()
        self.assertIn('href="headkanji:0:%E7%8C%AB"', self.window.browser.toHtml())
        document_revision = self.window.browser.document().revision()
        self.window._link(QUrl("headkanji:0:%E7%8C%AB"))
        self.app.processEvents()
        self.assertIn("Strokes 11", self.window.kanji_browser.toPlainText())
        self.assertNotIn("Strokes 11", self.window.browser.toPlainText())
        self.assertEqual(self.window.browser.document().revision(), document_revision)
        self.assertTrue(self.window.kanji_panel.isVisible())
        self.assertEqual(self.window.browser.verticalScrollBar().value(), 0)
        self.assertEqual(self.window.width(), geometry.width())
        self.assertGreaterEqual(self.window.height(), geometry.height())
        self.assertIs(self.window._result, result)
        self.assertEqual(self.window.revision, revision)
        self.window._link(QUrl("headkanji:0:%E7%8C%AB"))
        self.assertTrue(self.window.kanji_panel.isHidden())

    def test_kanji_links_share_one_visible_pane_and_preserve_dictionary_selection(self):
        kanji = (KanjiEntry("猫", stats=(("strokes", 11),)),
                 KanjiEntry("犬", stats=(("strokes", 4),)))
        self.window.show_entries((entry("猫犬", definitions=("Meaning " * 200,)),), kanji=kanji)
        self.app.processEvents()
        browser = self.window.browser
        cursor = browser.textCursor()
        cursor.setPosition(10)
        cursor.setPosition(20, QTextCursor.MoveMode.KeepAnchor)
        browser.setTextCursor(cursor)
        browser.verticalScrollBar().setValue(browser.verticalScrollBar().maximum() // 2)
        scroll = browser.verticalScrollBar().value()
        selection = browser.textCursor().selectedText()
        geometry = self.window.geometry()
        revision = browser.document().revision()
        for link, strokes in (("headkanji:0:猫", 11), ("headkanji:0:犬", 4), ("kanji:猫", 11)):
            self.window._link(QUrl(link))
            self.app.processEvents()
            self.assertEqual(len(self.window._kanji_details), 1)
            self.assertEqual(self.window.kanji_browser.toPlainText().count("Strokes"), 1)
            self.assertIn(f"Strokes {strokes}", self.window.kanji_browser.toPlainText())
            self.assertTrue(self.window.kanji_panel.isVisible())
            self.assertTrue(self.window.frame.rect().contains(self.window.kanji_panel.geometry()))
            self.assertEqual(browser.verticalScrollBar().value(), scroll)
            self.assertEqual(browser.textCursor().selectedText(), selection)
            self.assertEqual(browser.document().revision(), revision)
            self.assertEqual(self.window.width(), geometry.width())
        self.window.kanji_close.click()
        self.app.processEvents()
        self.assertTrue(self.window.kanji_panel.isHidden())
        self.assertEqual(browser.verticalScrollBar().value(), scroll)
        self.assertEqual(browser.textCursor().selectedText(), selection)

    def test_kanji_more_preserves_summary_selection_and_dictionary_document(self):
        kanji = (KanjiEntry("猫", "One", meanings=("cat",),
                           stats=(("strokes", "11"), ("halpern", "123"))),
                 KanjiEntry("犬", "Two", meanings=("dog",)))
        self.window.show_entries((entry("猫犬"),), kanji=kanji)
        self.window._link(QUrl("kanji:猫"))
        self.app.processEvents()
        browser = self.window.kanji_browser
        browser.setTextCursor(browser.document().find("cat"))
        geometry = self.window.geometry()
        revision = self.window.browser.document().revision()
        for _ in range(2):
            self.window.kanji_more.click()
            self.app.processEvents()
            self.assertIn("halpern", browser.toPlainText())
            self.assertEqual(browser.textCursor().selectedText(), "cat")
            self.window.kanji_more.click()
            self.app.processEvents()
            self.assertNotIn("halpern", browser.toPlainText())
            self.assertEqual(browser.textCursor().selectedText(), "cat")
            self.assertEqual(self.window.geometry(), geometry)
            self.assertEqual(self.window.browser.document().revision(), revision)
        self.window.kanji_more.click()
        self.window._link(QUrl("kanji:犬"))
        self.assertTrue(self.window.kanji_more.isHidden())
        self.assertFalse(self.window.kanji_more.isChecked())
        self.assertNotIn("halpern", browser.toPlainText())

    def test_kanji_pane_fits_short_pinned_results(self):
        self.window.show_entries((entry(),), peek=True,
                                 kanji=(KanjiEntry("猫", stats=(("strokes", 11),)),))
        self.window.pin.setChecked(True)
        self.app.processEvents()
        geometry = self.window.geometry()
        self.window._link(QUrl("headkanji:0:猫"))
        self.app.processEvents()
        self.assertEqual(self.window.geometry(), geometry)
        self.assertTrue(self.window.kanji_panel.isVisible())
        self.window.kanji_close.click()
        self.app.processEvents()
        self.assertEqual(self.window.geometry(), geometry)

    def test_default_kanji_split_fits_glyph_without_fitting_long_meanings(self):
        for height in (340, 500):
            self.window.show_entries((entry(),),
                                     kanji=(KanjiEntry("?", meanings=("long meaning " * 500,)),))
            self.window._reading_size_custom = True
            self.window.resize(480, height)
            self.app.processEvents()
            geometry = self.window.geometry()
            self.window._select_kanji("?")
            self.app.processEvents()
            self.assertEqual(self.window.geometry(), geometry)
            self.assertGreaterEqual(self.window.kanji_browser.viewport().height(),
                                    self.window._kanji_glyph_height())
            self.assertGreater(self.window.kanji_browser.verticalScrollBar().maximum(), 0)
            self.window._close_kanji()
            self.app.processEvents()
            self.assertEqual(self.window.geometry(), geometry)

    def test_kanji_divider_remembers_share_and_keeps_manual_window_size(self):
        self.window.show_entries((entry(),), kanji=(KanjiEntry("猫", meanings=("cat",)),))
        self.app.processEvents()
        self.window._select_kanji("猫")
        self.app.processEvents()
        splitter = self.window.kanji_splitter
        splitter.moveSplitter(round(sum(splitter.sizes()) * .3), 1)
        ratio = self.settings.value("profiles/ja/kanji_height_ratio", type=float)
        self.assertGreater(ratio, .5)
        self.window._close_kanji()
        self.window._select_kanji("猫")
        self.app.processEvents()
        sizes = splitter.sizes()
        self.assertAlmostEqual(sizes[1] / sum(sizes), ratio, delta=.02)
        self.window.resize(self.window.width() + 20, self.window.height())
        geometry = self.window.geometry()
        self.window._close_kanji()
        self.app.processEvents()
        self.assertEqual(self.window.geometry(), geometry)

    def test_headword_audio_buttons_follow_readings_and_scroll_with_headings(self):
        entries = (replace(entry("same", definitions=("first " * 250,)), reading="one"),
                   replace(entry("same"), reading="two"))
        self.window.show_entries(entries, "same")
        self.app.processEvents()
        self.window.audio = Mock()
        self.assertTrue(self.window.audio_button.isHidden())
        self.assertEqual(len(self.window._headword_rows), 2)
        second_row, _, second = self.window._headword_rows[("same", "two")]
        self.assertTrue(second_row.isHidden())
        second.click()
        self.assertEqual(self.window.audio.play.call_args.args[0].reading, "two")
        self.window.browser.verticalScrollBar().setValue(self.window.browser.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertTrue(second_row.isVisible())
        self.window._set_peek(True)
        self.window.pin.setChecked(True)
        self.window.browser.verticalScrollBar().setValue(0)
        self.app.processEvents()
        first_row = self.window._headword_rows[("same", "one")][0]
        self.assertTrue(first_row.isVisible())
        self.assertFalse(first_row.geometry().intersects(self.window.audio_actions.geometry()))
        self.settings.setValue("profiles/ja/buttons/audio", False)
        self.window._place_actions()
        self.assertTrue(second_row.isHidden())

    def test_kanji_long_summary_keeps_window_geometry(self):
        self.window.show_entries((entry(),), peek=True,
                                 kanji=(KanjiEntry("猫", meanings=("Long meaning " * 500,)),))
        self.window.pin.setChecked(True)
        self.app.processEvents()
        geometry = self.window.geometry()
        self.window._select_kanji("猫")
        self.app.processEvents()
        area = self.app.screenAt(self.window.geometry().center()).availableGeometry()
        self.assertTrue(area.contains(self.window.geometry()))
        self.assertEqual(self.window.geometry(), geometry)
        self.assertGreater(self.window.kanji_browser.verticalScrollBar().maximum(), 0)
        self.window._close_kanji()
        self.app.processEvents()
        self.assertEqual(self.window.geometry(), geometry)

    def test_pinning_keeps_content_at_the_top_and_search_restores_its_header(self):
        for _ in range(2):
            self.window.show_entries((entry(),), "cat", peek=True)
            self.app.processEvents()
            top = self.window.browser.geometry().top()
            self.window.pin.setChecked(True)
            self.app.processEvents()
            self.assertFalse(self.window.header.isVisible())
            self.assertEqual(self.window.browser.geometry().top(), top)
            self.assertTrue(self.window.audio_actions.isVisible())
            self.assertEqual(self.window.audio_actions.parentWidget(), self.window.browser.viewport())
            cursor = self.window.browser.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            self.window.browser.setTextCursor(cursor)
            selected = self.window.browser.selected_text()
            geometry = self.window.geometry()
            with patch.object(self.window.browser, "setHtml", wraps=self.window.browser.setHtml) as render:
                self.window._place_actions()
                self.window._place_actions()
                render.assert_not_called()
            self.assertEqual(self.window.browser.selected_text(), selected)
            self.assertEqual(self.window.geometry(), geometry)
            self.window.open_search()
            self.app.processEvents()
            self.assertTrue(self.window.header.isVisible())
            self.assertTrue(self.window.search.isVisible())
            self.assertEqual(self.window.audio_actions.parentWidget(), self.window.header)

    def test_inline_actions_share_heading_geometry_and_visibility_preserves_selection(self):
        self.settings.setValue("profiles/ja/anki/enabled", True)
        self.window.show_entries((entry(definitions=("Long definition. " * 100,)),), "cat", peek=True)
        self.window.pin.setChecked(True)
        for width in (340, 600):
            self.window.resize(width, 340)
            self.app.processEvents()
            browser = self.window.browser
            block = self.window._action_heading
            heading = browser.document().documentLayout().blockBoundingRect(block)
            controls = self.window.audio_actions
            self.assertFalse(self.window.header.isVisible())
            self.assertTrue(controls.isVisible())
            self.assertGreaterEqual(controls.y(), heading.top())
            following = browser.document().documentLayout().blockBoundingRect(block.next())
            self.assertLess(controls.geometry().bottom(), following.top())
            self.assertLessEqual(heading.right(), controls.x())
            for button in (self.window.anki_button, self.window.sentence_audio_button, self.window.audio_button):
                self.assertEqual(button.size(), self.window.copy_button.size())
                self.assertEqual(button.iconSize(), self.window.copy_button.iconSize())
                self.assertEqual(button.styleSheet(), self.window.copy_button.styleSheet())
        cursor = browser.document().find("Long definition.")
        browser.setTextCursor(cursor)
        selected = browser.selected_text()
        geometry = self.window.geometry()
        for name in self.window._popup_actions:
            self.settings.setValue(f"profiles/ja/buttons/{name}", False)
        self.window.reload_appearance()
        self.app.processEvents()
        self.assertEqual(browser.selected_text(), selected)
        self.assertFalse(self.window.audio_actions.isVisible())
        self.assertFalse(self.window.actions_row.isVisible())
        self.assertEqual(self.window._action_clearance(), 0)
        self.assertEqual(self.window.geometry(), geometry)
        self.settings.setValue("profiles/ja/buttons/audio", True)
        self.window.reload_appearance()
        self.app.processEvents()
        self.assertTrue(self.window.audio_button.isVisible())
        self.assertFalse(self.window.sentence_audio_button.isVisible())
        self.assertFalse(self.window.anki_button.isVisible())

    def test_pinned_translation_controls_stay_outside_text_when_resized(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.pin.setChecked(True)
        self.window._display(SearchResult("猫", "ja", "en", translation="Translated sentence. " * 60))
        for width in (340, 600):
            self.window.resize(width, 340)
            self.app.processEvents()
            viewport = self.window.browser.viewport()
            bottom = viewport.mapTo(self.window, viewport.rect().bottomLeft())
            controls = self.window.audio_actions
            top = controls.mapTo(self.window, controls.rect().bottomLeft())
            self.assertLess(top.y(), viewport.mapTo(self.window, QPoint()).y())
            self.assertLess(bottom.y(), self.window.actions_row.mapTo(self.window, QPoint()).y())
            self.assertEqual(controls.width(), controls.sizeHint().width())
            self.assertEqual(self.window.browser.verticalScrollBar().value(), 0)

    def test_translation_stream_preserves_selection_and_view_in_repeated_definitions(self):
        text = "𠮷 repeated selection"
        original = SearchResult("猫", "ja", "en", tuple(entry(source=source, definitions=(text,))
                                for source in ("First", "Second")) + (
                                    entry(source="Third", definitions=("Following text.\n" * 20,)),),
                                translation="Initial translation.")
        self.window._display(original)
        self.window.show()
        self.app.processEvents()
        browser = self.window.browser
        first = browser.document().find(text)
        second = browser.document().find(text, first.selectionEnd())
        cursor = QTextCursor(browser.document())
        cursor.setPosition(second.selectionEnd())
        cursor.setPosition(second.selectionStart(), QTextCursor.MoveMode.KeepAnchor)
        browser.setTextCursor(cursor)
        before = browser.cursorRect().top()
        self.window._translation_busy = True
        self.window._translation_base = original
        self.window._translation_chunk = replace(original, translation="Initial translation.\n" + "More text.\n" * 25)
        self.window._flush_translation()
        self.app.processEvents()
        self.assertEqual(browser.selected_text(), text)
        self.assertLess(browser.textCursor().position(), browser.textCursor().anchor())
        self.assertGreater(browser.textCursor().selectionStart(), browser.document().find("Second").selectionEnd())
        self.assertEqual(browser.cursorRect().top(), before)

    def test_kanji_sections_do_not_insert_horizontal_rules(self):
        result = SearchResult("猫", "ja", "en", (entry(),),
                              kanji=(KanjiEntry("猫", meanings=("cat",)),))
        for details in ((), ("猫",), ("head:0:猫",)):
            self.window._display(result, kanji_details=details)
            block = self.window.browser.document().begin()
            while block.isValid():
                self.assertFalse(block.blockFormat().hasProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth))
                block = block.next()

    def test_search_shortcut_is_opt_in_and_restores_explicit_choice(self):
        self.assertIsNone(self.window._keys)
        with patch("meikipop.gui.text_shortcuts.TextHotKeys") as hotkeys:
            self.window.restore_shortcut()
            hotkeys.assert_not_called()
            self.assertEqual(self.settings.value("hotkey"), "")
            import sys
            chosen = "<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d"
            self.settings.setValue("hotkey", chosen)
            self.window.restore_shortcut()
            self.assertEqual(self.settings.value("hotkey"),
                             chosen)
            hotkeys.return_value.start.assert_called_once()
            self.window.apply_shortcut("")
            hotkeys.return_value.stop.assert_called_once()
            self.assertIsNone(self.window._keys)
            self.window.restore_shortcut()
            self.assertIsNone(self.window._keys)

    def test_lookup_shortcut_opens_empty_input_without_selection(self):
        with patch.object(QApplication, "activeWindow", return_value=None), \
                patch.object(QApplication, "clipboard") as clipboard, \
                patch.object(self.window.selection, "start") as capture:
            clipboard.return_value.text.return_value = "clipboard"
            self.window.request_lookup()
            capture.assert_called_once_with(wait_for_modifiers=True)
            self.assertFalse(self.window.isVisible())
            self.window.selection.completed.emit("selected")
            self.assertEqual(self.window.search.text(), "selected")
            self.window.request_lookup()
            self.window.selection.unavailable.emit(True)
            self.assertEqual(self.window.search.text(), "")
            self.assertTrue(self.window.isVisible())
            self.window.hide()
            self.window.request_lookup()
            self.window.selection.unavailable.emit(False)
            self.assertFalse(self.window.isVisible())
            clipboard.assert_not_called()

    def test_lookup_shortcut_uses_only_selection_within_app(self):
        with patch.object(QApplication, "activeWindow", return_value=self.window), \
                patch.object(QApplication, "focusWidget", return_value=self.window.search), \
                patch.object(QApplication, "clipboard") as clipboard:
            self.window.search.setText("selected phrase")
            self.window.search.selectAll()
            self.window.request_lookup()
            self.assertEqual(self.window.search.text(), "selected phrase")
            self.window.search.deselect()
            self.window.request_lookup()
            self.assertEqual(self.window.search.text(), "")
            self.assertTrue(self.window.isVisible())
            clipboard.assert_not_called()

    def test_shortcut_selected_sentence_waits_for_explicit_translation(self):
        with patch.object(QApplication, "activeWindow", return_value=None), \
                patch.object(self.window.selection, "start"):
            self.window.request_lookup()
            self.window.selection.completed.emit("This is a complete sentence.")
            self.wait_until(lambda: self.window._result is not None)
            self.assertEqual([call[3] for call in self.engine.calls], [False])
            self.assertIsNone(self.window.translation_worker)

    def test_typed_lookup_takes_focus_after_passive_selection(self):
        with patch("meikipop.utils.window_focus.focus_search") as focus:
            self.window.lookup_selected("word", passive=True)
            self.app.processEvents()
            focus.assert_not_called()
            self.window.open_search()
            self.app.processEvents()
            focus.assert_called_once_with(self.window)
            self.assertFalse(self.window._passive_text)

    def test_pitch_display_follows_dictionary_data_despite_old_toggle(self):
        from meikipop.dictionary.pitch import Pitch
        self.settings.setValue("profiles/ja/show_pitch", False)
        pitched = replace(entry(), pitches=(Pitch("Accent dictionary", "ねこ", 1),))
        self.window._display(SearchResult("猫", "ja", "en", (pitched,)))
        self.assertIn("ねこ [1]", self.window.browser.toPlainText())
        self.window._display(SearchResult("猫", "ja", "en", (entry(),)))
        self.assertNotIn("ねこ [1]", self.window.browser.toPlainText())

    def test_recording_active_shortcut_does_not_open_search(self):
        import sys
        self.settings.setValue('hotkey', '<cmd>+<shift>+d' if sys.platform == 'darwin' else '<ctrl>+<shift>+d')
        self.window.open_settings()
        dialog = self.window._setup
        dialog.tabs.setCurrentWidget(dialog.shortcuts_tab)
        dialog.shortcut.recorder.setFocus()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), dialog.shortcut.recorder)
        with patch.object(self.window, 'request_lookup') as request:
            self.window.hotkey_requested.emit()
        request.assert_not_called()
        self.assertFalse(self.window.isVisible())
        self.assertTrue(dialog.isVisible())
        dialog.hide()

    def test_mac_search_survives_delayed_application_activation(self):
        with patch("sys.platform", "darwin"), patch.object(QApplication, "platformName", return_value="cocoa"), \
                patch.object(self.window, "isActiveWindow", return_value=False), \
                patch("meikipop.utils.window_focus.configure_macos_popup"), \
                patch("meikipop.utils.window_focus.focus_search"), \
                patch("meikipop.gui.quick_lookup.QCursor.pos", return_value=QPoint(-5000, -5000)):
            self.window.open_search()
            self.app.processEvents()
            self.window._dismiss_if_inactive()
            self.assertTrue(self.window._opening_search)
            self.assertTrue(self.window.isVisible())

    def test_automatic_text_lookup_is_opt_in_and_does_not_steal_focus(self):
        from meikipop.gui.text_triggers import TextTriggers
        triggers = TextTriggers(self.window)
        self.assertIsNone(triggers.listener)
        try:
            with patch.object(QApplication, "activeWindow", return_value=None), \
                    patch.object(QApplication, "activeModalWidget", return_value=None), \
                    patch.object(QApplication, "activePopupWidget", return_value=None), \
                    patch.object(QApplication, "doubleClickInterval", return_value=400), \
                    patch("meikipop.gui.text_triggers.QCursor.pos", return_value=QPoint(-100, -100)), \
                    patch("meikipop.utils.macos.require_input_monitoring_permission"), \
                    patch.object(self.window.selection, "start") as capture, patch("pynput.mouse.Listener") as listener:
                triggers.capture_selection()
                capture.assert_not_called()
                self.settings.setValue(f"profiles/{self.window.preferred_foreign}/selected_text", True)
                triggers.reload()
                listener.return_value.start.assert_called_once()
                triggers.click(-100, -100, True)
                triggers.click(-100, -100, False)
                triggers.click(-100, -100, True)
                triggers.click(-100, -100, False)
                self.wait_until(lambda: capture.called)
                capture.assert_called_once()
                self.assertTrue(self.window._selection_passive)
                self.settings.setValue(f"profiles/{self.window.preferred_foreign}/selected_text", False)
                triggers.reload()
                listener.return_value.stop.assert_called_once()
                triggers.capture_selection()
                capture.assert_called_once()
        finally:
            triggers.shutdown()
            triggers.deleteLater()

    def test_automatic_selection_capture_is_cancelled_by_new_interactions(self):
        from meikipop.gui.text_triggers import TextTriggers
        triggers = TextTriggers(self.window)
        try:
            with patch.object(QApplication, "activeWindow", return_value=None), \
                    patch.object(QApplication, "activeModalWidget", return_value=None), \
                    patch.object(QApplication, "activePopupWidget", return_value=None), \
                    patch.object(QApplication, "doubleClickInterval", return_value=400), \
                    patch("meikipop.utils.macos.require_input_monitoring_permission"), \
                    patch("pynput.mouse.Listener"), patch.object(self.window.selection, "start") as capture:
                self.settings.setValue("profiles/ja/selected_text", True)
                for action in (lambda: triggers.click(-200, -200, True),
                               lambda: triggers.click(-200, -200, True, left=False),
                               triggers.reload, triggers.shutdown):
                    triggers.press = triggers.last_click = None
                    for down in (True, False, True, False):
                        triggers.click(-100, -100, down)
                    self.assertTrue(triggers.capture_timer.isActive())
                    action()
                    self.assertFalse(triggers.capture_timer.isActive())
                capture.assert_not_called()
                triggers.reload()
                triggers.click(-100, -100, False)
                self.assertFalse(triggers.capture_timer.isActive())
        finally:
            triggers.shutdown()
            triggers.deleteLater()

    def test_automatic_selection_capture_ignores_open_menus(self):
        from meikipop.gui.text_triggers import TextTriggers
        triggers = TextTriggers(self.window)
        try:
            self.settings.setValue("profiles/ja/selected_text", True)
            with patch.object(QApplication, "activeWindow", return_value=None), \
                    patch.object(QApplication, "activePopupWidget", return_value=Mock()), \
                    patch.object(self.window.selection, "start") as capture:
                triggers.capture_selection()
                capture.assert_not_called()
        finally:
            triggers.shutdown()
            triggers.deleteLater()

    def test_selection_listener_does_not_hide_popup_on_scaled_display_or_scan_click(self):
        from meikipop.gui.text_triggers import TextTriggers
        triggers = TextTriggers(self.window)
        self.window.lookup_selected("猫", passive=True)
        try:
            with patch.object(QApplication, "activeWindow", return_value=None), \
                    patch("meikipop.gui.text_triggers.QCursor.pos", return_value=self.window.geometry().center()):
                triggers.click(2000, 2000, True)
                self.assertTrue(self.window.isVisible())
                self.window._passive_text = False
                self.window._opening_search = False
                self.window._dismiss_if_inactive()
                self.assertTrue(self.window.isVisible())
            self.window.scan_hold_changed(True)
            with patch.object(QApplication, "activeWindow", return_value=None), \
                    patch("meikipop.gui.text_triggers.QCursor.pos", return_value=QPoint(-500, -500)), \
                    patch.object(self.window.selection, "start") as capture:
                triggers.click(-500, -500, True)
                triggers.capture_selection()
                self.assertTrue(self.window.isVisible())
                capture.assert_not_called()
        finally:
            triggers.shutdown()
            triggers.deleteLater()

    def test_selection_uses_lookup_autoplay_and_shortcut_toggles_visible_popup(self):
        self.settings.setValue("profiles/ja/audio_autoplay_mode", "lookup")
        self.window.audio = Mock()
        self.window.lookup_selected("猫", passive=True)
        self.wait_until(lambda: self.window._result is not None)
        self.window.audio.play.assert_called_once()
        self.window.hotkey_requested.emit()
        self.assertFalse(self.window.isVisible())
        with patch.object(self.window, "request_lookup") as request:
            self.window.hotkey_requested.emit()
            request.assert_called_once()

    def test_latest_worker_coalesces_pending_requests(self):
        started, release = threading.Event(), threading.Event()
        engine = FakeEngine()
        original = engine.search

        def slow(text, **kwargs):
            if text == "first":
                started.set()
                release.wait(2)
            return original(text, **kwargs)

        engine.search = slow
        worker = LookupWorker(engine_factory=lambda: engine)
        worker.start()
        try:
            worker.request(1, "first", "ja", "tr")
            self.assertTrue(started.wait(2))
            worker.request(2, "obsolete", "ja", "tr")
            worker.request(3, "latest", "ja", "tr")
            release.set()
            self.wait_until(lambda: len(engine.calls) == 2)
            self.assertEqual([call[0] for call in engine.calls], ["first", "latest"])
        finally:
            release.set()
            worker.shutdown()
            worker._thread.join(timeout=2)
        self.assertTrue(engine.closed)


class DictionaryManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "library"
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/target", "en")
        self.dialog = SetupDialog(self.directory, self.settings, Mock())

    def tearDown(self):
        if self.dialog.operation is not None:
            self.dialog.cancel_operation()
            self.dialog.operation.thread.join(timeout=3)
        self.dialog.hide()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def archive(self, title, language=None):
        path = Path(self.temp.name) / f"{title}.zip"
        metadata = {"title": title, "format": 3}
        if language:
            metadata["sourceLanguage"] = language
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("index.json", json.dumps(metadata))
            archive.writestr("term_bank_1.json", json.dumps([["araç", "", "", "", 1, ["vehicle"]]]))
        return path

    def wait_for_operation(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if self.dialog.operation is None:
                return
            time.sleep(0.005)
        self.fail("Setup did not finish")

    def test_multiple_imports_keep_declared_language_and_use_explicit_legacy_language(self):
        legacy = self.archive("Legacy")
        turkish = self.archive("Turkdict", "tr")
        self.dialog.begin_operation([legacy, turkish], language="ja")
        self.wait_for_operation()
        library = Library(self.directory)
        try:
            languages = {metadata["title"]: metadata["language"] for _, metadata, _ in library.packs}
            self.assertEqual(languages, {"Legacy": "ja", "Turkdict": "tr"})
        finally:
            library.close()
        self.assertEqual(self.dialog.packs.count(), 2)

    def test_import_keeps_ui_responsive_and_continues_after_settings_close(self):
        from PyQt6.QtCore import QTimer
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            self.dialog.begin_operation([self.archive("Background", "ja")])
            operation = self.dialog.operation
            self.dialog.reject()
            self.assertFalse(operation.cancelled.is_set())
            self.assertEqual(self.dialog.windowModality(), Qt.WindowModality.NonModal)
            self.wait_for_operation()
            self.assertGreater(len(ticks), 0)
            self.assertEqual(self.dialog.packs.count(), 1)
        finally:
            timer.stop()

    def test_russian_ocr_default_and_paddle_availability_follow_profile(self):
        with patch("meikipop.gui.dictionary_manager.sys.platform", "win32"):
            self.dialog.sync_profile("ru")
            provider = self.dialog.other_ocr_provider
            self.assertEqual(provider.currentData(), "screenai")
            self.assertFalse(provider.model().item(provider.findData("paddle")).isEnabled())
            self.dialog.sync_profile("de")
            self.assertEqual(provider.currentData(), "paddle")
            self.assertTrue(provider.model().item(provider.findData("paddle")).isEnabled())

    @patch("meikipop.gui.dictionary_manager.sys.platform", "win32")
    def test_unsupported_ocr_profile_keeps_dictionary_and_saved_provider(self):
        self.settings.setValue("profiles/gem-pro/ocr_provider", "screenai")
        self.dialog.sync_profile("gem-pro")
        provider = self.dialog.other_ocr_provider
        self.assertEqual(self.dialog.profile.currentData(), "gem-pro")
        self.assertEqual(provider.currentData(), "screenai")
        self.assertFalse(provider.isEnabled())
        self.assertFalse(provider.model().item(provider.findData("screenai")).isEnabled())
        self.assertFalse(self.dialog.scan_key.isEnabled())
        self.assertFalse(self.dialog.scan_mouse.isEnabled())
        self.assertEqual(self.settings.value("profiles/gem-pro/ocr_provider"), "screenai")
        self.dialog.sync_profile("ar")
        self.assertEqual(provider.currentData(), "screenai")
        self.assertTrue(provider.isEnabled())
        self.assertTrue(provider.model().item(provider.findData("screenai")).isEnabled())
        self.assertFalse(provider.model().item(provider.findData("paddle")).isEnabled())

    @patch("meikipop.gui.dictionary_manager.sys.platform", "win32")
    def test_mandarin_ocr_alias_uses_supported_provider(self):
        self.dialog.sync_profile("cmn")
        provider = self.dialog.other_ocr_provider
        self.assertEqual(provider.currentData(), "paddle")
        self.assertTrue(provider.model().item(provider.findData("paddle")).isEnabled())

    def test_startup_preference_is_saved_only_after_registry_success(self):
        from PyQt6.QtWidgets import QCheckBox
        self.dialog.settings.remove("start_with_windows")
        self.dialog.start_with_windows = QCheckBox(self.dialog)
        with patch("meikipop.utils.startup.set_startup_enabled") as startup:
            self.dialog.save_startup(False)
            startup.assert_called_once_with(False)
        self.assertFalse(self.dialog.settings.value("start_with_windows", True, bool))
        with patch("meikipop.utils.startup.set_startup_enabled", side_effect=OSError("blocked")):
            self.dialog.save_startup(True)
        self.assertFalse(self.dialog.settings.value("start_with_windows", True, bool))

    def test_frozen_scan_setting_saves_independently_per_profile(self):
        self.dialog.sync_profile("ja")
        self.assertTrue(self.dialog.freeze_while_held.isChecked())
        self.dialog.freeze_while_held.setChecked(False)
        self.assertFalse(self.settings.value("profiles/ja/freeze_while_held", True, bool))
        self.dialog.sync_profile("tr")
        self.assertTrue(self.dialog.freeze_while_held.isChecked())
        self.dialog.sync_profile("ja")
        self.assertFalse(self.dialog.freeze_while_held.isChecked())

    def test_new_profiles_inherit_scan_shortcut_and_preserve_explicit_disable(self):
        self.dialog.sync_profile("tr")
        self.settings.setValue("profiles/tr/scan_bindings", "shift,middle")
        self.dialog.add_profile("id")
        self.assertEqual(self.settings.value("profiles/id/scan_bindings"), "shift,middle")
        self.settings.setValue("profiles/id/scan_bindings", "")
        self.dialog.add_profile("ru")
        self.assertEqual(self.settings.value("profiles/ru/scan_bindings"), "")
        self.dialog.sync_profile("tr")
        self.dialog.add_profile("id")
        self.assertEqual(self.settings.value("profiles/id/scan_bindings"), "")

    def test_base_form_setup_is_explicit_and_follows_selected_profile(self):
        with patch("meikipop.language.stanza_analyzer.model_status", return_value="Not installed"), \
                patch("meikipop.scripts.setup_morphology.install") as install:
            self.dialog.sync_profile("ru")
            install.assert_not_called()
            self.assertFalse(self.dialog.resources.base_install.isHidden())
            self.dialog.resources.base_install.click()
            self.wait_for_operation()
            self.assertEqual(install.call_args.args[0], "ru")
            self.assertIn("installed", self.dialog.status.text())
            self.dialog.sync_profile("ja")
            self.assertTrue(self.dialog.resources.base_install.isHidden())

    def test_turkish_engine_status_remains_visible_after_installation(self):
        with patch("meikipop.language.turkish_analyzer.available", return_value=True), \
                patch("meikipop.language.stanza_analyzer.model_status", return_value="Installed") as status:
            self.dialog.sync_profile("tr")
            resources = self.dialog.resources
            self.assertEqual(resources.base_status.text(), "Word forms: Zeyrek")
            self.assertFalse(resources.base_status.isHidden())
            self.assertTrue(resources.base_install.isHidden())
            status.return_value = "Model needed"
            resources.refresh()
            self.assertEqual(resources.base_status.text(), "Word forms: Zeyrek")
            self.assertTrue(resources.base_install.isHidden())
            self.dialog.sync_profile("ja")
            self.assertTrue(resources.base_status.isHidden())

    def test_preview_definition_limit_is_saved_per_profile_with_all_option(self):
        self.dialog.sync_profile('tr')
        self.assertFalse(hasattr(self.dialog.appearance, 'pinned_definitions'))
        self.dialog.appearance.preview_definitions.setValue(0)
        self.assertEqual(self.settings.value('profiles/tr/preview_definitions', type=int), 0)
        self.dialog.sync_profile('ja')
        self.assertEqual(self.dialog.appearance.preview_definitions.value(), 1)
        self.dialog.sync_profile('tr')
        self.assertEqual(self.dialog.appearance.preview_definitions.text(), 'All')

    def test_legacy_import_requires_a_language_in_automatic_mode(self):
        self.dialog.begin_operation([self.archive("Legacy")])
        self.wait_for_operation()
        self.assertIn("Choose its language", self.dialog.status.text())
        self.assertEqual(self.dialog.packs.count(), 0)

    def test_disable_and_order_are_saved(self):
        self.dialog.begin_operation([self.archive("A", "tr"), self.archive("B", "tr")])
        self.wait_for_operation()
        self.dialog.packs.setCurrentRow(1)
        self.dialog.profile.setCurrentIndex(self.dialog.profile.findData("tr"))
        name = self.dialog.packs.item(1).data(Qt.ItemDataRole.UserRole)
        self.dialog.move_pack(-1)
        self.assertEqual(json.loads((self.directory / "preferences.json").read_text())["order"][0], name)
        self.dialog.packs.item(0).setCheckState(Qt.CheckState.Unchecked)
        saved = json.loads((self.directory / "preferences.json").read_text())
        self.assertEqual(saved["order"][0], name)
        self.assertEqual(saved["disabled"], [name])

    def test_cancelled_operation_keeps_completed_imports(self):
        first, second = self.archive("A", "tr"), self.archive("B", "tr")
        operation = SetupOperation([first, second], self.directory)
        from meikipop.dictionary.library import import_yomitan

        def import_then_cancel(*args, **kwargs):
            result = import_yomitan(*args, **kwargs)
            operation.cancelled.set()
            return result

        from meikipop.dictionary.import_job import import_batch
        with patch("meikipop.dictionary.import_job.import_yomitan", side_effect=import_then_cancel):
            import_batch([first, second], self.directory, None, lambda text: None, operation.cancelled)
        library = Library(self.directory)
        try:
            self.assertEqual([metadata["title"] for _, metadata, _ in library.packs], ["A"])
        finally:
            library.close()
        self.assertFalse(list(self.directory.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
