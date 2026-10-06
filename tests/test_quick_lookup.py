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

from PyQt6.QtCore import QEvent, QPoint, QSettings, Qt, QUrl
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from meikipop.dictionary.library import Entry, Library
from meikipop.dictionary.kanji import KanjiEntry
from meikipop.dictionary.metadata import Frequency
from meikipop.dictionary.search import SearchResult
from meikipop.gui.dictionary_manager import SetupDialog, SetupOperation
from meikipop.gui.quick_lookup import LookupWorker, QuickLookupWindow, render_result


def entry(term="猫", source="Dictionary", definitions=("cat",), language="ja"):
    return Entry(f"{source}:{term}", term, "ねこ" if language == "ja" else "", source,
                 language, tuple(definitions))


class FakeEngine:
    def __init__(self):
        self.library = SimpleNamespace(packs=[(None, {"language": "de"}, None)])
        self.calls = []
        self.closed = False

    def search(self, text, source="auto", foreign="ja", translate=False, target=None, pair=None, translation_settings=None):
        self.calls.append((text, source, foreign, translate, threading.get_ident()))
        return SearchResult(text, "ja" if source == "auto" else source, "en",
                            () if translate else (entry(text),), translation="translated" if translate else "")

    def refresh(self):
        pass

    def close(self):
        self.closed = True


class QuickLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
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

    def test_morphology_option_follows_profile_for_dictionary_lookup_only(self):
        self.settings.setValue("profiles/tr/morphology", True)
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
        self.assertEqual(dialog.appearance.theme.currentText(), "Monochrome Dark")
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
        self.assertIn("translated", self.window.browser.toPlainText())
        self.window.search.returnPressed.emit()
        self.wait_until(lambda: len(self.engine.calls) == 2)
        self.assertFalse(self.engine.calls[1][3])

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
        self.assertEqual(self.window.height(), 420)

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

    def test_jitendex_preview_reduces_nesting_and_separates_tags(self):
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
        self.assertIn("noun archaic", text)
        self.assertIn("first gloss; second gloss", text)
        self.assertNotIn("alternate form", text)
        cursor = self.window.browser.document().find("first gloss")
        cursor.setPosition(cursor.selectionStart())
        self.assertLess(self.window.browser.cursorRect(cursor).x(), 80)
        self.window.pin.setChecked(True)
        self.assertIn("alternate form", self.window.browser.toPlainText())
        self.assertIn("JMdict footer", self.window.browser.toPlainText())

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

    def test_switching_to_english_keeps_previous_foreign_mode(self):
        self.window.set_mode("tr")
        self.window.set_mode("en")
        self.assertEqual(self.window.preferred_foreign, "tr")
        self.assertEqual(self.window.foreign.currentData(), "en")

    def test_explicit_sentence_skips_dictionary_and_translates_into_english(self):
        self.settings.setValue("profiles/ja/auto_translate_sentence", True)
        self.window.lookup_selected("昨日は朝ご飯を食べなかった。")
        self.wait_until(lambda: self.window._result is not None)
        self.assertTrue(self.engine.calls[0][3])
        self.assertEqual(self.window._result.entries, ())
        self.assertNotIn("No entry", self.window.browser.toPlainText())

    def test_word_without_dictionary_hit_falls_back_to_translation_once(self):
        self.settings.setValue("profiles/ja/auto_translate_miss", True)
        original = self.engine.search
        def missing(text, **options):
            result = original(text, **options)
            return result if options.get("translate") else replace(result, entries=(), message="No entry found.")
        self.engine.search = missing
        self.window.open_search("unknown")
        self.wait_until(lambda: self.window._result is not None and self.window._result.translation)
        self.assertEqual([call[3] for call in self.engine.calls], [False, True])
        self.assertNotIn("No entry", self.window.browser.toPlainText())

    def test_short_japanese_sentence_does_not_stop_at_first_dictionary_word(self):
        self.settings.setValue("profiles/ja/auto_translate_miss", True)
        original = self.engine.search
        self.engine.search = lambda text, **options: replace(original(text, **options), matched_length=1)
        self.window.open_search("猫がいる")
        self.wait_until(lambda: self.window._result is not None and self.window._result.translation)
        self.assertEqual([call[3] for call in self.engine.calls], [False, True])

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
            self.assertEqual(self.settings.value("profiles/de/scan_bindings"), "")
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
            dialog.pin_gesture.setCurrentIndex(dialog.pin_gesture.findData("middle"))
            self.assertEqual(self.settings.value("profiles/tr/pin_gesture"), "middle")
            dialog.audio_sources.items.setCurrentRow(1)
            dialog.audio_sources.move(-1)
            self.assertEqual(self.settings.value("profiles/tr/audio_order")[0], "tts")
            dialog.sync_profile("ja")
            self.assertEqual(dialog.audio_volume.value(), 42)
            self.assertEqual(dialog.translation_target.currentData(), "ru")
            self.assertFalse(dialog.appearance.compact_preview.isChecked())
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

    def test_typed_results_are_silent_for_all_autoplay_modes(self):
        self.window.audio = Mock()
        for mode in ("lookup", "pin", "off"):
            self.settings.setValue("profiles/ja/audio_autoplay_mode", mode)
            self.window.open_search()
            self.window._display(SearchResult("猫", "ja", "en", (entry(),)))
            self.window._display(SearchResult("猫がいる。", "ja", "en", translation="There is a cat."))
        self.window.audio.play.assert_not_called()
        self.window.audio.play_text.assert_not_called()

    def test_ocr_translation_keeps_source_when_input_is_hidden(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.pin.setChecked(True)
        self.window._display(SearchResult("猫がいる。", "ja", "en", translation="There is a cat."))
        self.assertIn("猫がいる。", self.window.browser.toPlainText())

    def test_pinned_sentence_is_optional_per_profile_and_reuses_unchanged_document(self):
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
        self.assertTrue(self.window.header.isHidden())
        self.assertEqual(self.window.audio_actions.parentWidget(), self.window.browser.viewport())
        self.assertEqual(self.window.audio_actions.layout().indexOf(self.window.translate), 0)
        self.assertEqual(self.window.audio_actions.layout().indexOf(self.window.sentence_audio_button), 1)
        self.assertEqual(self.window.audio_actions.layout().indexOf(self.window.audio_button), 2)
        self.assertEqual(self.window.actions_row.layout().indexOf(self.window.audio_button), -1)
        self.assertTrue(self.window.pin.isHidden())
        self.assertEqual(self.window.actions_row.layout().indexOf(self.window.copy_button), 2)
        self.assertEqual(self.window.actions_row.layout().indexOf(self.window.dismiss_button), 3)
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
        result = SearchResult("oğlum", "tr", "en", (replace(entry("oğul", language="tr"),
                                                            inflection=("my (possessive)",)),))
        self.window.show_entries(result.entries, result.text, "tr", peek=True)
        self.assertIn("my (possessive)", self.window.browser.toPlainText())
        self.window.show_entries((entry("geldim", language="tr"),
                                  replace(entry("gelmek", language="tr"), inflection=("past", "I"))),
                                 "geldim", "tr", peek=True)
        self.assertIn("gelmek · past · I", self.window.browser.toPlainText())

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

    def test_rendering_previews_every_dictionary_and_expands_structured_glosses(self):
        definitions = ({"type": "structured-content", "content": {
            "tag": "div", "content": [{"tag": "span", "content": "Turkdict example " + "long " * 150},
                                       {"tag": "p", "content": "Final example"}]}},)
        result = SearchResult("arac", "tr", "en", (
            entry("araç", "Turkdict", definitions, "tr"),
            entry("araç", "Other", ("vehicle",), "tr")))
        self.window.show_entries(result.entries, "arac", "tr")
        self.assertIn("Turkdict", self.window.browser.toPlainText())
        self.assertIn("Other", self.window.browser.toPlainText())
        self.assertNotIn("Final example", self.window.browser.toPlainText())
        self.window._link(QUrl("expand:0"))
        self.assertIn("Final example", self.window.browser.toPlainText())
        self.assertIn("Turkdict", self.window._expanded)
        self.window._link(QUrl("expand:0"))
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
        preview = render_result(result)
        self.assertIn("<ol><li>vehicle", preview)
        self.assertNotIn("Hidden example", preview)
        self.assertNotIn("Third sense", preview)
        expanded = render_result(result, {"Turkdict"})
        self.assertIn("Hidden example", expanded)
        self.assertIn("Third sense", expanded)
        self.assertNotIn("Fourth sense", expanded)
        self.assertIn('href="expand:1"', expanded)

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

    def test_copy_click_pins_before_copy_and_dismiss_does_not_pin(self):
        self.window.show_entries((entry(),), "猫", peek=True)
        self.window.set_context("猫がいる。")
        with patch.object(QApplication, "clipboard") as clipboard:
            clipboard.return_value.setText.side_effect = lambda _: self.assertTrue(self.window.is_pinned)
            QTest.mouseClick(self.window.copy_button, Qt.MouseButton.LeftButton)
            clipboard.return_value.setText.assert_called_once_with("猫がいる。")
        self.window.pin.setChecked(False)
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

    def test_popup_hides_technical_tooltips_and_keeps_copy_preview(self):
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
        self.assertNotIn("Hy-MT2", self.window.translate.toolTip())
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
                self.assertEqual(html.count("<h2>koyun</h2>"), 1)
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
        self.assertNotIn("Fourth sense", self.window.browser.toPlainText())
        self.window._link(QUrl("expand:0"))
        self.assertIn("Fourth sense", self.window.browser.toPlainText())
        self.assertNotIn("Strokes 11", self.window.browser.toPlainText())
        self.window._link(QUrl("kanji:toggle"))
        self.assertNotIn("Strokes", self.window.browser.toPlainText())
        self.assertIn("Fourth sense", self.window.browser.toPlainText())

    def test_default_search_shortcut_can_be_disabled(self):
        self.assertIsNone(self.window._keys)
        with patch("meikipop.gui.text_shortcuts.TextHotKeys") as hotkeys:
            self.window.restore_shortcut()
            import sys
            self.assertEqual(self.settings.value("hotkey"),
                             "<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d")
            hotkeys.return_value.start.assert_called_once()
            self.window.apply_shortcut("")
            hotkeys.return_value.stop.assert_called_once()
            self.assertIsNone(self.window._keys)
            self.window.restore_shortcut()
            self.assertIsNone(self.window._keys)

    def test_lookup_shortcut_prefers_selection_then_falls_back_to_clipboard(self):
        with patch.object(QApplication, "activeWindow", return_value=None), \
                patch.object(QApplication, "clipboard") as clipboard, \
                patch.object(self.window.selection, "start") as capture:
            clipboard.return_value.text.return_value = "clipboard"
            self.window.request_lookup()
            capture.assert_called_once_with(wait_for_modifiers=True, copy_timeout=.05)
            self.assertFalse(self.window.isVisible())
            self.window.selection.completed.emit("selected")
            self.assertEqual(self.window.search.text(), "selected")
            self.window.request_lookup()
            self.window.selection.unavailable.emit(True)
            self.assertEqual(self.window.search.text(), "clipboard")
            self.window.hide()
            self.window.request_lookup()
            self.window.selection.unavailable.emit(False)
            self.assertFalse(self.window.isVisible())

    def test_shortcut_clipboard_sentence_translates_without_dictionary_lookup(self):
        self.settings.setValue("profiles/ja/auto_translate_sentence", True)
        with patch.object(QApplication, "activeWindow", return_value=None), \
                patch.object(QApplication, "clipboard") as clipboard, \
                patch.object(self.window.selection, "start"):
            clipboard.return_value.text.return_value = "This is a complete sentence."
            self.window.request_lookup()
            self.window.selection.unavailable.emit(True)
            self.wait_until(lambda: self.window._result is not None)
            self.assertEqual(len(self.engine.calls), 1)
            self.assertTrue(self.engine.calls[0][3])

    def test_typed_lookup_takes_focus_after_passive_selection(self):
        with patch("meikipop.utils.window_focus.focus_search") as focus:
            self.window.lookup_selected("word", passive=True)
            self.app.processEvents()
            focus.assert_not_called()
            self.window.open_search()
            self.app.processEvents()
            focus.assert_called_once_with(self.window)
            self.assertFalse(self.window._passive_text)

    def test_automatic_text_lookup_is_opt_in_and_does_not_steal_focus(self):
        from meikipop.gui.text_triggers import TextTriggers
        triggers = TextTriggers(self.window)
        self.assertIsNone(triggers.listener)
        try:
            with patch.object(QApplication, "activeWindow", return_value=None), \
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
                QTest.qWait(80)
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

        with patch("meikipop.gui.dictionary_manager.import_yomitan", side_effect=import_then_cancel):
            operation.start()
            operation.thread.join(timeout=3)
        self.assertFalse(operation.thread.is_alive())
        library = Library(self.directory)
        try:
            self.assertEqual([metadata["title"] for _, metadata, _ in library.packs], ["A"])
        finally:
            library.close()
        self.assertFalse(list(self.directory.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
