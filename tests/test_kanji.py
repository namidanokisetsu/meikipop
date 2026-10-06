import unittest

from meikipop.dictionary.kanji import KanjiEntry, from_legacy, kanji_characters
from meikipop.gui.kanji_panel import render_kanji


class KanjiTests(unittest.TestCase):
    def test_characters_preserve_order_and_include_extensions(self):
        self.assertEqual(kanji_characters("日本語の日本𠮷"), ("日", "本", "語", "𠮷"))
        self.assertEqual(kanji_characters("日本語", 2), ("日", "本"))
        self.assertEqual(kanji_characters("日本語", 0), ())
        self.assertEqual(kanji_characters("ひらがなカタカナabc"), ())

    def test_legacy_adapter_keeps_components_and_examples(self):
        entry = from_legacy({"character": "語", "meanings": ["language"], "readings": ["ゴ", "かた.る"],
                             "components": [{"c": "言", "m": "speech"}],
                             "examples": [{"w": "日本語", "r": "にほんご", "m": "Japanese"}]})
        self.assertEqual(entry.onyomi, ("ゴ",))
        self.assertEqual(entry.kunyomi, ("かた.る",))
        self.assertEqual(entry.components[0]["c"], "言")
        self.assertEqual(entry.examples[0]["w"], "日本語")

    def test_compact_panel_keeps_details_separate(self):
        entry = KanjiEntry("猫", "Kanji Source", ("ビョウ",), ("ねこ",), ("cat",), stats=(("strokes", "11"),),
                           components=({"c": "田", "m": "field"},), examples=({"w": "子猫", "r": "こねこ", "m": "kitten"},))
        compact = render_kanji((entry,))
        self.assertIn("猫", compact)
        self.assertIn("ビョウ", compact)
        self.assertIn("ねこ", compact)
        self.assertIn("cat", compact)
        self.assertIn('href="kanji:toggle"', compact)
        self.assertNotIn("Strokes", compact)
        self.assertNotIn("kitten", compact)
        expanded = render_kanji((entry,), expanded=True)
        self.assertIn("Strokes 11", expanded)
        self.assertIn("kitten", expanded)
        self.assertIn("field", expanded)
        self.assertIn("Kanji Source", expanded)

    def test_untrusted_text_is_escaped_and_empty_panel_hidden(self):
        entry = KanjiEntry("<", 'bad"source', meanings=("<script>bad()</script>",),
                           stats=(("x", '<img src="https://example.test/">'),),
                           examples=({"w": "<b>bad</b>"},))
        html = render_kanji((entry,), expanded=True)
        self.assertNotIn("<script>", html)
        self.assertNotIn('<img src=', html)
        self.assertIn("&lt;script&gt;", html)
        self.assertEqual(render_kanji(()), "")

    def test_dictionary_entries_share_one_character_in_all_modes(self):
        entries = (KanjiEntry("決", "First", meanings=("decide",)),
                   KanjiEntry("定", "First", meanings=("determine",)),
                   KanjiEntry("決", "Second", onyomi=("ケツ",), meanings=("agree",)),
                   KanjiEntry("定", "Second", onyomi=("テイ",), meanings=("establish",)))
        for options in ({}, {"expanded": True}, {"compact_only": True}):
            with self.subTest(options=options):
                html = render_kanji(entries, **options)
                self.assertEqual(html.count(">決</td>"), 1)
                self.assertEqual(html.count(">定</td>"), 1)
                self.assertEqual(html.count('rowspan="2"'), 2)
                self.assertLess(html.index("agree"), html.index(">定</td>"))
                for value in ("First", "Second", "decide", "determine", "agree", "establish", "ケツ", "テイ"):
                    self.assertIn(value, html)


if __name__ == "__main__":
    unittest.main()
