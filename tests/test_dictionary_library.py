import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile

from meikipop.dictionary.library import Library, folded, import_yomitan, remove_dictionary, save_preferences
from meikipop.dictionary.search import SearchEngine


class LibraryTests(unittest.TestCase):
    def test_english_profile_looks_up_entries_instead_of_reverse_glosses(self):
        self.pack("English", [self.row("cat", ["a feline animal"])], language="en")
        engine = SearchEngine(self.directory)
        try:
            result = engine.search("cat", source="en", foreign="en", pair=("en", "ja"))
            self.assertEqual([entry.term for entry in result.entries], ["cat"])
            self.assertFalse(engine.search("feline", source="en", foreign="en", pair=("en", "ja")).entries)
        finally:
            engine.close()

    def test_remove_dictionary_releases_readers_and_does_not_restore_old_revision(self):
        self.pack("Words", [self.row("eski", ["old"])], revision="1")
        current = self.pack("Words", [self.row("yeni", ["new"])], revision="2")
        other = self.pack("Keep", [self.row("ev", ["house"])])
        self.library = Library(self.directory)
        remove_dictionary(self.directory, current.name, self.library.refresh, threading.Event())
        self.assertEqual(list(self.directory.glob("*.sqlite3")), [other])
        self.assertEqual([meta["title"] for _, meta, _ in self.library.packs], ["Keep"])
        with self.assertRaises(ValueError):
            remove_dictionary(self.directory, "../outside.sqlite3", self.library.refresh, threading.Event())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / "library"
        self.library = None

    def tearDown(self):
        if self.library:
            self.library.close()
        self.temp.cleanup()

    def pack(self, name, rows, language="tr", revision="1"):
        archive = self.root / (name + revision + ".zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("index.json", json.dumps(dict(title=name, format=3, sourceLanguage=language, revision=revision)))
            zf.writestr("term_bank_1.json", json.dumps(rows))
        return import_yomitan(archive, self.directory)

    @staticmethod
    def row(term, definitions, reading="", rules=""):
        return [term, reading, "", rules, 0, definitions, -1, ""]

    def test_exact_and_arbitrary_diacritics_and_case(self):
        self.pack("Turkish", [self.row("araç", ["vehicle"]), self.row("oğul", ["son"]),
                              self.row("görüşürüz", ["see you"]), self.row("IŞIK", ["light"])])
        self.pack("Forms", [self.row("oğlum", [["oğul", []]])])
        self.library = Library(self.directory)
        for text, expected in (("arac", "araç"), ("oglum", "oğul"), ("GORUSURUZ", "görüşürüz"), ("ISIK", "IŞIK")):
            with self.subTest(text=text):
                entries = self.library.lookup(text, "tr")
                self.assertEqual(entries[0].term, expected)
        self.assertEqual(self.library.lookup("araç", "tr")[0].route, "exact")
        self.assertEqual(folded("I\u0307ŞIĞI"), "isigi")

    def test_form_cycles_are_bounded_and_exact_precedes_lemma(self):
        self.pack("Words", [self.row("yaz", ["summer"]), self.row("yazmak", ["write"])])
        self.pack("Forms", [self.row("yaz", [["yazmak", []]]), self.row("yazmak", [["yaz", []]])])
        self.library = Library(self.directory)
        self.assertEqual([e.term for e in self.library.lookup("yaz", "tr")], ["yaz", "yazmak"])

    def test_russian_yo_recovery_reuses_forms_without_merging_exact_spellings(self):
        self.pack("Russian", [self.row("пойти", ["go"]), self.row("все", ["everyone"]),
                              self.row("всё", ["everything"]), self.row("берёза", ["birch"])], language="ru")
        self.pack("Forms", [self.row("пошёл", [["пойти", ["past", "masculine"]]])], language="ru")
        self.library = Library(self.directory)
        entry = self.library.lookup("ПОШЕЛ", "ru")[0]
        self.assertEqual((entry.term, entry.route, entry.inflection),
                         ("пойти", "form spelling", ("past", "masculine")))
        self.assertEqual(self.library.lookup("береза", "ru")[0].term, "берёза")
        self.assertEqual([e.term for e in self.library.lookup("все", "ru")], ["все"])
        self.assertEqual([e.term for e in self.library.lookup("всё", "ru")], ["всё"])
        self.assertFalse(self.library.lookup("пошел", "ru", tolerant=False))
        self.assertFalse(self.library.lookup("пошел", "uk"))
        self.assertFalse(self.library.lookup("е" * 2000, "ru"))

    def test_form_labels_keep_shortest_alternatives_without_homograph_cycles(self):
        self.pack("Russian", [self.row("большой", ["big"]), self.row("великий", ["great"])], language="ru")
        self.pack("Forms", [
            self.row("больших", [["большой", ["accusative plural animate"]],
                                  ["большой", ["genitive plural"]],
                                  ["большой", ["prepositional plural"]]]),
            self.row("большой", [["большой", ["genitive/dative feminine"]],
                                 ["великий", ["comparative"]]]),
            self.row("великий", [["большой", ["cycle"]]])], language="ru")
        self.library = Library(self.directory)
        entries = {e.term: e for e in self.library.lookup("больших", "ru")}
        self.assertEqual(entries["большой"].inflection,
                         ("accusative plural animate OR genitive plural OR prepositional plural",))
        self.assertEqual(entries["великий"].inflection,
                         ("accusative plural animate · comparative OR genitive plural · comparative OR "
                          "prepositional plural · comparative",))

    def test_turkish_form_labels_survive_import_and_accent_recovery(self):
        self.pack("Words", [self.row("oğul", ["son"]), self.row("gelmek", ["come"])])
        self.pack("Forms", [self.row("oğlum", [["oğul", ["my (possessive)"]]]),
                            self.row("geldim", [["gelmek", ["past", "I"]]])])
        self.library = Library(self.directory)
        for spelling in ("oğlum", "oglum", "OGLUM"):
            self.assertEqual(self.library.lookup(spelling, "tr")[0].inflection, ("my (possessive)",))
        self.assertEqual(self.library.lookup("geldim", "tr")[0].inflection, ("past", "I"))
        self.assertEqual(self.library.lookup("gelmek", "tr")[0].inflection, ())

    def test_form_paths_remain_alternatives_and_old_packs_can_be_reimported(self):
        import sqlite3
        self.pack("Words", [self.row("ev", ["house"])])
        path = self.pack("Forms", [self.row("evleri", [["ev", ["plural", "accusative"]],
                                                     ["ev", ["his/her", "plural"]]])])
        self.library = Library(self.directory)
        self.assertEqual(self.library.lookup("evleri", "tr")[0].inflection,
                         ("plural · accusative OR his/her · plural",))
        self.library.close()
        with sqlite3.connect(path) as db:
            db.execute("ALTER TABLE forms DROP COLUMN labels")
            db.execute("UPDATE metadata SET value='1' WHERE key='schema_version'")
        db.close()
        self.library.refresh()
        self.assertEqual(self.library.lookup("evleri", "tr")[0].inflection, ("inflected form",))
        import_yomitan(self.root / "Forms1.zip", self.directory)
        self.library.refresh()
        self.assertEqual(self.library.lookup("evleri", "tr")[0].inflection,
                         ("plural · accusative OR his/her · plural",))

    def test_reverse_search_quotes_fts_and_supports_multiple_dictionaries(self):
        self.pack("A", [self.row("猫", ["cat; a domestic animal"], "ねこ")], "ja")
        self.pack("B", [self.row("猫", ["a cat"], "ねこ")], "ja")
        self.library = Library(self.directory)
        self.assertEqual(len(self.library.lookup("ネコ", "ja")), 2)
        self.assertEqual(len(self.library.reverse('"cat"', "ja")), 2)
        self.assertFalse(self.library.reverse('" OR * --', "ja"))
        self.assertIn("cat", self.library.lookup("猫")[0].glosses()[0])

    def test_failed_import_keeps_installed_pack_and_cleans_staging(self):
        installed = self.pack("Words", [self.row("araç", ["vehicle"])])
        before = installed.read_bytes()
        with self.assertRaises(ValueError):
            self.pack("Words", [["malformed"]], revision="2")
        self.assertEqual(installed.read_bytes(), before)
        self.assertEqual(list(self.directory.glob("*.tmp")), [])
        self.library = Library(self.directory)
        self.assertTrue(self.library.lookup("arac", "tr"))

    def test_reimport_idempotent_revisions_and_disable(self):
        self.pack("Words", [self.row("araç", ["old"])] )
        path = self.pack("Words", [self.row("araç", ["new"])], revision="2")
        self.assertEqual(import_yomitan(self.root / "Words2.zip", self.directory), path)
        self.library = Library(self.directory)
        self.assertEqual(len(self.library.packs), 1)
        self.assertEqual(self.library.lookup("araç", "tr")[0].definitions, ("new",))
        save_preferences(self.directory, [path.name], [])
        self.library.refresh()
        self.assertFalse(self.library.lookup("araç", "tr"))

    def test_typo_candidates_include_late_alphabet_replacements(self):
        self.pack("Words", [self.row("kitap", ["book"]), self.row("yüz", ["face"])])
        self.library = Library(self.directory)
        self.assertIn("kitap", self.library.suggest("kitpa"))
        self.assertIn("yüz", self.library.suggest("xuz"))

    def test_language_detection_reverse_and_translation_are_separate(self):
        self.pack("Words", [self.row("araç", ["vehicle"]), self.row("çat", ["crack"])])
        self.pack("Japanese", [self.row("猫", ["cat"], "ねこ"), self.row("食べる", ["eat"], "たべる", "v1")], "ja")
        from unittest.mock import Mock
        translator = Mock()
        translator.translate.return_value = "translation"
        engine = SearchEngine(self.directory, translator)
        try:
            self.assertEqual(engine.search("arac").source, "tr")
            self.assertEqual(engine.search("cat").entries[0].term, "猫")
            self.assertEqual(engine.search("食べました").entries[0].term, "食べる")
            translator.translate.assert_not_called()
            self.assertEqual(engine.search("hello", translate=True).translation, "translation")
            translator.translate.assert_called_once_with("hello", "en", "ja")
            engine.search("hello", translate=True)
            translator.translate.assert_called_once()
        finally:
            engine.close()

    def test_profile_pair_limits_detection_dictionaries_and_translation_direction(self):
        self.pack("Turkish", [self.row("am", ["Turkish entry"]), self.row("araç", ["vehicle"])])
        self.pack("Japanese", [self.row("猫", ["cat"], "ねこ")], "ja")
        from unittest.mock import Mock
        translator = Mock(last_model="fixture")
        translator.translate.return_value = "translated"
        engine = SearchEngine(self.directory, translator)
        try:
            self.assertEqual(engine.search("am", foreign="ja", pair=("ja", "en")).source, "en")
            self.assertEqual(engine.search("cat", foreign="ja", pair=("ja", "en")).entries[0].source, "Japanese")
            self.assertEqual(engine.search("vehicle", foreign="tr", pair=("tr", "en")).entries[0].source, "Turkish")
            first = engine.search("猫", foreign="ja", pair=("ja", "en"), translate=True)
            second = engine.search("cat", foreign="ja", pair=("ja", "en"), translate=True)
            self.assertEqual((first.source, first.target), ("ja", "en"))
            self.assertEqual((second.source, second.target), ("en", "ja"))
            self.assertEqual(first.entries, ())
            self.assertEqual(second.entries, ())
            manual = engine.search("Merhaba", source="tr", target="ru", foreign="ja",
                                   pair=("ja", "en"), translate=True)
            self.assertEqual((manual.source, manual.target), ("tr", "ru"))
            detected = engine.search("Привет", target="tr", foreign="ja", pair=("ja", "en"), translate=True)
            self.assertEqual((detected.source, detected.target), ("ru", "tr"))
            automatic_target = engine.search("Merhaba", source="tr", foreign="ja",
                                             pair=("ja", "en"), translate=True)
            self.assertEqual(automatic_target.target, "en")
            with self.assertRaisesRegex(ValueError, "different"):
                engine.search("cat", source="en", target="en", pair=("ja", "en"), translate=True)
        finally:
            engine.close()

    def test_other_languages_share_import_lookup_forms_and_reverse(self):
        self.pack("Deutsch", [self.row("Buch", ["book"]), self.row("Bücher", [["Buch", []]]),
                              self.row("für", ["for"])], "de")
        self.pack("한국어", [self.row("책", ["book"])], "ko")
        engine = SearchEngine(self.directory)
        try:
            self.assertEqual(engine.search("Bücher", source="de").entries[0].term, "Buch")
            self.assertEqual(engine.search("book", source="en", foreign="de").entries[0].term, "Buch")
            self.assertEqual(engine.search("Buch").source, "de")
            self.assertEqual(engine.search("für").source, "de")
            self.assertEqual(engine.search("책").source, "ko")
        finally:
            engine.close()

    def test_translation_retry_and_model_change_do_not_reuse_stale_output(self):
        from unittest.mock import Mock
        translator = Mock(last_model="Hy-MT2-7B")
        translator.cache_key.return_value = ("quality",)
        translator.translate.side_effect = [RuntimeError("Server is starting."), "First", "Second"]
        engine = SearchEngine(self.directory, translator)
        try:
            failed = engine.search("hello", source="en", translate=True)
            self.assertFalse(failed.translation)
            self.assertIn("starting", failed.message)
            result = engine.search("hello", source="en", translate=True)
            self.assertEqual(result.translation, "First")
            self.assertEqual(result.translation_model, "Hy-MT2-7B")
            translator.cache_key.return_value = ("lightweight",)
            translator.last_model = "Hy-MT2-1.8B"
            result = engine.search("hello", source="en", translate=True)
            self.assertEqual(result.translation, "Second")
            self.assertEqual(result.translation_model, "Hy-MT2-1.8B")
        finally:
            engine.close()

    def test_corrupt_preferences_are_recoverable_and_unchanged_inventory_keeps_connections(self):
        self.pack("Words", [self.row("kitap", ["book"])])
        (self.directory / 'preferences.json').write_text('null', encoding='utf-8')
        self.library = Library(self.directory)
        connection = self.library.packs[0][2]
        self.assertFalse(self.library.refresh_if_changed())
        self.assertIs(self.library.packs[0][2], connection)
        self.assertTrue(self.library.lookup('kitap', 'tr'))

    def test_reverse_prefers_exact_meaning_over_incidental_mentions(self):
        self.pack("Words", [self.row("uzun bir kitap ifadesi", ["a book about a book"]),
                            self.row("kitap", [dict(type='structured-content',content=[
                                dict(tag='div',content='book'), dict(tag='div',content='Many other details and examples.')])])])
        self.library = Library(self.directory)
        self.assertEqual(self.library.reverse('book', 'tr')[0].term, 'kitap')


if __name__ == "__main__":
    unittest.main()
