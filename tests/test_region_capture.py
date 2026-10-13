import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from meikipop.utils.capture import CaptureRequest, RegionCapture, _screen_geometry


class RegionTests(unittest.TestCase):
    def test_qt_friendly_monitor_name_maps_at_fractional_scale(self):
        monitors = {r"\\.\DISPLAY1": (0, 0, 3440, 1440)}
        self.assertEqual(_screen_geometry("ZQE-CAA", monitors, (0, 0, 2293, 960), 1.5),
                         (0, 0, 3440, 1440))

    def test_friendly_name_mapping_retains_negative_native_origins(self):
        monitors = {"left": (-1920, -100, 1920, 1080), "right": (0, 0, 2560, 1440)}
        self.assertEqual(_screen_geometry("friendly", monitors, (-1920, -100, 1280, 720), 1.5),
                         (-1920, -100, 1920, 1080))
        with self.assertRaisesRegex(RuntimeError, "Display changed"):
            _screen_geometry("friendly", monitors, (-1920, -100, 1280, 720), 2)
        with self.assertRaisesRegex(RuntimeError, "Display changed"):
            _screen_geometry("friendly", monitors, (-1919, -100, 1280, 720), 1.5)

    def test_ambiguous_or_missing_monitor_is_rejected(self):
        monitors = {"one": (0, 0, 1920, 1080), "two": (0, 0, 1920, 1080)}
        with self.assertRaisesRegex(RuntimeError, "Display changed"):
            _screen_geometry("friendly", monitors, (0, 0, 1920, 1080))
        self.assertEqual(_screen_geometry("one", monitors), monitors["one"])

    def test_negative_origin_and_mixed_scale(self):
        request = CaptureRequest(1, "screen", (-1920, -100, 1280, 720), (-1800, 0, 400, 200), 1.5, 2)
        self.assertEqual(request.physical_crop((-1920, -100, 1920, 1080)), (-1740, 50, 600, 300))

    def test_capture_owns_buffer_and_closes_backend_on_its_thread(self):
        calls = []
        pixels = bytearray([0, 0, 255, 0] * 4)
        backend = Mock()
        backend.grab.side_effect = lambda region: (calls.append(threading.get_ident()) or SimpleNamespace(bgra=pixels))
        backend.close.side_effect = lambda: calls.append(threading.get_ident())
        frames = []
        request = CaptureRequest(1, "screen", (0, 0, 2, 2), (0, 0, 2, 2), 1, 1)
        def run():
            capture = RegionCapture()
            try:
                frames.append(capture.capture(request))
            finally:
                capture.close()
        with patch("mss.mss", return_value=backend), patch("meikipop.utils.capture.windows_screen_geometry", return_value=(0, 0, 2, 2)):
            worker = threading.Thread(target=run)
            worker.start()
            worker.join(2)
        pixels[:] = bytes(len(pixels))
        self.assertEqual(frames[0].image().getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(calls, [worker.ident, worker.ident])
        self.assertNotEqual(worker.ident, threading.get_ident())
