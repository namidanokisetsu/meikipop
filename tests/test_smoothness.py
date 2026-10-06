import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest.mock import Mock, patch
from test_quick_lookup import QuickLookupTests, entry
from meikipop.dictionary.search import SearchResult


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
