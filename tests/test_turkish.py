from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meikipop.dictionary.turkish_store import TurkishStore
from meikipop.dictionary.turkish_lookup import TurkishLookup
from meikipop.language.analyzer import ExactAnalyzer, Token, normalize
from meikipop.scripts.build_turkish_dictionary import build


class TurkishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.db"
        with closing(sqlite3.connect(self.source)) as db:
            db.executescript((Path(__file__).parent / "fixtures/turkish.sql").read_text(encoding="utf-8"))
        self.report = build(self.source, self.root / "pack")
        self.path = self.root / "pack/dictionary.sqlite3"
        self.store = TurkishStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_import_preserves_senses_labels_examples_homographs_and_relations(self):
        book = self.store.lookup("kitap")[0]
        self.assertEqual([s["order"] for s in book["senses"]], [1, 2])
        self.assertEqual(book["senses"][0]["labels"], ["isim", "mecaz"])
        self.assertEqual(book["senses"][0]["examples"][0]["author"], "Örnek Yazar")
        self.assertEqual(len(book["senses"][0]["examples"]), 2)
        self.assertEqual({r["related_id"] for r in book["relations"]}, {"tdk:6", "tdk:10"})
        self.assertEqual(len(self.store.lookup("yaz")), 2)
        self.assertEqual(self.report["omitted_entries"], 1)

    def test_turkish_case_and_verb_alias_requires_pos(self):
        self.assertEqual(normalize("IŞIK"), "ışık")
        self.assertEqual(normalize("I\u0307Z"), "iz")
        self.assertTrue(self.store.lookup("ışık"))
        self.assertFalse(self.store.lookup("işik"))
        self.assertEqual(self.store.lookup("yaz", "VERB")[0]["headword"], "yazmak")
        self.assertFalse(self.store.lookup("çak", "VERB"))

    def test_bad_source_checksum_leaves_existing_pack_untouched(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            build(self.source, self.path.parent, {"sha256": "wrong"})
        self.assertEqual(before, self.path.read_bytes())

    def test_exact_offsets_preserve_apostrophe_combining_marks_and_emoji(self):
        text = "📚 I\u0307Z Ankara’ya kitap"
        tokens = ExactAnalyzer().analyze(text)
        self.assertEqual([text[t.start:t.end] for t in tokens], ["I\u0307Z", "Ankara’ya", "kitap"])

    def test_missing_model_is_visible_exact_fallback(self):
        with patch("meikipop.language.stanza_analyzer.StanzaAnalyzer", side_effect=FileNotFoundError):
            lookup = TurkishLookup(self.store)
        result = lookup.lookup("kitap")
        self.assertIn("Exact fallback", result.status)
        self.assertEqual(result.entries[0]["headword"], "kitap")

    def test_inflected_verb_phrase_and_context_cache(self):
        class Analyzer:
            calls = 0
            def analyze(self, text):
                self.calls += 1
                return (Token(0,4,"fark","NOUN"), Token(5,9,"et","VERB"))
        lookup = TurkishLookup(self.store, "exact")
        lookup.analyzer = Analyzer()
        for target in (0, 1):
            result = lookup.lookup("fark etti", target)
            self.assertEqual(result.entries[0]["headword"], "fark etmek")
            match = next(m for m in result.matches if m.entry_id == result.entries[0]["id"])
            self.assertEqual((match.start, match.end, match.candidate), (0, 9, "fark et"))
            self.assertEqual(match.route, "phrase_lemma")
            from meikipop.gui.turkish.window import render_result
            self.assertIn("fark etmek", render_result(result))
            self.assertNotIn("→", render_result(result))
        self.assertEqual(lookup.analyzer.calls, 1)
        self.assertEqual(TurkishLookup(self.store, "exact").lookup("kitap kurdu").target, None)

    def test_casing_retry_keeps_original_analysis_and_context_offsets(self):
        from unittest.mock import Mock
        text = "📚 I\u0307Z KİTAPLAR"
        start = text.index("KİTAPLAR")
        original = (Token(2, 5, "iz", "NOUN"), Token(start, len(text), "wrong", "NOUN"))
        retried = (Token(2, 4, "iz", "NOUN"), Token(start - 1, len(text) - 1, "kitap", "NOUN"))
        lookup = TurkishLookup(self.store, "exact")
        lookup.analyzer = Mock()
        lookup.analyzer.analyze.side_effect = [original, retried]
        for _ in range(2):
            result = lookup.lookup(text, 1)
            self.assertEqual(result.tokens, original)
            self.assertEqual(result.entries[0]["headword"], "kitap")
            self.assertEqual(result.matches[0].route, "casing_lemma")
            self.assertEqual(text[result.matches[0].start:result.matches[0].end], "KİTAPLAR")
        self.assertEqual(lookup.analyzer.analyze.call_count, 2)
        self.assertEqual(lookup.analyzer.analyze.call_args.args, ("📚 iz kitaplar",))

    def test_casing_retry_requires_aligned_dictionary_match(self):
        from unittest.mock import Mock
        for retry in ((Token(0, 7, "kitap", "NOUN"),),
                      (Token(0, 8, "missing", "NOUN"),), RuntimeError("unavailable")):
            with self.subTest(retry=retry):
                lookup = TurkishLookup(self.store, "exact")
                lookup.analyzer = Mock()
                lookup.analyzer.analyze.side_effect = [(Token(0, 8, "wrong", "NOUN"),), retry]
                result = lookup.lookup("KİTAPLAR")
                self.assertFalse(result.entries)
                self.assertFalse(result.matches)

    def test_casing_retry_does_not_run_after_dictionary_hit(self):
        from unittest.mock import Mock
        lookup = TurkishLookup(self.store, "exact")
        lookup.analyzer = Mock()
        lookup.analyzer.analyze.return_value = (Token(0, 5, "wrong", "NOUN"),)
        result = lookup.lookup("KİTAP", 0)
        self.assertEqual(result.entries[0]["headword"], "kitap")
        lookup.analyzer.analyze.assert_called_once_with("KİTAP")

    def test_stanza_expansion_keeps_original_span(self):
        from types import SimpleNamespace as NS
        from meikipop.language.stanza_analyzer import StanzaAnalyzer
        analyzer = StanzaAnalyzer.__new__(StanzaAnalyzer)
        analyzer.pipeline = lambda _: NS(sentences=[NS(tokens=[NS(start_char=0, end_char=7,
            text="kitaptı", words=[NS(lemma="kitap", upos="NOUN"), NS(lemma="imek", upos="AUX")])])])
        self.assertEqual(analyzer.analyze("kitaptı"), (Token(0,7,"kitap","NOUN"),))
        self.assertEqual([w["lemma"] for w in analyzer.diagnostics("kitaptı")[0]["words"]],
                         ["kitap", "imek"])

    def test_cli_debug_is_optional_and_exact_mode_has_no_raw_stanza(self):
        import io
        import json
        from meikipop.scripts.turkish import main
        for debug in (False, True):
            output = io.StringIO()
            args = ["lookup-turkish", "cocuk", "--dictionary", str(self.path), "--analyzer", "exact"]
            with patch("sys.stdout", output):
                main(args + (["--debug"] if debug else []))
            data = json.loads(output.getvalue())
            self.assertEqual("attempts" in data, debug)
            self.assertEqual("analysis" in data, debug)
            if debug:
                self.assertIsNone(data["analysis"])
                self.assertTrue(data["attempts"])

    def test_cli_redirected_windows_output_is_utf8(self):
        import io
        import json
        from meikipop.scripts.turkish import main
        with io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as output:
            with patch("sys.stdout", output):
                main(["lookup-turkish", "IŞIK", "--dictionary", str(self.path),
                      "--analyzer", "exact"])
            output.flush()
            data = json.loads(output.buffer.getvalue().decode("utf-8"))
        self.assertEqual(data["text"], "IŞIK")
        self.assertEqual(data["entries"][0]["headword"], "IŞIK")

    def test_stanza_setup_and_offline_pipeline_share_charlm_configuration(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from meikipop.language.stanza_analyzer import StanzaAnalyzer, setup_models
        stanza = SimpleNamespace(__version__="1.14.0", download=Mock(), Pipeline=Mock())
        expected = {"tokenize": "imst", "mwt": "imst", "pos": "imst_charlm", "lemma": "imst_charlm"}
        with patch.dict("sys.modules", {"stanza": stanza}):
            setup_models(self.root)
            analyzer = StanzaAnalyzer(self.root)
        for call in (stanza.download.call_args, stanza.Pipeline.call_args):
            self.assertEqual(call.kwargs["processors"], expected)
            self.assertEqual(call.kwargs["resources_version"], "1.14.0")
            self.assertIsNone(call.kwargs["package"])
        self.assertIsNone(stanza.Pipeline.call_args.kwargs["download_method"])
        self.assertIn("lemma=imst_charlm", analyzer.identity)

    def test_html_escapes_source_and_examples_can_be_disabled(self):
        from meikipop.gui.turkish.window import render_result
        result = TurkishLookup(self.store, "exact").lookup("kitap")
        html = render_result(result)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("Örnek &amp; alıntı.", html)
        self.assertNotIn("Örnek &amp; alıntı.", render_result(result, examples=False))

    def test_recovery_preserves_source_and_validates_suggestions(self):
        lookup = TurkishLookup(self.store, "exact")
        for text, expected, route in (("cocuk", "çocuk", "diacritic"),
                                      ("cocugu", "çocuk", "diacritic_nominal"),
                                      ("benzerliği", "benzerlik", "nominal"),
                                      ("kitpa", "kitap", "edit")):
            with self.subTest(text=text):
                result = lookup.lookup(text, debug=True)
                self.assertFalse(result.entries)
                self.assertEqual(result.text, text)
                suggestion = next(s for s in result.suggestions if s.headword == expected)
                self.assertEqual(suggestion.route, route)
                self.assertEqual((suggestion.start, suggestion.end), (0, len(text)))
                self.assertTrue(self.store.lookup(suggestion.headword))
                self.assertTrue(any(not a["entry_ids"] for a in result.attempts))
        self.assertFalse(lookup.lookup("çocuk").suggestions)
        self.assertEqual(lookup.lookup("cocuk").attempts, ())
        result = lookup.lookup("kisi")
        self.assertTrue({"kişi", "kış"} <= {s.headword for s in result.suggestions})
        self.assertLess(next(s.cost for s in result.suggestions if s.headword == "kişi"), 4)

    def test_recovery_work_is_bounded_and_reanalysis_requires_alignment(self):
        from unittest.mock import Mock
        from meikipop.language.turkish_recovery import diacritic_candidates, edit_candidates
        self.assertLessEqual(len(diacritic_candidates("c" * 32)), 64)
        self.assertLessEqual(len(edit_candidates("c" * 32)), 256)
        self.assertEqual(diacritic_candidates("c" * 2000), ())
        lookup = TurkishLookup(self.store, "exact")
        lookup.analyzer = Mock()
        lookup.analyzer.analyze.side_effect = lambda text: (Token(0, len(text) - 1, "kitap", "NOUN"),)
        attempts = []
        def query(*args):
            attempts.append(args)
            return self.store.lookup(args[0], args[1])
        suggestions = lookup._suggest("c" * 32, Token(0, 32, "wrong", "NOUN"), query)
        self.assertLessEqual(lookup.analyzer.analyze.call_count, 8)
        self.assertLessEqual(len(attempts), 800)
        self.assertLessEqual(len(suggestions), 5)
        self.assertFalse(any(s.route == "diacritic_lemma" for s in suggestions))

    def test_corrected_inflection_is_analyzed_in_context(self):
        from unittest.mock import Mock
        lookup = TurkishLookup(self.store, "exact")
        lookup.analyzer = Mock()
        def analyze(text):
            if text == "bir çucu":
                return (Token(0, 3, "bir"), Token(4, 8, "çocuk", "NOUN"))
            return (Token(0, 3, "bir"), Token(4, 8, "missing", "NOUN"))
        lookup.analyzer.analyze.side_effect = analyze
        result = lookup.lookup("bir cucu", 1)
        suggestion = next(s for s in result.suggestions if s.headword == "çocuk")
        self.assertEqual(suggestion.route, "diacritic_lemma")
        self.assertEqual((suggestion.start, suggestion.end), (4, 8))

    def test_raw_diagnostics_keep_all_words_and_split_source_is_selectable_once(self):
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        from meikipop.language.stanza_analyzer import StanzaAnalyzer
        analyzer = StanzaAnalyzer.__new__(StanzaAnalyzer)
        words = [NS(text="cocug", lemma="cocug", upos="NOUN", feats="Case=Nom"),
                 NS(text="u", lemma="u", upos="INTJ", feats=None)]
        analyzer.pipeline = Mock(return_value=NS(sentences=[NS(tokens=[
            NS(text="cocug", start_char=0, end_char=5, words=words[:1])]), NS(tokens=[
            NS(text="u", start_char=5, end_char=6, words=words[1:])])]))
        self.assertEqual(analyzer.analyze("cocugu"), (Token(0, 6, "cocug", "NOUN"),))
        raw = analyzer.diagnostics("cocugu")
        self.assertEqual([t["text"] for t in raw], ["cocug", "u"])
        self.assertEqual(raw[0]["words"][0]["feats"], "Case=Nom")
        analyzer.pipeline.assert_called_once()


if __name__ == "__main__":
    unittest.main()
