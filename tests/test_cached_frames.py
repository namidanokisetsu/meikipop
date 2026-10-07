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
from meikipop.ocr.frames import RecognizedFrame
from meikipop.utils.capture import CaptureRequest, PixelFrame
from meikipop.dictionary.search import SearchResult
from meikipop.dictionary.library import Entry
from test_unified_ocr import recognized, FakeWindow


class CachedFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_boundary_recovery_delivers_first_word_without_pointer_movement(self):
        window = FakeWindow()
        controller = UnifiedOCR(window)
        controller.enabled = controller.holding = True
        screen = self.app.primaryScreen()
        geometry = screen.geometry()
        request = CaptureRequest(1, screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), controller.generation, True)
        frame = RecognizedFrame(request, tuple(recognized()), "tr", (), 1, monotonic())
        results = Queue()
        hit_worker = HitWorker(SimpleNamespace(emit=lambda *args: results.put(args)))
        controller.hit_worker = hit_worker
        book = Entry("book", "kitap", "", "Fixture", "tr", ("book",))
        engine = Mock()
        engine.search.return_value = SearchResult("kitap", "tr", "en", (book,))
        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(80, 100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.ocr.boundaries.expanded_crop", return_value=(0, 0, 600, 300)), \
                patch.object(controller, "_request_capture") as capture:
            hit_worker.start()
            try:
                controller.accept_frame(controller.generation, frame, "")
                capture.assert_called_once_with(QPoint(80, 100))
                controller.deliver(*results.get(timeout=2))
                window.show_entries.assert_called_once()
                window.set_context.assert_called_once_with("kitap ev", 0, 5)
            finally:
                controller.shutdown()
                window.deleteLater()

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

    def test_latest_pointer_and_frame_validity_replace_distance_rejection(self):
        from dataclasses import replace
        from meikipop.ocr.context import hit_paragraphs
        window = FakeWindow()
        controller = UnifiedOCR(window)
        controller.enabled = controller.holding = True
        screen = QApplication.primaryScreen()
        geometry = screen.geometry()
        request = CaptureRequest(1, screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), controller.generation)
        frame = RecognizedFrame(request, tuple(recognized()), "tr", (), 1, monotonic())
        controller.hit_worker = SimpleNamespace(queue=Queue(), stop=Mock(), join=Mock())
        try:
            with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(280, 100)), \
                    patch.object(QApplication, "activeWindow", return_value=None):
                controller.accept_frame(controller.generation, frame, "")
                job = controller.hit_worker.queue.get_nowait()
                self.assertEqual(job[2].query, "ev")
                old_hit = hit_paragraphs(frame.paragraphs, (.2, .5), "tr")
                book = Entry("book", "kitap", "", "Fixture", "tr", ("book",))
                house = Entry("house", "ev", "", "Fixture", "tr", ("house",))
                controller.deliver(controller.generation, SearchResult("kitap", "tr", "en", (book,)), (frame, old_hit), "")
                window.show_entries.assert_not_called()
                controller.deliver(controller.generation, SearchResult("ev", "tr", "en", (house,)), (frame, job[2]), "")
                window.show_entries.assert_called_once()
            point = QPoint(280, 100)
            for invalid in (replace(frame, captured_at=monotonic()-3), replace(frame, language="ja"),
                            replace(frame, request=replace(request, screen="other")),
                            replace(frame, request=replace(request, generation=-1))):
                self.assertFalse(controller._valid_frame(invalid, point, monotonic()))
        finally:
            controller.shutdown()
            window.deleteLater()
