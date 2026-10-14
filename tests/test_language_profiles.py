import sys
import subprocess
import unittest

from meikipop.language.profiles import get_profile


class LanguageProfileTests(unittest.TestCase):
    def test_profiles_only_appear_after_explicit_configuration(self):
        import tempfile
        from pathlib import Path
        from PyQt6.QtCore import QSettings
        from meikipop.language.profiles import configured_profiles
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            self.assertEqual(configured_profiles(settings), ())
            settings.setValue("profile", "ja")
            self.assertEqual(configured_profiles(settings), ())
            settings.setValue("profiles/ja/target", "en")
            self.assertEqual(configured_profiles(settings), ("ja",))
            settings.setValue("profiles/tr/target", "en")
            self.assertEqual(configured_profiles(settings), ("ja", "tr"))

    def test_lookup_keys_preserve_existing_pack_behavior(self):
        self.assertEqual(get_profile("tr").lookup_key("  IŞIK İSTANBUL’DA  "), "ışık istanbul'da")
        self.assertEqual(get_profile("tr").lookup_key("OĞLUMʼUN"), "oğlum'un")
        self.assertEqual(get_profile("ja").lookup_key(" ＡＢＣ ｶﾀｶﾅ "), "abc カタカナ")
        self.assertEqual(get_profile("de").lookup_key("Straße"), "straße")
        self.assertNotEqual(get_profile("tr").lookup_key("sık"), get_profile("tr").lookup_key("sik"))

    def test_source_spans_keep_combining_marks_and_apostrophes(self):
        text = "İstanbul’da oğlumʼun caf\u0065\u0301'si 3.5 5'te."
        spans = get_profile("tr").word_spans(text)
        self.assertEqual([text[start:end] for start, end in spans],
                         ["İstanbul’da", "oğlumʼun", "cafe\u0301'si", "3.5", "5'te"])
        self.assertTrue(all(text[start:end] for start, end in spans))

    def test_persian_joiners_keep_complete_words_and_original_source_offsets(self):
        text = "کتاب\u200cها می\u200cروم می\u200cنویسم"
        spans = get_profile("fa").word_spans(text)
        self.assertEqual(spans, ((0, 7), (8, 14), (15, 23)))
        self.assertEqual([text[start:end] for start, end in spans],
                         ["کتاب\u200cها", "می\u200cروم", "می\u200cنویسم"])
        sentence, start, end = get_profile("fa").sentence_span(text, 8, 14)
        self.assertEqual((sentence, start, end), (text, 8, 14))
        self.assertEqual(get_profile("fa").lookup_key(text[8:14]), "می\u200cروم")
        self.assertEqual(get_profile("fa").word_spans("\u200cکتاب\u200c"), ((1, 5),))

    def test_internal_joiners_preserve_indic_letter_clusters(self):
        for language, text in (("hi", "क्\u200dष"), ("bn", "ক্\u200cষ")):
            with self.subTest(language=language):
                self.assertEqual(get_profile(language).word_spans(text), ((0, len(text)),))

    def test_unspaced_profiles_retain_character_positions(self):
        text = "か\u3099本を読む。"
        spans = get_profile("ja").word_spans(text)
        self.assertEqual([text[start:end] for start, end in spans], ["か\u3099", "本", "を", "読", "む"])
        self.assertEqual(get_profile("zh-tw").word_mode, "unspaced")
        self.assertEqual(get_profile("cmn").word_mode, "unspaced")
        self.assertEqual(get_profile("ko").word_mode, "spaced")

    def test_mandarin_retains_native_character_positions_for_prefix_lookup(self):
        from meikipop.ocr.context import fragment_paragraphs, hit_paragraphs

        text = "学习中文。"
        fragments = [(char, (index * 20, 0, (index + 1) * 20, 20))
                     for index, char in enumerate(text)]
        paragraphs = fragment_paragraphs([(text, fragments)], 100, 20, "cmn")
        self.assertEqual([word.text for word in paragraphs[0].words], list("学习中文"))
        hit = hit_paragraphs(paragraphs, (.5, .5), "cmn")
        self.assertEqual((hit.query, hit.start, hit.end), ("中文。", 2, 3))
        self.assertEqual(hit.text[hit.start:hit.end], "中")

    def test_thai_cursor_prefix_keeps_combining_marks_at_the_source_position(self):
        from meikipop.ocr.context import fragment_paragraphs, hit_paragraphs

        text = "อ่านหนังสือ"
        spans = get_profile("th").word_spans(text)
        fragments = [(text[start:end], (index * 20, 0, (index + 1) * 20, 20))
                     for index, (start, end) in enumerate(spans)]
        paragraphs = fragment_paragraphs([(text, fragments)], len(spans) * 20, 20, "th")
        target = next(word for word in paragraphs[0].words if word.text == "นั")
        hit = hit_paragraphs(paragraphs, (target.box.center_x, target.box.center_y), "th")
        start = text.index("นั")
        self.assertEqual((hit.query, hit.start, hit.end), (text[start:], start, start + 2))
        self.assertEqual(hit.text[hit.start:hit.end], "นั")

    def test_japanese_combining_dakuten_stays_with_its_character_during_interpolation(self):
        from meikipop.ocr.context import hit_paragraphs
        from meikipop.ocr.interface import BoundingBox, Paragraph, Word

        text = "か\u3099本"
        word = Word(text, "", BoundingBox(.5, .5, 1, 1))
        paragraph = Paragraph(text, [word], word.box, False)
        hit = hit_paragraphs([paragraph], (.49, .5), "ja")
        self.assertEqual((hit.query, hit.start, hit.end), (text, 0, 2))

    def assert_sentence(self, language, text, word, expected):
        start = text.index(word)
        sentence, first, last = get_profile(language).sentence_span(text, start, start+len(word))
        self.assertEqual(sentence, expected)
        self.assertEqual(sentence[first:last], word)

    def test_turkish_title_and_decimal_are_not_sentence_breaks(self):
        text = "Önce bitti. Dr. Işık, Prof. Özgür ile 3.5 metreyi ölçtü. Sonra gitti."
        self.assert_sentence("tr", text, "Özgür", "Dr. Işık, Prof. Özgür ile 3.5 metreyi ölçtü.")
        self.assert_sentence("tr", text, "gitti", "Sonra gitti.")

    def test_japanese_quoted_sentence_preserves_closer(self):
        self.assert_sentence("ja", '前です。「猫が好きです！」次です。', "猫", '「猫が好きです！」')

    def test_generic_english_initials_and_closers(self):
        text = 'First. Mr. A. Smith said “Hello!” Last.'
        self.assert_sentence("en", text, "Smith", 'Mr. A. Smith said “Hello!”')

    def test_blank_lines_and_truncated_ocr_keep_exact_text(self):
        self.assert_sentence("tr", "eski paragraf\n\n  çünkü oğlum bugün", "oğlum", "çünkü oğlum bugün")
        self.assertEqual(get_profile("ja").sentence_span("", 999), ("", 0, 0))
        self.assertEqual(get_profile("en").sentence_span("   ", 1), ("", 0, 0))

    def test_unknown_script_fallback_and_no_model_imports(self):
        profile = get_profile("zz")
        text = "café Привет مرحبا"
        self.assertEqual([text[a:b] for a,b in profile.word_spans(text)], ["café", "Привет", "مرحبا"])
        self.assertEqual(profile.lookup_key("CAFÉ"), "café")
        self.assertIs(get_profile("zz"), profile)
        check = subprocess.run([sys.executable, "-c", "import sys; from meikipop.language.profiles import get_profile; get_profile('tr'); assert not {'spacy', 'zeyrek', 'stanza'} & sys.modules.keys()"], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)


if __name__ == "__main__":
    unittest.main()
