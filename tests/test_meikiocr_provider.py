import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image


class MeikiPixelTests(unittest.TestCase):
    def test_colored_rgb_image_is_sent_as_contiguous_opencv_bgr(self):
        with patch.dict(sys.modules, {"meikiocr": SimpleNamespace(MeikiOCR=Mock())}):
            from meikipop.ocr.providers.meikiocr.provider import MeikiOcrProvider
        provider = MeikiOcrProvider.__new__(MeikiOcrProvider)
        provider.ocr_client = Mock()
        provider.ocr_client.run_ocr.return_value = []
        provider.scan(Image.new("RGB", (2, 3), (10, 20, 30)))
        pixels = provider.ocr_client.run_ocr.call_args.args[0]
        self.assertEqual(pixels[0, 0].tolist(), [30, 20, 10])
        self.assertTrue(pixels.flags.c_contiguous)
        self.assertEqual(pixels.shape, (3, 2, 3))


if __name__ == "__main__":
    unittest.main()
