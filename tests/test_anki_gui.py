import os
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
from meikipop.gui.anki import AnkiSettingsPanel, AnkiExportDialog
from meikipop.gui.quick_lookup import QuickLookupWindow
from test_quick_lookup import FakeEngine


class AnkiGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.widgets = []

    def tearDown(self):
        for widget in reversed(self.widgets):
            if isinstance(widget, QuickLookupWindow):
                widget.shutdown()
                widget.worker._thread.join(2)
            task = getattr(widget, "_task", None)
            if task:
                task.thread.join(2)
            widget.hide()
            widget.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.settings.clear()
        self.settings.sync()
        self.temp.cleanup()

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
        self.assertFalse(panel.shortcut.enabled.isChecked())
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

    def test_export_snapshots_context_and_selection_and_prevents_double_submission(self):
        entry = Entry("1", "猫", "ねこ", "Words", "ja", ("cat",))
        options = AnkiSettings(True, deck="Japanese", model="Basic", fields={"Front": "expression", "Back": "glossary"})
        dialog = AnkiExportDialog([entry], "猫がいる。", "chosen sense", options)
        self.widgets.append(dialog)
        self.assertEqual(dialog.definition.toPlainText(), "chosen sense")
        calls, threads = [], []
        with patch("meikipop.gui.anki.AnkiClient") as client:
            def add(values):
                calls.append(values)
                threads.append(threading.get_ident())
                return 123
            client.return_value.add.side_effect = add
            dialog.submit()
            dialog.submit()
            self.wait_until(lambda: dialog._saved)
            dialog.submit()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["sentence"], "猫がいる。")
        self.assertIn("chosen sense", calls[0]["glossary"])
        self.assertNotEqual(threads[0], threading.get_ident())

    def test_export_includes_captured_pixels_and_editable_translation(self):
        from io import BytesIO
        from PIL import Image
        from meikipop.utils.capture import CaptureRequest, PixelFrame
        request = CaptureRequest(1, "screen", (0, 0, 2, 2), (0, 0, 2, 2), 1, 1)
        snapshot = PixelFrame(request, (2, 2), bytes([255, 0, 0]) * 4, 10)
        entry = Entry("1", "cat", "", "Words", "en", ("cat",))
        options = AnkiSettings(True, fields={"Front": "expression", "Image": "picture", "Translation": "sentence_translation"})
        dialog = AnkiExportDialog([entry], "cat here", "", options, screenshot=snapshot, translation="initial")
        self.widgets.append(dialog)
        dialog.translation.setPlainText("edited <translation>")
        with patch("meikipop.gui.anki.AnkiClient") as client:
            client.return_value.add.return_value = 123
            dialog.submit()
            self.wait_until(lambda: dialog._saved)
        values = client.return_value.add.call_args.args[0]
        self.assertEqual(values["sentence_translation"], "edited &lt;translation&gt;")
        media = values["_media"]["picture"]
        self.assertEqual(Image.open(BytesIO(media["data"])).getpixel((0, 0)), (255, 0, 0))

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
        layout = window.actions_row.layout()
        self.assertEqual(layout.indexOf(window.anki_button), 2)
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
        self.assertIsNone(window._anki_dialog)
