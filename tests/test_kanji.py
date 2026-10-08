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
                self.assertEqual(html.count(">決</a></td>"), 1)
                self.assertEqual(html.count(">定</a></td>"), 1)
                self.assertEqual(html.count('rowspan="2"'), 2)
                self.assertLess(html.index("agree"), html.index(">定</a></td>"))
                for value in ("First", "Second", "decide", "determine", "agree", "establish", "ケツ", "テイ"):
                    self.assertIn(value, html)

    def test_distinct_characters_use_a_compact_three_column_grid(self):
        entries = tuple(KanjiEntry(character, meanings=(f"meaning {character}",))
                        for character in "日本語")

        html = render_kanji(entries, compact_only=True)

        self.assertEqual(html.count('<td valign="top" width="33%"'), 3)
        self.assertEqual(html.count('style="font-size:30px'), 3)

        two_html = render_kanji(entries[:2], compact_only=True)
        self.assertEqual(two_html.count('<td valign="top" width="50%"'), 2)

    def test_clicking_a_character_shows_all_sources_in_a_full_width_section(self):
        entries = (KanjiEntry("日", "First", ("ニチ",), ("ひ",), ("day", "sun"), ("grade1",),
                            (("strokes", "4"),), ({"c": "一", "m": "one"},),
                            ({"w": "日本", "r": "にほん", "m": "Japan"},)),
                   KanjiEntry("日", "Second", ("ジツ",), ("か",), ("date",), ("jlptN5",),
                            (("grade", "1"),), (), ()))

        compact = render_kanji(entries, compact_only=True)
        self.assertIn('href="kanji:%E6%97%A5" title="Expand"', compact)
        self.assertNotIn("Strokes 4", compact)
        self.assertNotIn("Japan", compact)

        detailed = render_kanji(entries, compact_only=True, expanded_characters={"日"})
        self.assertIn('href="kanji:%E6%97%A5" title="Collapse"', detailed)
        for value in ("First", "Second", "day", "sun", "date", "ニチ", "ジツ", "ひ", "か",
                      "Strokes 4", "Grade 1", "grade1", "jlptN5", "one", "Japan"):
            self.assertIn(value, detailed)
        self.assertGreaterEqual(detailed.count('<table width="100%"'), 2)

    def test_character_links_url_encode_unicode(self):
        html = render_kanji((KanjiEntry("𠮷", meanings=("variant",)),), compact_only=True)

        self.assertIn('href="kanji:%F0%A0%AE%B7" title="Expand"', html)


if __name__ == "__main__":
    unittest.main()
