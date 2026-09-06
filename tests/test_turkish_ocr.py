from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meikipop.ocr.turkish_paddle import LocalOCR, hit_word


class OCRTests(unittest.TestCase):
    def test_pointer_moves_reuse_recognition_but_changed_pixels_invalidate(self):
        import numpy as np
        from unittest.mock import Mock
        from meikipop.ocr.scan_cache import ScanCache
        ocr = LocalOCR.__new__(LocalOCR)
        ocr.scan_cache = ScanCache()
        ocr.engine = Mock()
        ocr.engine.predict.return_value = [{"rec_texts": ["kitap yaz"], "text_word": [["kitap", "yaz"]],
                                          "text_word_boxes": [[[0, 0, 30, 20], [40, 0, 70, 20]]]}]
        pixels = np.zeros((30, 80, 3), dtype=np.uint8)
        self.assertEqual(ocr.lookup_point(pixels, (15, 10)), ("kitap yaz", 0))
        self.assertEqual(ocr.lookup_point(pixels.copy(), (55, 10)), ("kitap yaz", 6))
        self.assertIsNone(ocr.lookup_point(pixels, (75, 25)))
        from meikipop.pipeline import REUSE_LAST_VALUE
        self.assertEqual(ocr.lookup_point(REUSE_LAST_VALUE, (55, 10)), ("kitap yaz", 6))
        self.assertEqual(ocr.engine.predict.call_count, 1)
        pixels[0, 0, 0] = 1
        ocr.lookup_point(pixels, (15, 10))
        self.assertEqual(ocr.engine.predict.call_count, 2)

    def test_boxes_preserve_context_and_repeated_word_offsets(self):
        result = {"rec_texts": ["kitap ve kitap"], "text_word": [["kitap", "ve", "kitap"]],
                  "text_word_boxes": [[[0, 0, 30, 20], [40, 0, 50, 20], [60, 0, 90, 20]]]}
        self.assertEqual(hit_word(result, (75, 10)), ("kitap ve kitap", 9))
        self.assertIsNone(hit_word(result, (35, 10)))
        self.assertIsNone(hit_word(result, (75, 25)))

    def test_missing_models_fail_before_paddle_import_or_download(self):
        with tempfile.TemporaryDirectory() as temporary, patch("meikipop.ocr.turkish_paddle.model_root", return_value=Path(temporary)):
            with self.assertRaisesRegex(RuntimeError, "setup-turkish-ocr"):
                LocalOCR()
