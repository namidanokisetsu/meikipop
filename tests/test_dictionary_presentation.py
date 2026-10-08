import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtGui import QTextFormat
from PyQt6.QtWidgets import QApplication

from meikipop.dictionary.library import Entry
from meikipop.dictionary.search import SearchResult
from meikipop.gui.quick_lookup import LocalDictionaryBrowser, render_result


def result(definitions, source="Fixture"):
    return SearchResult("word", "ja", "en", (
        Entry("fixture", "word", "", source, "ja", tuple(definitions)),))


class DictionaryPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser(selection_lookup=False)
        self.browser.resize(480, 230)
        self.browser.show()

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()

    def render(self, value, **kwargs):
        self.browser.setHtml(render_result(value, **kwargs))
        self.app.processEvents()
        return self.browser.toPlainText()

    def test_bunpro_preview_keeps_meaning_and_expansion_separates_sections(self):
        definition = {"type": "structured-content", "content": [
            "【 Meaning 】", {"tag": "div", "content": "Persistently"},
            "【 Explanation 】", {"tag": "div", "content": "Explanation body " * 30},
            "【 Example sentences 】", {"tag": "ol", "content": [
                {"tag": "li", "content": "Example one"}]}]}
        footer = {"type": "structured-content", "content": [
            {"tag": "a", "href": "https://example.test", "content": "Link to Bunpro"}]}
        value = result((definition, footer), "Bunpro Dictionary")
        text = self.render(value, preview=True)
        self.assertIn("Persistently", text)
        self.assertNotIn("Explanation", text)
        self.assertNotIn("Example one", text)
        self.assertNotIn("Link to Bunpro", text)
        self.assertNotIn("<ol>", render_result(value, preview=True))
        text = self.render(value, expanded=("Bunpro Dictionary",))
        self.assertIn("Persistently\nExplanation\nExplanation body", text)
        self.assertIn("Example sentences\n", text)
        self.assertIn("Example one", text)
        self.assertIn("Link to Bunpro", text)
        self.assertEqual(definition["content"][0], "【 Meaning 】")

    def test_grammar_preview_selects_meaning_and_expansion_preserves_examples(self):
        source = "日本語文法辞典(全集)"
        value = result(("文法項目 | という | 基本\n [解説]\n Explanation\n\n [意味]\n Called\n\n"
                        " [例文A]\n Japanese example\n English example",), source)
        self.assertIn("Called", self.render(value, preview=True))
        self.assertNotIn("Explanation", self.browser.toPlainText())
        text = self.render(value, expanded=(source,))
        self.assertIn("基本", text)
        self.assertIn("Japanese example", text)
        self.assertIn("English example", text)
        self.assertNotIn("\n\n\n", text)

    def test_forms_are_supplements_not_numbered_senses(self):
        for kind in ("forms", "formsTable", "forms-list"):
            with self.subTest(kind=kind):
                value = result(("Meaning", {"type": "structured-content", "content": {
                    "tag": "div", "data": {"content": kind}, "content": "Alternative spelling"}}))
                self.assertNotIn("Alternative spelling", self.render(value, preview=True))
                html = render_result(value, expanded=("Fixture",))
                self.assertNotIn("<ol>", html)
                self.assertIn("Forms", html)
                self.assertIn("Alternative spelling", self.render(value, expanded=("Fixture",)))

    def test_jitendex_tags_share_first_meaning_line_and_forms_label_is_not_repeated(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "div", "data": {"content": "sense-group"}, "content": [
                {"tag": "span", "data": {"class": "tag", "content": "part-of-speech-info"},
                 "content": "noun"},
                {"tag": "div", "data": {"content": "sense"}, "content": [
                    {"tag": "ul", "data": {"content": "glossary"},
                     "content": {"tag": "li", "content": "Tokyo"}},
                    {"tag": "div", "content": "Example sentence"}]},
                {"tag": "div", "data": {"content": "sense"}, "content": "Second meaning"}]},
            {"tag": "div", "data": {"content": "forms"}, "content": [
                {"tag": "span", "data": {"class": "tag", "content": "forms-label"},
                 "content": "forms"},
                {"tag": "table", "content": {"tag": "tr", "content": [
                    {"tag": "td", "content": "東京"}, {"tag": "td", "content": "東亰"}]}}]}]}
        text = self.render(result((definition,)), expanded=("Fixture",))
        self.assertIn("[noun] Tokyo\nExample sentence\nSecond meaning", text)
        self.assertEqual(text.lower().count("forms"), 1)
        self.assertIn("東亰", text)
        self.assertEqual(definition["content"][0]["content"][1]["tag"], "div")

    def test_semantic_meanings_collapse_without_discarding_full_content(self):
        value = result(({"type": "structured-content", "content": {"tag": "div", "content": [
            {"tag": "div", "data": {"meaning": ""}, "content": f"Sense {i}"}
            for i in range(1, 7)]}},))
        text = self.render(value)
        self.assertIn("Sense 2", text)
        self.assertNotIn("Sense 3", text)
        self.assertIn("Sense 6", self.render(value, expanded=("Fixture",)))

    def test_unstructured_japanese_preview_is_bounded(self):
        value = result(("長い意味" * 200,))
        text = self.render(value, preview=True)
        self.assertLess(len(text), 270)
        self.assertIn("…", text)
        self.assertIn("長い意味" * 200, self.render(value, expanded=("Fixture",)))

    def test_other_readings_are_reachable_without_initial_wall_of_entries(self):
        value = SearchResult("生", "ja", "en", tuple(
            Entry(str(i), "生", reading, "Fixture", "ja", (f"Meaning {i}",))
            for i, reading in enumerate(("なま", "せい", "しょう", "き", "いき"))))
        text = self.render(value)
        self.assertIn("Meaning 0", text)
        self.assertNotIn("Meaning 4", text)
        self.assertIn("Other readings (4)", text)
        self.assertIn("Meaning 4", self.render(value, details_expanded=("readings",)))

    def test_headword_does_not_keep_qt_relative_font_enlargement(self):
        self.render(result(("Meaning",)))
        block = self.browser.document().begin()
        self.assertFalse(block.charFormat().hasProperty(QTextFormat.Property.FontSizeAdjustment))
        self.assertFalse(block.begin().fragment().charFormat().hasProperty(QTextFormat.Property.FontSizeAdjustment))

    def test_missing_entry_shows_nonempty_scanned_text_safely(self):
        for message in ("", "No entry found."):
            with self.subTest(message=message):
                value = SearchResult("未登録 <word>\n次の行", "ja", "en", (), message=message)
                text = self.render(value, show_source=False)
                self.assertIn("未登録 <word>\n次の行", text.replace("\u2028", "\n"))
                self.assertNotIn("No entry found", text)
        text = self.render(SearchResult("", "ja", "en", ()))
        self.assertEqual(text.strip(), "")


if __name__ == "__main__":
    unittest.main()
