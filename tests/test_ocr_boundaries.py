import unittest
from dataclasses import replace

from meikipop.ocr.boundaries import expanded_crop
from meikipop.ocr.frames import RecognizedFrame
from meikipop.ocr.interface import BoundingBox, Paragraph, Word
from meikipop.utils.capture import CaptureRequest


def frame(box, *, vertical=False):
    word = Word("kitap", "", box)
    return RecognizedFrame(CaptureRequest(1, "screen", (-1000, 0, 3000, 1600),
                                         (-500, 300, 1200, 480), 1.5, 1),
                           (Paragraph("kitap", [word], box, vertical),), "tr", (), 1, 0, (1800, 720))


class BoundaryTests(unittest.TestCase):
    def test_right_edge_grows_with_next_line_context_on_negative_monitor(self):
        value = frame(BoundingBox(.95, .5, .1, .2))
        self.assertEqual(expanded_crop(value, (640, 540)), (-500, 300, 1800, 720))

    def test_interior_word_and_pointer_outside_text_do_not_rescan(self):
        self.assertIsNone(expanded_crop(frame(BoundingBox(.5, .5, .2, .2)), (100, 540)))
        self.assertIsNone(expanded_crop(frame(BoundingBox(.95, .5, .1, .2)), (100, 540)))

    def test_screen_boundary_is_final(self):
        value = frame(BoundingBox(.95, .5, .1, .2))
        value = replace(value, request=replace(value.request, crop=value.request.geometry))
        self.assertIsNone(expanded_crop(value, (1850, 800)))

    def test_vertical_continuation_grows_down_and_left(self):
        value = frame(BoundingBox(.5, .95, .2, .1), vertical=True)
        self.assertEqual(expanded_crop(value, (100, 756)), (-1000, 300, 1700, 720))

    def test_pixel_margin_accounts_for_actual_capture_scale(self):
        value = frame(BoundingBox(.945, .5, .1, .2))
        self.assertIsNone(expanded_crop(value, (634, 540)))
        value = replace(value, pixel_size=(600, 240))
        self.assertIsNotNone(expanded_crop(value, (634, 540)))
