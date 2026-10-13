import io
import json
from contextlib import closing
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile

from PIL import Image

from meikipop.dictionary.library import Library, import_yomitan, remove_dictionary
from meikipop.dictionary.media import resolve_image


class DictionaryMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, path="images/picture.avif", data=None):
        if data is None:
            stream = io.BytesIO()
            Image.new("RGB", (400, 200), "red").save(stream, format="PNG")
            data = stream.getvalue()
        archive = self.root / "images.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("index.json", json.dumps(dict(title="Illustrated", format=3, sourceLanguage="ja")))
            zf.writestr("term_bank_1.json", json.dumps([
                ["絵", "え", "", "", 0, [{"type": "structured-content", "content": [
                    "picture", {"tag": "img", "path": path, "alt": "drawing"}]}], -1, ""]]))
            zf.writestr(path, data)
        return archive

    def test_reimport_upgrades_old_image_pack_and_removal_cleans_assets(self):
        archive = self.archive()
        pack = import_yomitan(archive, self.library)
        with closing(Library(self.library)) as reader:
            entry = reader.lookup("絵")[0]
            image = entry.definitions[0]["content"][1]
            resolved = resolve_image(self.library, image["path"])
            with Image.open(resolved) as decoded:
                self.assertEqual(decoded.size, (400, 200))
            html = entry.glosses()[0]
            self.assertIn('width="320" height="160"', html)
            self.assertIn('src="meikipop-image:', html)
        import sqlite3
        with closing(sqlite3.connect(pack)) as db:
            db.execute("DELETE FROM metadata WHERE key='media_version'")
            db.commit()
        self.assertEqual(import_yomitan(archive, self.library), pack)
        self.assertTrue(pack.with_suffix(".assets").exists())
        remove_dictionary(self.library, pack.name, lambda: None, threading.Event())
        self.assertFalse(pack.exists())
        self.assertFalse(pack.with_suffix(".assets").exists())

    def test_untrusted_resources_and_broken_images_have_text_fallback(self):
        for source, data in (("../outside.png", None), ("https://example.test/image.png", None),
                             ("images/broken.png", b"not an image")):
            with self.subTest(source=source):
                pack = import_yomitan(self.archive(source, data), self.library)
                with closing(Library(self.library)) as reader:
                    entry = reader.lookup("絵")[0]
                    self.assertIn("drawing", entry.glosses()[0])
                    self.assertNotIn("<img", entry.glosses()[0])
                self.assertFalse(pack.with_suffix(".assets").exists())
        for uri in ("file:///C:/private.png", "https://example.test/image.png",
                    "meikipop-image:/../outside.png"):
            self.assertIsNone(resolve_image(self.library, uri))

    def test_cancellation_after_image_decode_discards_staged_pack_and_assets(self):
        archive = self.archive()
        def cancel_after_image():
            return any(self.library.glob(".import-assets-*/*.png"))
        with self.assertRaises(InterruptedError):
            import_yomitan(archive, self.library, cancelled=cancel_after_image)
        self.assertEqual(list(self.library.iterdir()), [])

    def test_explicit_reimport_repairs_a_missing_image_in_an_existing_asset_directory(self):
        archive = self.archive()
        pack = import_yomitan(archive, self.library)
        with closing(Library(self.library)) as reader:
            uri = reader.lookup("絵")[0].definitions[0]["content"][1]["path"]
        image = resolve_image(self.library, uri)
        image.unlink()
        self.assertTrue(pack.with_suffix(".assets").is_dir())
        self.assertIsNone(resolve_image(self.library, uri))
        import_yomitan(archive, self.library)
        self.assertEqual(resolve_image(self.library, uri), image)
