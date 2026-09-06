from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meikipop.ocr.turkish_paddle import LocalOCR, hit_word


class OCRTests(unittest.TestCase):
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
