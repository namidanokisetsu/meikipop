import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from queue import Queue
import threading
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication
from meikipop.gui.unified_ocr import ScanWorker, HitWorker, UnifiedOCR
from meikipop.utils.capture import CaptureRequest, PixelFrame
from meikipop.dictionary.search import SearchResult
from test_unified_ocr import recognized, FakeWindow


class CachedFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cached_words_are_independent_of_slow_fresh_recognition(self):
        window = FakeWindow()
        controller = UnifiedOCR(window)
        controller.enabled = controller.holding = True
        screen = QApplication.primaryScreen()
        geometry = screen.geometry()
        request = CaptureRequest(1, screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), controller.generation)
        frames, results = Queue(), Queue()
        sink = SimpleNamespace(emit=lambda *args: frames.put(args))
        slow, release = threading.Event(), threading.Event()
        count = 0
        def provider(image):
            nonlocal count
            count += 1
            if count == 2:
                slow.set()
                release.wait(3)
            return recognized()
        engine = Mock()
        engine.search.side_effect = lambda text, **kw: SearchResult(text, "tr", "en")
        scan = ScanWorker(Mock(), frames=sink)
        hit_worker = HitWorker(SimpleNamespace(emit=lambda *args: results.put(args)))
        controller.hit_worker = hit_worker
        with patch.object(scan, "provider", return_value=provider), patch("meikipop.dictionary.search.SearchEngine", return_value=engine):
            scan.start()
            hit_worker.start()
            try:
                for color in (0, 255):
                    frame = PixelFrame(request, (2, 2), bytes([color] * 12), monotonic())
                    scan.queue.put((controller.generation, frame, (0, 0), "tr", (), False))
                    if color == 0:
                        controller.frame = frames.get(timeout=2)[1]
                self.assertTrue(slow.wait(2))
                controller.busy = True
                for point in (QPoint(80, 100), QPoint(280, 100)):
                    controller.hit_latest(point, monotonic())
                    results.get(timeout=2)
                self.assertEqual([call.args[0] for call in engine.search.call_args_list], ["kitap", "ev"])
                controller.hit_latest(QPoint(282, 100), monotonic())
                self.assertFalse(release.is_set())
                self.assertEqual(engine.search.call_count, 2)
                controller.invalidate()
                controller.hit_latest(QPoint(80, 100), monotonic())
                self.assertEqual(engine.search.call_count, 2)
            finally:
                release.set()
                scan.stop()
                scan.join(2)
                controller.shutdown()
                window.deleteLater()

    def test_worker_frame_freezes_provider_words_and_offsets(self):
        from dataclasses import replace
        from meikipop.ocr.frames import RecognizedFrame
        paragraphs = recognized()
        frozen = tuple(replace(p, words=tuple(p.words)) for p in paragraphs)
        paragraphs[0].words.clear()
        frame = RecognizedFrame(CaptureRequest(1, "screen", (0, 0, 400, 200), (0, 0, 400, 200), 1, 1),
                                frozen, "tr", (), 1, 10)
        self.assertEqual(frame.paragraphs[0].words[1].text, "ev")
        self.assertEqual(frame.point(280, 100), (.7, .5))
