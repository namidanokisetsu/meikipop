import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from meikipop.dictionary.library import import_yomitan
from meikipop.dictionary.search import SearchEngine
from meikipop.language.analyzer import Token
from meikipop.language.stanza_analyzer import StanzaAnalyzer, setup_models


class MorphologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = SearchEngine(self.root / "library")

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def pack(self, language, rows):
        archive = self.root / (language + ".zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("index.json", json.dumps(dict(title=language, format=3, sourceLanguage=language)))
            zf.writestr("term_bank_1.json", json.dumps([[term, "", "", rules, 0, definitions, -1, ""]
                                                      for term, definitions, rules in rows]))
        import_yomitan(archive, self.root / "library")
        self.engine.refresh()

    def test_off_exact_and_imported_forms_never_initialize_models(self):
        self.pack("tr", [("kitap", ["book"], ""), ("kitaplar", [["kitap", ["plural"]]], "")])
        with patch("meikipop.language.stanza_analyzer.StanzaAnalyzer") as factory:
            self.engine.search("kitaplarımdan", source="tr")
            self.assertEqual(self.engine.search("kitap", source="tr", morphology=True).entries[0].term, "kitap")
            self.assertEqual(self.engine.search("kitaplar", source="tr", morphology=True).entries[0].route, "form")
            factory.assert_not_called()

    def test_context_span_preserves_original_text_and_bounds_lemma_lookup(self):
        self.pack("tr", [("kitap", ["book"], ""), ("okumak", ["read"], "")])
        analyzer = Mock()
        analyzer.analyze.return_value = (Token(0, 3, "dün"), Token(4, 17, "kitap"), Token(18, 24, "okumak"))
        self.engine._analyzer = ("tr", analyzer)
        text = "Dün kitaplarımdan okudum."
        result = self.engine.search("kitaplarımdan", source="tr", morphology=True, context=(text, 4, 17))
        self.assertEqual([e.term for e in result.entries], ["kitap"])
        self.assertEqual(result.entries[0].route, "lemma")
        self.assertEqual(result.text, "kitaplarımdan")
        analyzer.analyze.assert_called_once_with(text)
        self.engine.search("kitaplarımdan", source="tr", morphology=True, context=(text, 4, 17))
        analyzer.analyze.assert_called_once()

    def test_automatic_detection_can_recover_a_profile_language_lemma(self):
        self.pack("de", [("laufen", ["run"], "")])
        analyzer = Mock()
        analyzer.analyze.return_value = (Token(0, 4, "laufen"),)
        self.engine._analyzer = ("de", analyzer)
        result = self.engine.search("lief", foreign="de", pair=("de", "en"), morphology=True)
        self.assertEqual((result.source, result.target), ("de", "en"))
        self.assertEqual(result.entries[0].term, "laufen")

    def test_japanese_keeps_rule_based_deconjugation_with_option_enabled(self):
        self.pack("ja", [("食べる", ["eat"], "v1")])
        with patch("meikipop.language.stanza_analyzer.StanzaAnalyzer") as factory:
            self.assertEqual(self.engine.search("食べました", source="ja", morphology=True).entries[0].term, "食べる")
            factory.assert_not_called()

    def test_missing_models_are_retryable_after_refresh_without_download(self):
        self.pack("tr", [("kitap", ["book"], "")])
        with patch("meikipop.language.stanza_analyzer.default_model_dir", return_value=self.root), \
                patch("meikipop.language.stanza_analyzer.StanzaAnalyzer") as factory:
            with self.assertRaisesRegex(RuntimeError, "Lemma fallback unavailable"):
                self.engine.search("kitaplarımdan", source="tr", morphology=True)
            factory.assert_not_called()
            self.assertTrue(self.engine.search("kitap", source="tr", morphology=True).entries)
            (self.root / "resources.json").write_text("{}")
            factory.return_value.analyze.return_value = (Token(0, 13, "kitap"),)
            self.engine.refresh()
            self.assertTrue(self.engine.search("kitaplarımdan", source="tr", morphology=True).entries)

    def test_shared_stanza_setup_keeps_downloads_explicit(self):
        stanza = SimpleNamespace(__version__="1.14.0", download=Mock(), Pipeline=Mock())
        with patch.dict("sys.modules", {"stanza": stanza}):
            setup_models(self.root, language="de")
            StanzaAnalyzer(self.root, language="de")
        self.assertEqual(stanza.download.call_args.args, ("de",))
        self.assertEqual(stanza.Pipeline.call_args.args, ("de",))
        self.assertEqual(stanza.Pipeline.call_args.kwargs["processors"], "tokenize,pos,lemma")
        self.assertIsNone(stanza.Pipeline.call_args.kwargs["download_method"])
