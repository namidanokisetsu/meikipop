import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from meikipop.ocr.providers.screenai import component
from meikipop.ocr.providers.screenai.chrome_screen_ai_pb2 import VisualAnnotation
from meikipop.ocr.providers.screenai.provider import ScreenAiOcr, suppress_output


def annotation(text="日本語", symbols=False):
    result = VisualAnnotation()
    line = result.lines.add(utf8_string=text, direction=1)
    line.bounding_box.width, line.bounding_box.height = 90, 20
    word = line.words.add(utf8_string=text)
    word.bounding_box.CopyFrom(line.bounding_box)
    if symbols:
        for i, char in enumerate(text):
            item = word.symbols.add(utf8_string=char)
            item.bounding_box.x, item.bounding_box.width, item.bounding_box.height = i * 30, 30, 20
    return result


class ComponentTests(unittest.TestCase):
    def test_discovery_accepts_resources_and_picks_numeric_latest_version(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(component.sys, "platform", "win32"):
            root = Path(directory)
            for version in ("9.0", "10.0"):
                folder = root / version / "resources"
                folder.mkdir(parents=True)
                (folder / "chrome_screen_ai.dll").touch()
            self.assertEqual(component.find_component_directory(root), (root / "10.0/resources").resolve())
            with self.assertRaisesRegex(RuntimeError, "extracted component folder"):
                component.find_component_directory(root / "absent")

    def test_mac_supports_official_so_and_alternate_dylib_with_arm_package(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(component.sys, "platform", "darwin"), \
                patch.object(component.platform, "machine", return_value="arm64"):
            root = Path(directory)
            for name in ("libchromescreenai.so", "libchromescreenai.dylib"):
                library = root / name
                library.touch()
                self.assertEqual(component.find_component_directory(root), root.resolve())
                library.unlink()
            self.assertTrue(component.component_url().endswith("mac-arm64"))

    def test_missing_standard_descriptors_do_not_block_native_calls(self):
        with patch("meikipop.ocr.providers.screenai.provider.os.dup", side_effect=OSError("no console")):
            with suppress_output():
                reached = True
        self.assertTrue(reached)


class ScreenAiBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / component.library_names()[0]).touch()
        self.native = Mock()
        self.native.InitOCRUsingCallback.return_value = True
        self.native.GetMaxImageDimension.return_value = 2048
        self.native.PerformOCR.return_value = None
        for name, value in (("_is_initialized", False), ("_directory", None), ("_lib", None)):
            patcher = patch.object(ScreenAiOcr, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("meikipop.ocr.providers.screenai.provider.ctypes.CDLL", return_value=self.native)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = ScreenAiOcr(self.root)

    def test_bitmap_has_stable_pixel_ref_bgra_pixels_and_does_not_resize_input(self):
        image = Image.new("RGB", (3000, 10), (10, 20, 30))
        captured = []

        def recognize(bitmap, length):
            bitmap = bitmap._obj
            captured.append((bitmap.fPixelRef, bitmap.fPixmap.fInfo.fDimensions.fWidth,
                             ctypes.string_at(bitmap.fPixmap.fPixels, 4)))
            return None

        self.native.PerformOCR.side_effect = recognize
        self.assertEqual(self.provider.scan(image), [])
        self.assertEqual(image.size, (3000, 10))
        self.assertTrue(captured[0][0])
        self.assertEqual(captured[0][1:], (2048, bytes((30, 20, 10, 255))))

    def test_native_buffer_freed_and_whole_word_retained_when_symbols_absent(self):
        data = annotation().SerializeToString()
        buffer = ctypes.create_string_buffer(data)

        def recognize(bitmap, length):
            length._obj.value = len(data)
            return ctypes.addressof(buffer)

        self.native.PerformOCR.side_effect = recognize
        paragraphs = self.provider.scan(Image.new("RGB", (100, 30)))
        self.assertEqual(paragraphs[0].full_text, "日本語")
        self.assertEqual(paragraphs[0].words[0].text, "日本語")
        self.native.FreeLibraryAllocatedCharArray.assert_called_once_with(ctypes.addressof(buffer))

    def test_model_callbacks_stay_inside_component_and_do_not_overread(self):
        (self.root / "model.bin").write_bytes(b"abc")
        output = ctypes.create_string_buffer(b"zzzzzzzz")
        self.assertEqual(ScreenAiOcr._cb1(b"model.bin"), 3)
        self.assertEqual(ScreenAiOcr._cb1(b"../missing.bin"), 0)
        ScreenAiOcr._cb2(b"model.bin", 8, ctypes.addressof(output))
        self.assertEqual(output.raw[:8], b"abczzzzz")

    def test_different_loaded_component_requires_restart(self):
        other = self.root / "other"
        other.mkdir()
        (other / component.library_names()[0]).touch()
        with self.assertRaisesRegex(RuntimeError, "Restart Meikipop"):
            ScreenAiOcr(other)

    def test_actual_symbol_boxes_and_line_only_vertical_text_survive(self):
        lines = self.provider._transform(annotation(symbols=True), 100, 30)
        self.assertEqual([word.text for word in lines[0].words], list("日本語"))
        result = annotation()
        del result.lines[0].words[:]
        result.lines[0].direction = 3
        lines = self.provider._transform(result, 100, 30)
        self.assertTrue(lines[0].is_vertical)
        self.assertEqual(lines[0].words[0].text, "日本語")

    def test_turkish_symbols_form_complete_accented_words_and_source_context(self):
        from meikipop.ocr.context import hit_paragraphs
        self.provider.language = "tr"
        text = "Öğretmen öğrencilerle görüşüyor."
        paragraphs = self.provider._transform(annotation(text, symbols=True), 1000, 100)
        self.assertEqual(paragraphs[0].full_text, text)
        self.assertEqual([word.text for word in paragraphs[0].words],
                         ["Öğretmen", "öğrencilerle", "görüşüyor"])
        for word in paragraphs[0].words:
            hit = hit_paragraphs(paragraphs, (word.box.center_x, word.box.center_y), "tr")
            self.assertEqual(hit.query, word.text)
            self.assertEqual(hit.sentence[0], text)


if __name__ == "__main__":
    unittest.main()
