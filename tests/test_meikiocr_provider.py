import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image


class MeikiPixelTests(unittest.TestCase):
    def test_missing_local_model_never_starts_downloading_client(self):
        from meikipop.ocr.providers.meikiocr.provider import MeikiOcrProvider
        client = Mock()
        with patch.dict(sys.modules, {"meikiocr": SimpleNamespace(MeikiOCR=client)}), \
                patch("meikipop.ocr.providers.meikiocr.provider.require_local_models",
                      side_effect=RuntimeError("Install Japanese OCR models")):
            with self.assertRaisesRegex(RuntimeError, "Install Japanese OCR models"):
                MeikiOcrProvider()
        client.assert_not_called()

    def test_model_preflight_uses_only_local_cache(self):
        from meikipop.ocr.providers.meikiocr.provider import require_local_models
        constants = SimpleNamespace(DET_MODEL_REPO="det", DET_MODEL_NAME="det.onnx",
                                    REC_MODEL_REPO="rec", REC_MODEL_NAME="rec.onnx", VREC_MODEL_NAME="vertical.onnx")
        download = Mock()
        with patch.dict(sys.modules, {"meikiocr.ocr": constants, "huggingface_hub": SimpleNamespace(hf_hub_download=download)}):
            require_local_models()
        self.assertEqual(download.call_count, 3)
        self.assertTrue(all(call.kwargs["local_files_only"] for call in download.call_args_list))

    def test_colored_rgb_image_is_sent_as_contiguous_opencv_bgr(self):
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
