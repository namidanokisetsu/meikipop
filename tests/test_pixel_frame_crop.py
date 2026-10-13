from dataclasses import replace
import unittest
from unittest.mock import patch

from meikipop.utils.capture import CaptureRequest, PixelFrame


class PixelFrameCropTests(unittest.TestCase):
    def frame(self, mode="BGRX", stride=0):
        channels = {"RGB": 3, "BGR": 3, "RGBX": 4, "BGRX": 4}[mode]
        row_size = 6 * channels
        stride = stride or row_size
        rows = [bytes((index + row * 31) % 256 for index in range(row_size))
                + bytes([255]) * (stride - row_size) for row in range(6)]
        request = CaptureRequest(1, "screen", (-40, -20, 4, 4), (-40, -20, 4, 4), 1.5, 7, True)
        return PixelFrame(request, (6, 6), b"".join(rows), 17, mode, stride, (-2400, -900, 6, 6))

    def test_bgrx_crop_preserves_snapshot_coordinates_and_timestamp(self):
        frame = self.frame()
        pixels = frame.pixels
        request = replace(frame.request, revision=2, crop=(-39, -19, 2, 2))
        expected = frame.image().crop((2, 2, 5, 5)).tobytes()
        cropped = frame.cropped(request)
        self.assertEqual(expected, cropped.image().tobytes())
        self.assertEqual((3, 3), cropped.size)
        self.assertEqual((-2398, -898, 3, 3), cropped.physical_crop)
        self.assertEqual(17, cropped.captured_at)
        self.assertIs(request, cropped.request)
        self.assertIs(pixels, frame.pixels)

    def test_supported_modes_and_padded_strides_keep_exact_rgb(self):
        for mode in ("RGB", "BGR", "RGBX", "BGRX"):
            for padding in (0, 7):
                with self.subTest(mode=mode, padding=padding):
                    channels = 3 if mode in ("RGB", "BGR") else 4
                    frame = self.frame(mode, 6 * channels + padding)
                    request = replace(frame.request, crop=(-39, -19, 2, 2))
                    expected = frame.image().crop((2, 2, 5, 5)).tobytes()
                    cropped = frame.cropped(request)
                    self.assertEqual(expected, cropped.image().tobytes())
                    self.assertEqual(mode, cropped.mode)
                    self.assertEqual(0, cropped.stride)

    def test_contained_crop_does_not_decode_the_full_frame(self):
        frame = self.frame()
        request = replace(frame.request, crop=(-39, -19, 2, 2))
        with patch.object(PixelFrame, "image", side_effect=AssertionError("full-frame decode")):
            cropped = frame.cropped(request)
        self.assertEqual((3, 3), cropped.size)

    def test_outside_crop_keeps_black_padding_and_physical_bounds(self):
        frame = self.frame(stride=31)
        request = replace(frame.request, crop=(-41, -22, 3, 4))
        expected = frame.image().crop((-2, -3, 2, 3)).tobytes()
        cropped = frame.cropped(request)
        self.assertEqual(expected, cropped.image().tobytes())
        self.assertEqual("RGB", cropped.mode)
        self.assertEqual((-2402, -903, 4, 6), cropped.physical_crop)
        self.assertEqual((0, 0, 0), cropped.image().getpixel((0, 0)))

    def test_planar_raw_decoder_uses_the_original_image_fallback(self):
        frame = self.frame("RGB")
        planar = replace(frame, mode="RGB;L", stride=0)
        request = replace(frame.request, crop=(-39, -19, 2, 2))
        expected = planar.image().crop((2, 2, 5, 5)).tobytes()
        cropped = planar.cropped(request)
        self.assertEqual(expected, cropped.image().tobytes())
        self.assertEqual("RGB", cropped.mode)


if __name__ == "__main__":
    unittest.main()
