from collections import OrderedDict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from meikipop.dictionary.library import import_yomitan
from meikipop.dictionary.search import SearchEngine
from meikipop.language.analyzer import Token
from meikipop.language.turkish_analyzer import TrAnalysis, TrMorpheme, TurkishAnalyzer, grammar_labels


class TurkishCandidateTests(unittest.TestCase):
    def test_background_preparation_is_shared_by_lookup_workers(self):
        from meikipop.language import turkish_analyzer as module
        entered, release = threading.Event(), threading.Event()
        engine = Mock()
        engine.analyse.return_value = ()
        main_thread = threading.get_ident()
        threads = []
        def load(future):
            threads.append(threading.get_ident())
            entered.set()
            release.wait(3)
            future.set_result(engine)
        with patch.object(module, '_engine_future', None), patch.object(module, '_load_engine', side_effect=load), \
                patch.object(module, 'available', return_value=True):
            try:
                future = module.warmup()
                self.assertTrue(entered.wait(3))
                self.assertFalse(future.done())
                self.assertIs(module.warmup(), future)
            finally:
                release.set()
            future.result(timeout=3)
            first, second = TurkishAnalyzer(), TurkishAnalyzer()
            first.candidates('cevrimizi', 0, 9)
            second.candidates('cevrimizi', 0, 9)
            self.assertIs(first.engine, second.engine)
            self.assertNotEqual(threads, [main_thread])

    def setUp(self):
        self.analyzer = TurkishAnalyzer.__new__(TurkishAnalyzer)
        self.analyzer.engine = Mock()
        self.analyzer._words = OrderedDict()
        self.readings = {}
        self.analyzer.engine.analyse.side_effect = lambda word: self.readings.get(word, ())

    def candidates(self, text, word):
        start = text.index(word)
        return self.analyzer.candidates(text, start, start + len(word))

    def test_alternatives_and_source_spans_are_preserved(self):
        self.readings['Kırkların'] = (TrAnalysis('kırklar', 'NOUN'), TrAnalysis('kırk', 'NUM'))
        self.assertEqual(self.candidates('Kırkların ceminde', 'Kırkların'), self.readings['Kırkların'])
        self.assertEqual(self.candidates('Kırkların ceminde', 'Kırk'), ())
        self.assertEqual(self.candidates('Kırkların ceminde', 'Kırkların ceminde'), ())
        self.candidates('Kırkların ceminde', 'Kırkların')
        self.assertEqual(self.analyzer.engine.analyse.call_count, 2)

    def test_proper_apostrophes_do_not_require_a_lexicon_entry(self):
        for word in ["İstanbul'da", 'İstanbul’da', 'İstanbulʼda']:
            with self.subTest(word=word):
                self.assertEqual(self.candidates(word, word), (TrAnalysis('İstanbul', 'PROPN', 'Prop'),))
        self.assertEqual(self.analyzer.engine.analyse.call_count, 3)

    def test_proper_names_retain_available_suffix_paths(self):
        name = TrAnalysis('İstanbul', 'PROPN', 'Prop', paths=((TrMorpheme('Noun', 'istanbul', 'Noun'),
                          TrMorpheme('Loc', 'da', 'Locative')),))
        self.readings["İstanbul'da"] = (name, TrAnalysis('istanbul', 'NOUN'))
        self.assertEqual(self.candidates("İstanbul'da", "İstanbul'da"), (name,))

    def test_name_context_prefers_name_without_discarding_other_readings(self):
        common, name = TrAnalysis('sel', 'NOUN'), TrAnalysis('Selin', 'PROPN', 'Prop')
        self.readings['Selin'] = (common, name)
        self.assertEqual(self.candidates('Merhaba Selin', 'Selin'), (name, common))
        self.assertEqual(self.candidates('Selin nerede?', 'Selin'), (common, name))

    def test_imperatives_and_aorist_requests_use_context(self):
        meat, imperative = TrAnalysis('et', 'NOUN'), TrAnalysis('etmek', 'VERB', imperative=True)
        self.readings['et'] = (meat, imperative)
        self.assertEqual(self.candidates('Yardım et!', 'et'), (imperative, meat))
        self.readings['bir'] = (TrAnalysis('bir', 'DET'),)
        self.assertEqual(self.candidates('bir et!', 'et'), (meat, imperative))
        noun, verb = TrAnalysis('bekler', 'NOUN'), TrAnalysis('beklemek', 'VERB', aorist=True)
        self.readings.update(bekler=(noun, verb), misin=(TrAnalysis('mi', 'PART'),))
        self.assertEqual(self.candidates('Beni bekler misin?', 'bekler'), (verb, noun))

    def test_unknown_names_and_oversized_words_do_not_get_invented_roots(self):
        self.assertEqual(self.candidates('mestanelikte', 'mestanelikte'), ())
        word = 'a' * 65
        self.assertEqual(self.candidates(word, word), ())
        self.analyzer.engine.analyse.assert_called_once_with('mestanelikte')

    def test_imports_and_readiness_do_not_load_nlp(self):
        check = subprocess.run([sys.executable, '-c',
            "import sys; from meikipop.language.morphology import model_available; "
            "model_available('tr'); model_available('ja'); "
            "assert not {'stanza', 'torch', 'zeyrek', 'nltk'} & sys.modules.keys()"], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)


class TurkishLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        archive = root / 'tr.zip'
        rows = [(word, [word]) for word in ['pervane', 'divane', 'kırk', 'kırklar', 'mestanelik', 'Sıtkı', 'sıdk', 'gelmek']]
        rows += [('kırk', [['kırkmak', ['imperative']]]), ('kırkmak', ['shear'])]
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('index.json', json.dumps(dict(title='fixture', format=3, sourceLanguage='tr')))
            bundle.writestr('term_bank_1.json', json.dumps([[word, '', '', '', 0, definitions, -1, ''] for word, definitions in rows]))
        import_yomitan(archive, root / 'library')
        self.engine = SearchEngine(root / 'library')
        self.addCleanup(self.engine.close)
        self.analyzer = Mock()
        self.analyzer.candidates.return_value = ()
        self.engine._turkish_analyzer = self.analyzer
        ready = patch('meikipop.language.turkish_analyzer.available', return_value=True)
        ready.start()
        self.addCleanup(ready.stop)
        stanza = patch('meikipop.language.stanza_analyzer.model_status', return_value='Model needed')
        self.stanza_status = stanza.start()
        self.addCleanup(stanza.stop)

    def search(self, text, **kwargs):
        return self.engine.search(text, source='tr', morphology=True, **kwargs)

    def test_dictionary_supported_alternatives_keep_analyzer_order(self):
        self.analyzer.candidates.return_value = (TrAnalysis('kırklar', 'NOUN'), TrAnalysis('kırk', 'NUM'))
        result = self.search('Kırkların')
        self.assertEqual([e.term for e in result.entries], ['kırklar', 'kırk'])
        self.assertTrue(all(e.route == 'morphology' for e in result.entries))

    def test_missing_definition_keeps_lemma_and_grammar_without_a_false_entry(self):
        reading = TrAnalysis('cevir', 'NOUN', paths=((TrMorpheme('Noun', 'cevr', 'Noun'),
                            TrMorpheme('P1pl', 'imiz', 'FirstPersonPluralPossessive'),
                            TrMorpheme('Acc', 'i', 'Accusative')),))
        self.analyzer.candidates.return_value = (reading,)
        result = self.search('cevrimizi')
        self.assertEqual(result.entries, ())
        self.assertEqual(result.analyses, (reading,))
        from meikipop.gui.quick_lookup import render_result
        html = render_result(result)
        for text in ('cevir', '-imiz (our)', '-i (accusative)', 'No dictionary entry.'):
            self.assertIn(text, html)
        self.assertNotIn('-imiz (our)', render_result(result, grammar=False))

    def test_detected_turkish_miss_keeps_suggestions_in_turkish(self):
        self.analyzer.candidates.return_value = (TrAnalysis('cevir', 'NOUN'),)
        with patch.object(self.engine.library, 'suggest', return_value=()) as suggest:
            result = self.engine.search('cevrimizi', foreign='tr', pair=('tr', 'en'), morphology=True)
        self.assertEqual(result.source, 'tr')
        suggest.assert_called_once_with('cevrimizi', 'tr')

    def test_missing_first_lemma_does_not_hide_attested_alternative(self):
        self.analyzer.candidates.return_value = (TrAnalysis('missing', 'NOUN'), TrAnalysis('pervane', 'NOUN'),
                                                 TrAnalysis('pervane', 'ADJ'))
        line = 'On dört bin yıl gezdim pervanelikte'
        start = line.index('pervanelikte')
        result = self.search('pervanelikte', context=(line, start, len(line)))
        self.assertEqual([e.term for e in result.entries], ['pervane'])
        self.analyzer.candidates.assert_called_once_with(line, start, len(line))
        self.assertEqual(result.text, 'pervanelikte')

    def test_missing_words_never_load_stanza_even_when_installed(self):
        stanza = Mock()
        stanza.analyze.return_value = (Token(0, 12, 'mestanelik', 'NOUN'),)
        self.engine._analyzer = ('tr', stanza)
        self.assertEqual(self.search('mestanelikte').entries, ())
        stanza.analyze.assert_not_called()
        self.stanza_status.return_value = 'Installed'
        self.engine.refresh()
        self.assertEqual(self.search('mestanelikte').entries, ())
        stanza.analyze.assert_not_called()
        self.stanza_status.assert_not_called()

    def test_analyzer_failure_does_not_start_a_second_engine(self):
        self.stanza_status.return_value = 'Installed'
        self.analyzer.candidates.side_effect = RuntimeError('fixture failure')
        with patch('meikipop.language.stanza_analyzer.StanzaAnalyzer') as stanza:
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                self.search('mestanelikte')
            stanza.assert_not_called()

    def test_turkish_readiness_does_not_depend_on_old_stanza_models(self):
        from meikipop.language.morphology import model_available
        with patch('meikipop.language.turkish_analyzer.available', return_value=False):
            self.assertFalse(model_available('tr'))
        self.assertTrue(model_available('tr'))
        self.stanza_status.assert_not_called()

    def test_successful_morphology_does_not_call_stanza(self):
        self.stanza_status.return_value = 'Installed'
        self.analyzer.candidates.return_value = (TrAnalysis('divane', 'ADJ'),)
        with patch('meikipop.language.stanza_analyzer.StanzaAnalyzer') as stanza:
            self.assertEqual(self.search('divanelikte').entries[0].term, 'divane')
            stanza.assert_not_called()

    def test_exact_entries_and_disabled_morphology_skip_analyzers(self):
        self.assertEqual(self.search('Sıtkı').entries[0].term, 'Sıtkı')
        self.engine.search('divanelikte', source='tr')
        self.analyzer.candidates.assert_not_called()

    def test_mismatched_context_cannot_lookup_another_word(self):
        self.analyzer.candidates.return_value = (TrAnalysis('divane', 'ADJ'),)
        self.assertEqual(self.search('divanelikte', context=('pervanelikte', 0, 12)).entries, ())
        self.analyzer.candidates.assert_not_called()

    def test_popup_retains_derivation_and_case_from_every_reading(self):
        path = (TrMorpheme('Adj', 'pervane', 'Adjective'), TrMorpheme('Ness', 'lik', 'Ness', True),
                TrMorpheme('Noun', '', 'Noun'), TrMorpheme('A3sg', '', 'ThirdPersonSingular'),
                TrMorpheme('Pnon', '', 'NoPosession'), TrMorpheme('Loc', 'te', 'Locative'))
        readings = (TrAnalysis('pervane', 'ADJ', paths=(path,)),
                    TrAnalysis('pervane', 'NOUN', paths=(path,)))
        self.analyzer.candidates.return_value = readings
        result = self.search('pervanelikte')
        entry = result.entries[0]
        self.assertEqual(entry.morphology, readings)
        self.assertEqual(entry.inflection, ('-lik (noun derivation) · -te (locative)',))
        from meikipop.gui.quick_lookup import render_result
        html = render_result(result)
        self.assertIn('-lik (noun derivation)', html)
        self.assertIn('-te (locative)', html)
        self.assertNotIn('-te (locative)', render_result(result, grammar=False))

    def test_ambiguous_paths_stay_alternatives_instead_of_a_combined_claim(self):
        root = TrMorpheme('Noun', 'pervane', 'Noun')
        paths = ((root, TrMorpheme('P2sg', 'n', 'SecondPersonSingularPossessive')),
                 (root, TrMorpheme('Gen', 'nin', 'Genitive')))
        readings = (TrAnalysis('pervane', 'NOUN', paths=paths),)
        self.analyzer.candidates.return_value = readings
        entry = self.search('pervanenin').entries[0]
        self.assertEqual(entry.morphology[0].paths, paths)
        self.assertEqual(grammar_labels(readings), ('-n (your) OR -nin (genitive)',))
