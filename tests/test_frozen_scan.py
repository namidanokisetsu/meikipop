import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from queue import Queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

from meikipop.gui.unified_ocr import ScanWorker, UnifiedOCR
from meikipop.ocr.frames import RecognizedFrame
from meikipop.utils.capture import CaptureRequest, PixelFrame
from test_unified_ocr import FakeWindow, recognized


class FrozenScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_captures_once_per_hold_and_crops_same_pixels(self):
        request = CaptureRequest(1, "test", (-20, 0, 40, 20), (-20, 0, 20, 20), 2, 1, True)
        next_crop = replace(request, revision=2, crop=(0, 0, 20, 20))
        new_hold = replace(request, revision=3, generation=2)
        backend = Mock()
        backend.capture.side_effect = lambda r: PixelFrame(r, (80, 40), bytes([80]) * 80 * 40 * 3,
                                                         10, physical_crop=(-40, 0, 80, 40))
        frames = Mock()
        worker = ScanWorker(Mock(), frames=frames)
        worker.queue = Queue()
        for r in (request, next_crop, new_hold):
            worker.queue.put((r.generation, r, (.2, .5), "tr", ("paddle", ""), False, None, 10))
        worker.queue.put(None)
        with patch("meikipop.gui.unified_ocr.RegionCapture", return_value=backend), \
                patch.object(worker, "provider", return_value=lambda image: recognized()):
            worker.run()
        self.assertEqual(backend.capture.call_count, 2)
        self.assertTrue(all(call.args[0].crop == request.geometry for call in backend.capture.call_args_list))
        first, second, third = [call.args[1] for call in frames.emit.call_args_list]
        self.assertEqual(first.captured_at, second.captured_at)
        self.assertEqual(second.physical_crop, (0, 0, 40, 40))
        self.assertEqual(third.request.generation, 2)
        self.assertIsNone(worker._frozen)
        worker.invalidate(3)
        self.assertIsNone(worker._frozen)

    def test_frozen_frame_survives_age_but_not_release_or_profile_change(self):
        window = FakeWindow()
        controller = UnifiedOCR(window)
        self.addCleanup(controller.shutdown)
        controller.enabled = controller.holding = True
        controller.freeze_while_held = True
        screen = self.app.primaryScreen()
        rect = screen.geometry()
        geometry = (rect.x(), rect.y(), rect.width(), rect.height())
        request = CaptureRequest(1, screen.name(), geometry, geometry, screen.devicePixelRatio(), controller.generation, True)
        frame = RecognizedFrame(request, (), "tr", (), 1, 0)
        point = rect.center()
        self.assertTrue(controller._valid_frame(frame, point, 1000))
        self.assertFalse(controller._valid_frame(replace(frame, request=replace(request, frozen=False)), point, 1000))
        controller.frame = frame
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=point), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch.object(controller, "_request_capture") as capture:
            controller.scan()
            capture.assert_not_called()
        window.preferred_foreign = "ja"
        self.assertFalse(controller._valid_frame(frame, point, 1000))
        window.preferred_foreign = "tr"
        controller.hold_changed(False)
        self.assertIsNone(controller.frame)
        self.assertFalse(controller._valid_frame(frame, point, 1000))

    def test_crop_preserves_pixel_ownership_and_timestamp(self):
        from PIL import Image
        request = CaptureRequest(1, "test", (0, 0, 4, 2), (0, 0, 4, 2), 1, 1, True)
        image = Image.new("RGB", (4, 2), "red")
        image.putpixel((3, 1), (0, 0, 255))
        full = PixelFrame(request, image.size, image.tobytes(), 17, physical_crop=(-4, 0, 4, 2))
        crop = full.cropped(replace(request, crop=(2, 0, 2, 2)))
        self.assertEqual(crop.image().getpixel((1, 1)), (0, 0, 255))
        self.assertEqual(crop.captured_at, 17)
        self.assertEqual(crop.physical_crop, (-2, 0, 2, 2))
