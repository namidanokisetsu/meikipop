import os
import json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
from PyQt6.QtWidgets import QApplication

from meikipop.anki import AnkiSettings, load_settings
from meikipop.dictionary.library import Entry
from meikipop.dictionary.kanji import KanjiEntry
from meikipop.gui.anki import AnkiSettingsPanel, export_note
from meikipop.gui.quick_lookup import QuickLookupWindow
from test_quick_lookup import FakeEngine


class AnkiGuiTests(unittest.TestCase):
    def test_card_glossary_uses_ruby_and_compact_left_aligned_definitions(self):
        from meikipop.gui.anki import _AnkiGlossConverter
        from meikipop.anki import note_values
        definition = {"type": "structured-content", "content": {
            "tag": "ul", "content": [{"tag": "li", "content": {
                "tag": "ruby", "content": ["猫", {"tag": "rt", "content": "ねこ"}]}}]}}
        entry = Entry("1", "猫", "ねこ", "Words", "ja", (definition,))
        values = note_values([entry], converter=_AnkiGlossConverter())
        for name in ("glossary", "glossary-first"):
            self.assertIn("text-align:left", values[name])
            self.assertIn("padding-left:1.2em", values[name])
            self.assertIn("<ruby>猫<rt>ねこ</rt></ruby>", values[name])
        self.assertNotIn("<b>Words</b>", values["glossary"])

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.widgets = []
        self.existing_patch = patch("meikipop.anki.AnkiClient.existing_notes", return_value={})
        self.existing_patch.start()

    def tearDown(self):
        for widget in reversed(self.widgets):
            if isinstance(widget, QuickLookupWindow):
                widget.shutdown()
                widget.worker._thread.join(2)
            task = getattr(widget, "_task", None) or getattr(widget, "_anki_task", None)
            if task:
                task.thread.join(2)
            check = getattr(widget, "_anki_check_task", None)
            if check:
                check.thread.join(2)
            widget.hide()
            widget.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.settings.clear()
        self.settings.sync()
        self.temp.cleanup()
        self.existing_patch.stop()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Anki worker timed out")

    def test_settings_offline_load_and_async_mapping_are_profile_specific(self):
        panel = AnkiSettingsPanel(self.settings)
        self.widgets.append(panel)
        with patch("meikipop.gui.anki.AnkiClient") as client:
            panel.load("ja")
            client.assert_not_called()
            self.assertTrue(panel.options.isHidden())
            client.return_value.catalog.return_value = (["Japanese"], ["Basic"])
            client.return_value.names.return_value = ["Front", "Back", "Reading"]
            panel.enabled.setChecked(True)
            self.assertFalse(panel.options.isHidden())
            self.wait_until(lambda: panel.status.text() == "Connected.")
        panel._field_controls["Reading"].setCurrentIndex(panel._field_controls["Reading"].findData("reading"))
        self.assertEqual(load_settings(self.settings, "ja").fields,
                         {"Front": "expression", "Back": "glossary", "Reading": "reading"})
        panel.load("tr")
        self.assertFalse(panel.enabled.isChecked())
        self.assertTrue(panel.options.isHidden())
        self.assertTrue(panel.shortcut.enabled.isChecked())
        self.assertEqual(panel.shortcut.recorder.keySequence().toString(), "Shift+A")
        panel.load("ja")
        self.assertEqual(panel._field_controls["Reading"].currentData(), "reading")

    def test_opening_enabled_settings_refreshes_catalog_and_preserves_choices(self):
        prefix = "profiles/ja/anki/"
        self.settings.setValue(prefix + "enabled", True)
        self.settings.setValue(prefix + "deck", "Japanese")
        self.settings.setValue(prefix + "model", "Basic")
        panel = AnkiSettingsPanel(self.settings)
        self.widgets.append(panel)
        panel.load("ja")
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.catalog.return_value = (["Default", "Japanese"], ["Cloze", "Basic"])
            client.return_value.names.return_value = ["Front", "Back"]
            panel.show()
            self.wait_until(lambda: panel.status.text() == "Connected.")
        self.assertEqual(panel.deck.count(), 2)
        self.assertEqual(panel.model.count(), 2)
        self.assertEqual(panel.deck.currentText(), "Japanese")
        self.assertEqual(panel.model.currentText(), "Basic")

    def test_duplicate_controls_preserve_decks_and_profiles(self):
        prefix = "profiles/ja/anki/"
        self.settings.setValue(prefix + "deck", "Japanese")
        self.settings.setValue(prefix + "duplicate_decks", json.dumps(["Other"]))
        self.settings.setValue(prefix + "duplicate_scope", "decks")
        panel = AnkiSettingsPanel(self.settings)
        self.widgets.append(panel)
        panel.load("ja")
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.catalog.return_value = (["Japanese", "Other", "New"], ["Basic"])
            client.return_value.names.return_value = ["Front", "Back"]
            panel.refresh()
            self.wait_until(lambda: panel.status.text() == "Connected.")
        actions = {action.text(): action for action in panel.duplicate_decks.menu().actions()}
        self.assertTrue(actions["Japanese"].isChecked())
        self.assertFalse(actions["Japanese"].isEnabled())
        self.assertTrue(actions["Other"].isChecked())
        actions["New"].setChecked(True)
        panel.check_all_models.setChecked(True)
        panel.duplicate_action.setCurrentIndex(panel.duplicate_action.findData("allow"))
        self.assertFalse(panel.duplicate_scope.isEnabled())
        self.assertFalse(panel.duplicate_decks.isEnabled())
        options = load_settings(self.settings, "ja")
        self.assertEqual(options.duplicate_decks, ("New", "Other"))
        self.assertEqual(options.duplicate_action, "allow")
        self.assertTrue(options.check_all_models)
        panel.load("tr")
        self.assertEqual(panel.duplicate_action.currentData(), "prevent")
        self.assertEqual(panel.duplicate_scope.currentData(), "deck")
        self.assertFalse(panel.check_all_models.isChecked())
        panel.load("ja")
        self.assertEqual(panel.duplicate_scope.currentData(), "decks")
        self.assertEqual(panel.duplicate_decks.text(), "2 selected")

    def test_duplicate_rejection_skips_all_note_preparation(self):
        from unittest.mock import Mock
        entry = Entry("1", "cat & dog", "", "Words", "ja", ("definition",))
        options = AnkiSettings(True, fields={"Front": "expression", "Back": "glossary", "Image": "picture",
                                            "Sentence": "sentence_furigana"})
        screenshot = Mock()
        with patch("meikipop.gui.anki.AnkiClient") as client, patch("meikipop.gui.anki._AnkiGlossConverter") as converter, \
                patch("meikipop.dictionary.library.Library") as library:
            client.return_value.check.side_effect = ValueError("duplicate")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                export_note([entry], "cat here", "", options, screenshot=screenshot)
            client.return_value.check.assert_called_once_with("cat &amp; dog")
            client.return_value.add.assert_not_called()
            converter.assert_not_called()
            library.assert_not_called()
            screenshot.image.assert_not_called()

    def test_connection_error_can_be_reloaded(self):
        panel = AnkiSettingsPanel(self.settings)
        self.widgets.append(panel)
        panel.load("ja")
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.catalog.side_effect = ValueError("Open Anki and check AnkiConnect.")
            panel.enabled.setChecked(True)
            self.wait_until(lambda: panel._task is None)
            self.assertIn("Open Anki", panel.status.text())
            self.assertTrue(panel.reload.isEnabled())
            client.return_value.catalog.side_effect = None
            client.return_value.catalog.return_value = (["Japanese"], ["Basic"])
            client.return_value.names.return_value = ["Front", "Back"]
            panel.reload.click()
            self.wait_until(lambda: panel.status.text() == "Connected.")

    def test_enabled_profile_switch_refreshes_after_pending_request(self):
        for profile in ("ja", "tr"):
            self.settings.setValue(f"profiles/{profile}/anki/enabled", True)
        panel = AnkiSettingsPanel(self.settings)
        self.widgets.append(panel)
        gate = threading.Event()
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.catalog.side_effect = [
                (["Old"], ["Basic"]), (["Turkish"], ["Basic"])]
            client.return_value.names.side_effect = lambda *_args, **_kwargs: (gate.wait(2), ["Front", "Back"])[1]
            panel.load("ja")
            panel.show()
            self.wait_until(lambda: panel._task is not None and panel._task.context[1] == "fields")
            panel.load("tr")
            gate.set()
            self.wait_until(lambda: panel.status.text() == "Connected.")
        self.assertEqual(panel.deck.currentText(), "Turkish")
        self.assertEqual(load_settings(self.settings, "tr").deck, "Turkish")

    def test_profile_switch_discards_pending_catalog(self):
        panel = AnkiSettingsPanel(self.settings)
        self.widgets.append(panel)
        gate = threading.Event()
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.catalog.side_effect = lambda: (gate.wait(2), (["Old"], ["Basic"]))[1]
            panel.load("ja")
            panel.refresh()
            panel.load("tr")
            gate.set()
            self.wait_until(lambda: panel._task is None)
        self.assertEqual(panel.deck.count(), 0)
        self.assertEqual(load_settings(self.settings, "tr").deck, "")

    def anki_window(self, fields=None):
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/target", "en")
        for key, value in dict(enabled=True, deck="Japanese", model="Basic",
                               fields=json.dumps(fields or {"Front": "expression", "Back": "glossary"})).items():
            self.settings.setValue(f"profiles/ja/anki/{key}", value)
        window = QuickLookupWindow(self.temp.name, FakeEngine, self.settings)
        self.widgets.append(window)
        return window

    def test_existing_word_shows_saved_state_and_opens_all_matching_notes(self):
        window = self.anki_window()
        with patch("meikipop.anki.AnkiClient.existing_notes", return_value={"cat": (123, 456)}):
            window.show_entries([Entry("1", "cat", "", "Words", "ja", ("cat",))], "cat")
            self.wait_until(lambda: window._anki_check_task is None)
        self.assertEqual(window.anki_button.property("action_name"), "anki_saved")
        self.assertEqual(window.anki_button.toolTip(), "Show in Anki")
        with patch("meikipop.anki.AnkiClient") as client:
            window.anki_button.click()
            self.wait_until(lambda: window._anki_browse_task is None)
            client.return_value.call.assert_called_once_with("guiBrowse", query="nid:123,456")
            client.return_value.add.assert_not_called()

    def test_existing_word_can_still_be_mined_when_duplicates_are_allowed(self):
        window = self.anki_window()
        self.settings.setValue("profiles/ja/anki/duplicate_action", "allow")
        with patch("meikipop.anki.AnkiClient.existing_notes", return_value={"cat": (123,)}):
            window.show_entries([Entry("1", "cat", "", "Words", "ja", ("cat",))], "cat")
            self.wait_until(lambda: window._anki_check_task is None)
        self.assertEqual(window.anki_button.property("action_name"), "anki_saved")
        self.assertEqual(window.anki_button.toolTip(), "Add another note")
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.add.return_value = 456
            window.anki_button.click()
            self.wait_until(lambda: window._anki_task is None)
            client.return_value.add.assert_called_once()

    def test_existing_note_check_discards_stale_results_and_checks_latest_word(self):
        window = self.anki_window()
        gate = threading.Event()
        def find(words):
            if words == ("cat",):
                gate.wait(2)
                return {"cat": (123,)}
            return {}
        with patch("meikipop.anki.AnkiClient.existing_notes", side_effect=find) as check:
            window.show_entries([Entry("1", "cat", "", "Words", "ja", ("cat",))], "cat")
            window.show_entries([Entry("2", "dog", "", "Words", "ja", ("dog",))], "dog")
            gate.set()
            self.wait_until(lambda: window._anki_check_task is None)
            self.assertEqual(check.call_count, 2)
        self.assertEqual(window.anki_button.toolTip(), "Add to Anki")
        self.assertEqual(window._anki_existing_notes, {})

    def test_one_click_snapshots_all_entries_context_and_selection_without_a_dialog(self):
        from PyQt6.QtGui import QTextCursor
        window = self.anki_window()
        entries = [Entry("1", "cat", "", "Words", "ja", ("first sense", "second sense")),
                   Entry("2", "cat", "", "Other words", "ja", ("another dictionary",))]
        window.show_entries(entries, "cat")
        window.set_context("A cat <here>.")
        window.browser.setHtml("chosen &lt;sense&gt;")
        cursor = window.browser.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        window.browser.setTextCursor(cursor)
        gate = threading.Event()
        threads = []
        def add(values):
            threads.append(threading.get_ident())
            gate.wait(2)
            return 123
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.add.side_effect = add
            window.anki_button.click()
            self.assertIsNotNone(window._anki_task)
            self.assertFalse(window.anki_button.isEnabled())
            self.assertFalse(any(widget.isModal() for widget in self.app.topLevelWidgets()))
            window.add_to_anki()
            window.set_context("changed context")
            window.browser.setHtml("changed selection")
            gate.set()
            self.wait_until(lambda: window._anki_task is None)
            with patch("meikipop.anki.AnkiClient") as browser_client:
                window.add_to_anki()
                self.wait_until(lambda: window._anki_browse_task is None)
                browser_client.return_value.call.assert_called_once_with("guiBrowse", query="nid:123")
        client.return_value.add.assert_called_once()
        values = client.return_value.add.call_args.args[0]
        self.assertEqual(values["sentence"], "A cat &lt;here&gt;.")
        self.assertEqual(values["popup-selection-text"], "chosen &lt;sense&gt;")
        self.assertIn("first sense", values["glossary-first"])
        self.assertIn("second sense", values["glossary-first"])
        self.assertNotIn("another dictionary", values["glossary-first"])
        for content in ("first sense", "second sense", "another dictionary", "Words", "Other words"):
            self.assertIn(content, values["glossary"])
        self.assertNotIn("chosen", values["glossary"])
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertEqual(window.anki_button.toolTip(), "Show in Anki")
        self.assertTrue(window.anki_button.isEnabled())

    def test_export_completion_does_not_mark_a_new_lookup_saved(self):
        window = self.anki_window()
        window.show_entries([Entry("1", "cat", "", "Words", "ja", ("cat",))], "cat")
        gate = threading.Event()
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.add.side_effect = lambda _: (gate.wait(2), 123)[1]
            window.add_to_anki()
            window.show_entries([Entry("2", "dog", "", "Words", "ja", ("dog",))], "dog")
            gate.set()
            self.wait_until(lambda: window._anki_task is None)
        self.assertTrue(window.anki_button.isEnabled())
        self.assertEqual(window.anki_button.toolTip(), "Add to Anki")
        self.assertEqual(client.return_value.add.call_args.args[0]["expression"], "cat")

    def test_each_reading_exports_only_its_group_and_tracks_its_saved_note(self):
        window = self.anki_window()
        entries = (Entry("1", "same", "one", "Words", "ja", ("first reading",)),
                   Entry("2", "same", "two", "Words", "ja", ("second reading",)),
                   Entry("3", "same", "two", "Other", "ja", ("other dictionary",)))
        window.show_entries(entries, "same")
        self.app.processEvents()
        first = window._headword_rows[("same", "one")][1]
        second = window._headword_rows[("same", "two")][1]
        self.assertTrue(window.anki_button.isHidden())
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.add.side_effect = (123, 456)
            second.click()
            self.wait_until(lambda: window._anki_task is None)
            values = client.return_value.add.call_args.args[0]
            self.assertIn("second reading", values["glossary"])
            self.assertIn("other dictionary", values["glossary"])
            self.assertNotIn("first reading", values["glossary"])
            self.assertEqual(second.toolTip(), "Show in Anki")
            self.assertEqual(first.toolTip(), "Add to Anki")
            first.click()
            self.wait_until(lambda: window._anki_task is None)
            self.assertEqual(first.toolTip(), "Show in Anki")
            with patch("meikipop.anki.AnkiClient") as browser_client:
                second.click()
                self.wait_until(lambda: window._anki_browse_task is None)
                browser_client.return_value.call.assert_called_once_with("guiBrowse", query="nid:123")

    def test_save_error_is_visible_and_can_be_retried_explicitly(self):
        window = self.anki_window()
        window.show_entries([Entry("1", "cat", "", "Words", "ja", ("cat",))], "cat")
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.add.side_effect = ValueError("Open Anki.")
            window.anki_button.click()
            self.wait_until(lambda: window._anki_task is None)
            self.assertEqual(window.status.text(), "Open Anki.")
            self.assertTrue(window.anki_button.isEnabled())
            client.return_value.add.assert_called_once()
            client.return_value.add.side_effect = None
            client.return_value.add.return_value = 123
            window.anki_button.click()
            self.wait_until(lambda: window._anki_task is None)
        self.assertEqual(window.anki_button.toolTip(), "Show in Anki")
        self.assertEqual(client.return_value.add.call_count, 2)

    def test_export_includes_captured_pixels_translation_and_only_mapped_audio(self):
        from io import BytesIO
        from types import SimpleNamespace
        from PIL import Image
        from meikipop.utils.capture import CaptureRequest, PixelFrame
        request = CaptureRequest(1, "screen", (0, 0, 2, 2), (0, 0, 2, 2), 1, 1)
        snapshot = PixelFrame(request, (2, 2), bytes([255, 0, 0]) * 4, 10)
        entry = Entry("1", "cat", "", "Words", "en", ("cat",))
        clip = SimpleNamespace(key=("cat", ""), filename="cat.mp3", data=b"audio")
        options = AnkiSettings(True, fields={"Front": "expression", "Image": "picture",
                                            "Translation": "sentence_translation", "Audio": "word_audio"})
        with patch("meikipop.gui.anki.AnkiClient") as client:
            export_note([entry], "cat here", "", options, screenshot=snapshot,
                        translation="A <cat>", audio_clip=clip)
        values = client.return_value.add.call_args.args[0]
        self.assertEqual(values["sentence_translation"], "A &lt;cat&gt;")
        self.assertEqual(values["popup-selection-text"], "")
        media = values["_media"]
        self.assertEqual(Image.open(BytesIO(media["picture"]["data"])).getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(media["word_audio"]["data"], b"audio")
        with patch("meikipop.gui.anki.AnkiClient") as client:
            export_note([entry], "", "", AnkiSettings(True), screenshot=snapshot, audio_clip=clip)
        self.assertEqual(client.return_value.add.call_args.args[0]["_media"], {})

    def test_popup_exports_collapsed_kanji(self):
        window = self.anki_window({"Front": "expression", "Kanji": "kanji-details"})
        window.show_entries([Entry("1", "猫", "ねこ", "Words", "ja", ("cat",))], "猫",
                            kanji=(KanjiEntry("猫", meanings=("feline",)),))
        self.assertFalse(window._kanji_details)
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.add.return_value = 123
            window.anki_button.click()
            self.wait_until(lambda: window._anki_task is None)
        self.assertIn("feline", client.return_value.add.call_args.args[0]["kanji-details"])

    def test_export_kanji_uses_full_captured_data_in_word_order(self):
        from meikipop.anki import suggest_fields
        self.assertEqual(suggest_fields(["Kanji"]), {"Kanji": "kanji-details"})
        entry = Entry("1", "自転車", "じてんしゃ", "Words", "ja", ("bicycle",))
        kanji = (KanjiEntry("車", "Pack", meanings=("car",)),
                 KanjiEntry("自", "Pack", onyomi=("ジ",), kunyomi=("みずから",),
                            meanings=("self", "one", "two", "unabridged <meaning>"),
                            examples=({"w": "自分", "r": "じぶん", "m": "oneself"},)),
                 KanjiEntry("転", "Pack", meanings=("turn",),
                            components=({"c": "車", "m": "car <part>"},)),
                 KanjiEntry("自", "Second pack", meanings=("oneself",)),
                 KanjiEntry("猫", "Pack", meanings=("cat",)))
        options = AnkiSettings(True, fields={"Front": "expression", "Kanji": "kanji-details"})
        with patch("meikipop.gui.anki.AnkiClient") as client:
            export_note([entry], "", "", options, kanji=kanji)
            html = client.return_value.add.call_args.args[0]["kanji-details"]
            self.assertLess(html.index('>自</div>'), html.index('>転</div>'))
            self.assertLess(html.index('>転</div>'), html.index('>車</div>'))
            for content in ("ジ", "みずから", "unabridged &lt;meaning&gt;", "自分",
                            "じぶん", "car &lt;part&gt;", "Second pack"):
                self.assertIn(content, html)
            self.assertEqual(html.count('>自</div>'), 1)
            for content in ("猫", "href=", "font-family", "<meaning>"):
                self.assertNotIn(content, html)
            export_note([entry], "", "", options)
            self.assertEqual(client.return_value.add.call_args.args[0]["kanji-details"], "")
            export_note([entry], "", "", AnkiSettings(True), kanji=kanji)
            self.assertEqual(client.return_value.add.call_args.args[0]["kanji-details"], "")

    def test_export_glossary_compacts_semantic_tags_without_losing_card_content(self):
        def tag(text):
            return {"tag": "span", "data": {"class": "tag"}, "content": text}
        definition = {"type": "structured-content", "content": [
            tag("JMdict Sense #1"), tag("noun (common) (futsuumeishi)"), tag("adverb (fukushi)"),
            {"tag": "ol", "content": [{"tag": "li", "content": "cat <animal>"},
                                       {"tag": "li", "content": "shamisen"}]},
            {"tag": "div", "data": {"content": "extra-info"}, "content": "Usage explanation"},
            {"tag": "div", "data": {"content": "forms"}, "content": "Alternate form"},
            {"tag": "div", "data": {"content": "attribution"}, "content": "Dictionary credit"}]}
        entry = Entry("1", "cat", "", "JMdict", "ja", (definition,))
        options = AnkiSettings(True, fields={"Front": "expression", "Back": "glossary"})
        with patch("meikipop.gui.anki.AnkiClient") as client:
            export_note([entry], "", "", options)
        values = client.return_value.add.call_args.args[0]
        for field in ("glossary", "glossary-first"):
            glossary = values[field]
            for content in ("cat &lt;animal&gt;", "shamisen", "Usage explanation", "Alternate form", "Dictionary credit"):
                self.assertIn(content, glossary)
            self.assertIn('title="noun (common) (futsuumeishi)', glossary)
            self.assertNotIn("JMdict Sense", glossary)
            self.assertNotIn("meikipop-tag:", glossary)

    def test_field_suggestions_preserve_manual_skips_until_match_is_requested(self):
        panel = AnkiSettingsPanel(self.settings)
        self.widgets.append(panel)
        panel.load("ja")
        panel._set_fields(["word", "READING", "sentenceFurigana"], {"READING": ""})
        self.assertEqual(panel._field_controls["word"].currentData(), "expression")
        self.assertEqual(panel._field_controls["READING"].currentData(), "")
        panel.auto_map.click()
        self.assertEqual(panel._field_controls["READING"].currentData(), "reading")
        self.assertEqual(panel._field_controls["sentenceFurigana"].currentData(), "sentence_furigana")

    def test_popup_is_opt_in_and_old_results_cannot_be_exported(self):
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/target", "en")
        window = QuickLookupWindow(self.temp.name, FakeEngine, self.settings)
        self.widgets.append(window)
        self.assertTrue(window.anki_button.isHidden())
        window.show_entries([Entry("1", "猫", "ねこ", "Words", "ja", ("cat",))], "猫")
        self.settings.setValue("profiles/ja/anki/enabled", True)
        window.update_anki()
        self.assertTrue(window.anki_button.isEnabled())
        self.assertFalse(window.anki_button.isHidden())
        self.assertEqual(window.anki_button.text(), "")
        self.assertEqual(window.anki_button.accessibleName(), "Add to Anki")
        self.assertEqual(window.anki_button.toolTip(), "Add to Anki")
        self.assertFalse(window.anki_button.icon().isNull())
        self.assertEqual(window.anki_button.size(), window.copy_button.size())
        layout = window.audio_actions.layout()
        self.assertEqual(layout.indexOf(window.anki_button), 0)
        window._set_peek(True)
        self.assertFalse(window.anki_button.isVisible())
        window.pin.setChecked(True)
        self.assertTrue(window.anki_button.isVisible())
        with patch.object(window, "open_settings") as open_settings:
            from unittest.mock import Mock
            window._setup = Mock()
            window.anki_button.click()
            open_settings.assert_called_once()
            window._setup.show_anki.assert_called_once()
            window._setup = None
        window.search.setText("another word")
        window.debounce.stop()
        self.assertFalse(window.anki_button.isEnabled())
        window.add_to_anki()
        self.assertIsNone(window._anki_task)
