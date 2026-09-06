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
