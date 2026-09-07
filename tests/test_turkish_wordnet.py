from pathlib import Path
import tempfile
import unittest

from meikipop.dictionary.turkish_wordnet import build, WordNetStore


SOURCE = '''<SYNSETS>
<SYNSET><ID>1</ID><SYNONYM><LITERAL>ışık<SENSE>1</SENSE><GROUP>2</GROUP></LITERAL>
<LITERAL>ziya<SENSE>3</SENSE></LITERAL></SYNONYM><POS>n</POS><DEF>Aydınlık</DEF>
<SR>2<TYPE>HYPERNYM</TYPE></SR><SR>missing<TYPE>ANTONYM</TYPE></SR></SYNSET>
<SYNSET><ID>2</ID><SYNONYM><LITERAL>enerji<SENSE>1</SENSE></LITERAL></SYNONYM><POS>n</POS></SYNSET>
<SYNSET><ID>3</ID><SYNONYM><LITERAL>ışık<SENSE>2</SENSE></LITERAL></SYNONYM><POS>n</POS><DEF>Umut</DEF></SYNSET>
</SYNSETS>'''


class WordNetTests(unittest.TestCase):
    def test_order_uses_clicked_lemma_senses_and_hides_ambiguous_derivations(self):
        from dataclasses import replace
        from meikipop.dictionary.turkish_lookup import TextResult
        from meikipop.gui.turkish.rendering import render_result
        source_text = '''<SYNSETS>
        <SYNSET><ID>001</ID><SYNONYM><LITERAL>yırtmak<SENSE>3</SENSE></LITERAL>
        <LITERAL>kırmak<SENSE>1</SENSE></LITERAL></SYNONYM><POS>v</POS><DEF>Destroy</DEF>
        <EXAMPLE>First.|Second.</EXAMPLE><SR>003<TYPE>DERIVATION_RELATED</TYPE></SR></SYNSET>
        <SYNSET><ID>002</ID><SYNONYM><LITERAL>yırtmak<SENSE>1</SENSE></LITERAL></SYNONYM>
        <POS>v</POS><DEF>Tear fabric</DEF><SR>004<TYPE>DERIVATION_RELATED</TYPE></SR></SYNSET>
        <SYNSET><ID>003</ID><SYNONYM><LITERAL>buzkıran<SENSE>1</SENSE></LITERAL></SYNONYM></SYNSET>
        <SYNSET><ID>004</ID><SYNONYM><LITERAL>yırtmaç<SENSE>1</SENSE></LITERAL></SYNONYM></SYNSET>
        </SYNSETS>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source.xml").write_text(source_text, encoding="utf-8")
            build(root / "source.xml", root / "pack.sqlite3")
            store = WordNetStore(root / "pack.sqlite3")
            try:
                groups = store.lookup(["yırtmak"], "VERB")
                self.assertEqual([g["id"] for g in groups], ["002", "001"])
                self.assertEqual(groups[1]["relations"], [])
                result = TextResult("yırtmak", (), None, (), "", wordnet=groups)
                preview = render_result(result)
                self.assertNotIn("buzkıran", preview)
                self.assertNotIn("yırtmaç", preview)
                self.assertNotIn("word:y%C4%B1rtmak", preview)
                self.assertNotIn("|", preview)
                expanded = render_result(result, show_more=True)
                self.assertIn("yırtmaç", expanded)
                self.assertIn("Second.", expanded)
                self.assertNotIn("buzkıran", expanded)
            finally:
                store.close()

    def test_senses_edges_and_turkish_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.xml"
            source.write_text(SOURCE, encoding="utf-8")
            report = build(source, root / "pack.sqlite3", {"source": "fixture"})
            self.assertEqual(report["missing_targets"], 1)
            store = WordNetStore(root / "pack.sqlite3")
            try:
                groups = store.lookup(["IŞIK", "ışık"])
                self.assertEqual(len(groups), 2)
                self.assertEqual(groups[0]["members"][0]["sense"], "1")
                self.assertEqual(groups[0]["members"][0]["group_id"], "2")
                self.assertEqual(groups[0]["relations"][0]["spelling"], "enerji")
                self.assertEqual(store.lookup(["İŞİK"]), ())
                self.assertEqual(store.lookup(["ziya"])[0]["id"], "1")
            finally:
                store.close()
            before = (root / "pack.sqlite3").read_bytes()
            source.write_text("<SYNSETS/>", encoding="utf-8")
            with self.assertRaises(ValueError):
                build(source, root / "pack.sqlite3")
            self.assertEqual((root / "pack.sqlite3").read_bytes(), before)
