import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from meikipop.data_assets import DataAsset, cleanup_removed_data, inventory, remove_asset, remove_language_data
from meikipop.dictionary.library import Library, import_yomitan


class DataAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data, self.cache, self.library = (self.root / name for name in ("data", "cache", "library"))
        self.roots = dict(data_root=self.data, cache_root=self.cache)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, data=b"fixture"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def pack(self, language):
        archive = self.root / (language + ".zip")
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("index.json", json.dumps(dict(title=language + " words", format=3, sourceLanguage=language)))
            bundle.writestr("term_bank_1.json", json.dumps([["word", "", "", "", 0, ["definition"]]]))
        return import_yomitan(archive, self.library)

    def test_inventory_separates_shared_models_and_all_installed_languages(self):
        from meikipop.scripts.translation_server import MODELS
        model = self.write(self.data / "translation/models" / MODELS["lightweight"]["file"])
        self.write(self.data / "languages/tr/paddle/3.7.0/model.bin")
        self.write(self.data / "languages/ru/stanza/1.14.0/model.pt")
        self.pack("en")
        assets = {asset.key: asset for asset in inventory(self.library, ("ja",), **self.roots)}
        self.assertEqual(assets["translation:lightweight"].paths, (model.resolve(),))
        self.assertEqual(assets["translation:lightweight"].status, "Incomplete")
        self.assertEqual(assets["ocr:paddle"].language, "")
        self.assertEqual(assets["stanza:ru"].language, "ru")
        self.assertTrue(any(asset.language == "en" and asset.kind == "dictionary" for asset in assets.values()))
        self.assertFalse(assets["builtin:ja"].removable)
        self.assertTrue(any(asset.kind == "recommended" and asset.language == "ja" for asset in assets.values()))

    def test_removing_language_deletes_its_packs_and_models_but_keeps_shared_data(self):
        russian, japanese = self.pack("ru"), self.pack("ja")
        stanza = self.write(self.data / "languages/ru/stanza/1.14.0/model.pt")
        shared = self.write(self.data / "languages/tr/paddle/3.7.0/model.bin")
        external = self.write(self.root / "external-model.pt")
        remove_language_data("ru", self.library, Mock(), threading.Event(), **self.roots)
        self.assertFalse(russian.exists())
        self.assertFalse(stanza.exists())
        self.assertTrue(japanese.exists())
        self.assertTrue(shared.exists())
        self.assertTrue(external.exists())
        library = Library(self.library)
        try:
            self.assertEqual([meta["language"] for _, meta, _ in library.packs], ["ja"])
        finally:
            library.close()

    def test_removal_rejects_inventory_paths_outside_owned_roots(self):
        external = self.write(self.root / "external.bin")
        asset = DataAsset("fixture", "Fixture", paths=(external,))
        with patch("meikipop.data_assets.inventory", return_value=(asset,)), self.assertRaises(ValueError):
            remove_asset("fixture", self.library, Mock(), threading.Event(), **self.roots)
        self.assertTrue(external.exists())

    def test_removing_shared_model_stops_owned_translation_and_preserves_other_files(self):
        from meikipop.scripts.translation_server import MODELS
        selected = self.write(self.data / "translation/models" / MODELS["lightweight"]["file"])
        other = self.write(self.data / "translation/models" / MODELS["quality"]["file"])
        with patch("meikipop.scripts.translation_server.shutdown_server") as shutdown:
            remove_asset("translation:lightweight", self.library, Mock(), threading.Event(), **self.roots)
        shutdown.assert_called_once_with()
        self.assertFalse(selected.exists())
        self.assertTrue(other.exists())

    def test_cancellation_and_invalid_keys_cannot_remove_external_files(self):
        from meikipop.scripts.translation_server import MODELS
        selected = self.write(self.data / "translation/models" / MODELS["lightweight"]["file"])
        external = self.write(self.root / "outside.sqlite3")
        cancelled = threading.Event()
        cancelled.set()
        with patch("meikipop.scripts.translation_server.shutdown_server"), self.assertRaises(InterruptedError):
            remove_asset("translation:lightweight", self.library, Mock(), cancelled, **self.roots)
        with self.assertRaises(ValueError):
            remove_asset("dictionary:../outside.sqlite3", self.library, Mock(), threading.Event(), **self.roots)
        self.assertTrue(selected.exists())
        self.assertTrue(external.exists())

    def test_linked_screenai_is_not_deleted_or_counted_as_owned_data(self):
        external = self.write(self.root / "external/chrome_screen_ai.dll")
        assets = inventory(self.library, screenai=str(external.parent), **self.roots)
        linked = next(asset for asset in assets if asset.key == "ocr:screenai-external")
        self.assertFalse(linked.removable)
        self.assertEqual(linked.size, 0)
        self.assertEqual(linked.status, "Linked")
        self.assertTrue(external.exists())

    def test_locked_files_are_uninstalled_and_collected_after_restart(self):
        unrelated = self.write(self.data / ".meikipop-removed-not-a-job/keep.bin")
        source = self.write(self.data / "screen_ai/component/chrome_screen_ai.dll")
        with patch("meikipop.data_assets.shutil.rmtree", side_effect=PermissionError("mapped file")):
            remove_asset("ocr:screenai", self.library, Mock(), threading.Event(), **self.roots)
        self.assertFalse(source.exists())
        pending = [asset for asset in inventory(self.library, **self.roots) if asset.kind == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertGreater(pending[0].size, 0)
        self.assertFalse(pending[0].removable)
        cleanup_removed_data(**self.roots)
        self.assertFalse(pending[0].paths[0].exists())
        self.assertTrue(unrelated.exists())
