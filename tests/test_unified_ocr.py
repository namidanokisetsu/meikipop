import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from queue import Queue
import threading
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QCheckBox, QLineEdit, QToolButton, QWidget

from meikipop.gui.unified_ocr import HitWorker, PaddleScan, ScanWorker, UnifiedOCR
from meikipop.ocr.context import ContextHit
from meikipop.ocr.interface import BoundingBox, Paragraph, Word


def image_bytes():
    image = QImage(100, 50, QImage.Format.Format_RGB32)
    image.fill(0xffffffff)
    return image


def recognized():
    first = Word("kitap", " ", BoundingBox(0.2, 0.5, 0.3, 0.3))
    second = Word("ev", "", BoundingBox(0.7, 0.5, 0.3, 0.3))
    return [Paragraph("kitap ev", [first, second], BoundingBox(0.5, 0.5, 1, 0.5), False)]


class ScanWorkerTests(unittest.TestCase):
    def make_worker(self, jobs):
        sink = SimpleNamespace(emit=Mock())
        worker = ScanWorker(sink)
        worker.queue = Queue()
        for job in jobs:
            worker.queue.put(job)
        return worker, sink

    def test_failed_engine_initialization_reports_error_and_can_retry(self):
        image = image_bytes()
        worker, sink = self.make_worker([(1, image, (0.2, 0.5), "tr"), (2, image, (0.2, 0.5), "tr"), None])
        engine = Mock()
        with patch("meikipop.dictionary.search.SearchEngine", side_effect=[RuntimeError("fixture init"), engine]), \
                patch.object(worker, "provider", return_value=lambda image: recognized()):
            worker.run()
        self.assertEqual(sink.emit.call_args_list[0].args, (1, None, None, "fixture init"))
        self.assertEqual(sink.emit.call_args_list[1].args[0], 2)
        self.assertEqual(sink.emit.call_args_list[1].args[2].query, "kitap")
        engine.close.assert_called_once_with()

    def test_pointer_moves_reuse_recognition_and_lookup_uses_current_word(self):
        image = image_bytes()
        worker, sink = self.make_worker([(1, image, (0.2, 0.5), "tr"), (2, None, (0.7, 0.5), "tr"), None])
        engine, provider = Mock(), Mock(return_value=recognized())
        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch.object(worker, "provider", return_value=provider):
            worker.run()
        provider.assert_called_once()
        self.assertEqual([call.args[0] for call in engine.search.call_args_list], ["kitap", "ev"])
        self.assertEqual([call.args[2].text for call in sink.emit.call_args_list], ["kitap ev", "kitap ev"])
        engine.refresh.assert_not_called()

    def test_paddle_profiles_share_model_but_keep_language_frame_caches(self):
        image = image_bytes()
        worker, sink = self.make_worker([
            (1, image, (.2, .5), "tr", ("paddle", "")),
            (2, image, (.2, .5), "en", ("paddle", "")),
            (3, image, (.7, .5), "tr", ("paddle", "")), None])
        provider, engine = Mock(return_value=recognized()), Mock()
        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch.object(worker, "provider", return_value=provider) as factory:
            worker.run()
        factory.assert_called_once_with("tr", "paddle", "")
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(sink.emit.call_count, 3)

    def test_unrelated_component_setting_does_not_duplicate_meiki_model(self):
        for default in ("meikiocr", "vision"):
            with self.subTest(default=default):
                image = image_bytes()
                worker, sink = self.make_worker([
                    (1, image, (.2, .5), "ja", ("meikiocr", "")),
                    (2, image, (.2, .5), "ja", ("meikiocr", "screenai/component")),
                    (3, image, (.7, .5), "ja"), None])
                provider, engine = Mock(return_value=recognized()), Mock()
                engine.search.return_value = SimpleNamespace(entries=())
                with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                        patch("meikipop.language.support.default_ocr_provider", return_value=default), \
                        patch("meikipop.language.support.ocr_supported", return_value=True), \
                        patch.object(worker, "provider", return_value=provider) as factory:
                    worker.run()
                self.assertEqual(factory.call_args_list[0].args, ("ja", "meikiocr", ""))
                if default == "meikiocr":
                    factory.assert_called_once()
                    provider.assert_called_once()
                else:
                    self.assertEqual(factory.call_count, 2)
                    self.assertEqual(factory.call_args_list[1].args, ("ja",))
                    self.assertEqual(provider.call_count, 2)
                self.assertEqual(sink.emit.call_count, 3)

    def test_capture_precedes_slow_model_loading(self):
        from meikipop.utils.capture import CaptureRequest, PixelFrame
        request = CaptureRequest(1, "fixture", (0, 0, 100, 50), (0, 0, 100, 50), 1, 1, True)
        worker, _ = self.make_worker([(1, request, (.2, .5), "tr", ("paddle", "")), None])
        worker.frames = SimpleNamespace(emit=Mock())
        order = []
        capture = Mock()
        capture.capture.side_effect = lambda request: (order.append("capture") or PixelFrame(request, (100, 50), bytes(15000), 1))
        provider = Mock(return_value=recognized())
        with patch("meikipop.gui.unified_ocr.RegionCapture", return_value=capture), \
                patch.object(worker, "provider", side_effect=lambda *args: (order.append("model") or provider)):
            worker.run()
        self.assertEqual(order, ["capture", "model"])
        capture.close.assert_called_once()

    def test_stop_during_model_loading_skips_inference(self):
        worker, sink = self.make_worker([(1, image_bytes(), (.2, .5), "tr"), None])
        provider = Mock(return_value=recognized())
        def load(*args):
            worker.stop()
            return provider
        with patch("meikipop.dictionary.search.SearchEngine", return_value=Mock()), \
                patch.object(worker, "provider", side_effect=load):
            worker.run()
        provider.assert_not_called()
        sink.emit.assert_not_called()

    def test_optional_morphology_receives_original_ocr_context(self):
        worker, _ = self.make_worker([(1, image_bytes(), (.2, .5), "tr", ("paddle", ""), True), None])
        engine = Mock()
        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch.object(worker, "provider", return_value=lambda image: recognized()):
            worker.run()
        engine.search.assert_called_once_with("kitap", source="tr", foreign="tr", morphology=True,
                                              context=("kitap ev", 0, 5))

    def test_receiver_deleted_during_inference_does_not_crash_worker(self):
        worker, sink = self.make_worker([(1, image_bytes(), (0.2, 0.5), "tr"), None])
        sink.emit.side_effect = RuntimeError("wrapped C++ object has been deleted")
        engine = Mock()
        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch.object(worker, "provider", return_value=lambda image: recognized()):
            worker.run()
        engine.close.assert_called_once_with()

    def test_stop_during_inference_suppresses_late_delivery_and_closes_engine(self):
        entered, release = threading.Event(), threading.Event()
        worker, sink = self.make_worker([(1, image_bytes(), (0.2, 0.5), "tr")])
        engine = Mock()

        def recognize(image):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test inference timed out")
            return recognized()

        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch.object(worker, "provider", return_value=recognize):
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                worker.stop()
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        sink.emit.assert_not_called()
        engine.search.assert_not_called()
        engine.close.assert_called_once_with()

    def test_selected_provider_and_component_have_independent_recognition_caches(self):
        image = image_bytes()
        worker, sink = self.make_worker([
            (1, image, (0.2, 0.5), "ja", ("meikiocr", "")),
            (2, image, (0.2, 0.5), "ja", ("screenai", "component")),
            (3, image, (0.2, 0.5), "ja", ("screenai", "component")),
            (4, image, (0.2, 0.5), "ja", ("meikiocr", "")), None])
        engine = Mock()
        engine.search.return_value = SimpleNamespace(entries=())
        first, second = Mock(return_value=recognized()), Mock(return_value=recognized())
        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch.object(worker, "provider", side_effect=[first, second]) as factory:
            worker.run()
        self.assertEqual([call.args for call in factory.call_args_list],
                         [("ja", "meikiocr", ""), ("ja", "screenai", "component")])
        first.assert_called_once()
        second.assert_called_once()
        self.assertEqual(sink.emit.call_count, 4)

    def test_screenai_can_be_selected_on_macos_without_vision_route(self):
        provider = Mock()
        with patch("meikipop.gui.unified_ocr.sys.platform", "darwin"), \
                patch("meikipop.ocr.providers.screenai.provider.ScreenAiOcr", return_value=provider) as factory:
            scan = ScanWorker.provider("ja", "screenai", "/local/component")
        self.assertEqual(scan, provider.scan)
        factory.assert_called_once_with("/local/component", language="ja")

    def test_japanese_meiki_route_explicitly_uses_cpu(self):
        provider = Mock()
        factory = Mock(return_value=provider)
        with patch.dict(sys.modules, {"meikipop.ocr.providers.meikiocr.provider": SimpleNamespace(MeikiOcrProvider=factory)}):
            scan = ScanWorker.provider("ja", "meikiocr")
        self.assertEqual(scan, provider.scan)
        factory.assert_called_once_with(execution_provider="CPUExecutionProvider")

    def test_russian_defaults_to_screenai_and_rejects_incompatible_paddle(self):
        provider = Mock()
        with patch("meikipop.gui.unified_ocr.sys.platform", "win32"), \
                patch("meikipop.ocr.providers.screenai.provider.ScreenAiOcr", return_value=provider) as factory:
            self.assertEqual(ScanWorker.provider("ru"), provider.scan)
            factory.assert_called_once_with(None, language="ru")
            with self.assertRaisesRegex(RuntimeError, "does not support this language"):
                ScanWorker.provider("ru", "paddle")

    def test_yiddish_uses_verified_screenai_without_japanese_route(self):
        provider = Mock()
        with patch("meikipop.gui.unified_ocr.sys.platform", "win32"), \
                patch("meikipop.ocr.providers.screenai.provider.ScreenAiOcr", return_value=provider) as factory:
            self.assertEqual(ScanWorker.provider("yi"), provider.scan)
        factory.assert_called_once_with(None, language="yi")

    def test_unverified_language_does_not_load_native_component(self):
        with patch("meikipop.gui.unified_ocr.sys.platform", "win32"), \
                patch("meikipop.ocr.providers.screenai.provider.ScreenAiOcr") as factory:
            with self.assertRaisesRegex(RuntimeError, "unverified"):
                ScanWorker.provider("ang")
            with self.assertRaisesRegex(RuntimeError, "does not support"):
                ScanWorker.provider("ang", "screenai")
        factory.assert_not_called()

    def test_invalid_selection_on_mac_cannot_fall_through_to_vision(self):
        with patch("meikipop.gui.unified_ocr.sys.platform", "darwin"), \
                patch("meikipop.ocr.macos_vision.recognize") as recognize:
            with self.assertRaisesRegex(RuntimeError, "does not support"):
                ScanWorker.provider("tr", "meikiocr")
        recognize.assert_not_called()

    def test_reusing_paddle_model_does_not_bypass_language_coverage(self):
        image = image_bytes()
        worker, sink = self.make_worker([
            (1, image, (.2, .5), "tr", ("paddle", "")),
            (2, image, (.2, .5), "ru", ("paddle", "")), None])
        provider = Mock(return_value=recognized())
        with patch("meikipop.dictionary.search.SearchEngine", return_value=Mock()), \
                patch.object(worker, "provider", return_value=provider):
            worker.run()
        provider.assert_called_once()
        self.assertIn("does not support", sink.emit.call_args_list[1].args[-1])

    def test_shared_paddle_uses_current_profile_character_geometry(self):
        result = {"rec_texts": ["中文"], "text_word": [["中", "文"]],
                  "text_word_boxes": [[(10, 10, 30, 30), (40, 10, 60, 30)]]}
        model = Mock()
        model.recognize.return_value = [result]
        scanner = PaddleScan(model, "tr")
        image = image_bytes()
        worker, sink = self.make_worker([
            (1, image, (.5, .4), "tr", ("paddle", "")),
            (2, image, (.5, .4), "cmn", ("paddle", "")), None])
        engine = Mock()
        engine.search.return_value = SimpleNamespace(entries=(), matched_length=0)
        with patch("meikipop.dictionary.search.SearchEngine", return_value=engine), \
                patch.object(worker, "provider", return_value=scanner) as factory:
            worker.run()
        factory.assert_called_once_with("tr", "paddle", "")
        self.assertEqual(model.recognize.call_count, 2)
        self.assertEqual([call.args[2].query for call in sink.emit.call_args_list], ["中文", "文"])

    def test_arabic_paddle_rejected_before_loading_latin_model(self):
        with patch("meikipop.ocr.turkish_paddle.LocalOCR") as factory:
            with self.assertRaisesRegex(RuntimeError, "does not support"):
                ScanWorker.provider("ar", "paddle")
        factory.assert_not_called()

    def test_unspaced_matched_prefix_highlight_uses_original_source_length(self):
        from meikipop.dictionary.search import SearchResult

        for language, text, term, matched, expected_end in [
            ("cmn", "你好猫", "你好", 2, 2),
            ("ja", "食べています", "食べる", 6, 1),
        ]:
            with self.subTest(language=language):
                sink = SimpleNamespace(emit=Mock())
                worker = HitWorker(sink)
                worker.queue = Queue()
                frame = SimpleNamespace(language=language, request=SimpleNamespace(revision=1))
                hit = ContextHit(text, text, 0, 1, language)
                worker.queue.put((1, frame, hit, False))
                worker.queue.put(None)
                engine = Mock()
                engine.search.return_value = SearchResult(text, language, "en", (SimpleNamespace(term=term),), matched_length=matched)
                with patch("meikipop.dictionary.search.SearchEngine", return_value=engine):
                    worker.run()
                delivered = sink.emit.call_args.args[2][1]
                self.assertEqual((delivered.query, delivered.text, delivered.start, delivered.end),
                                 (text, text, 0, expected_end))


class FakeWindow(QWidget):
    dictionaries_changed = pyqtSignal()
    ocr_enabled_changed = pyqtSignal(bool)
    mode_changed = pyqtSignal(str)
    scan_settings_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.search = QLineEdit(self)
        self.scan_toggle = QCheckBox(self)
        self.source = SimpleNamespace(currentData=lambda: "tr")
        self.preferred_foreign = "tr"
        self.is_pinned = False
        self.pin = QCheckBox(self)
        self.pin.toggled.connect(lambda checked: setattr(self, "is_pinned", checked))
        self._peek = True
        self._place = Mock()
        self.dismiss_button = QToolButton(self)
        self.show_message = Mock()
        self.show_entries = Mock(return_value=True)
        self.set_context = Mock()


class UnifiedOCRLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = FakeWindow()
        self.controller = UnifiedOCR(self.window)
        self.controller.enabled = self.controller.holding = True

    def tearDown(self):
        self.controller.shutdown()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def enable_hover(self):
        self.controller.holding = False
        self.controller.hover_enabled = True
        self.controller.hover_region = QRect(50, 50, 300, 150)
        self.controller.hover_screen = self.controller._screen_key(QApplication.primaryScreen())

    def test_hover_refreshes_stationary_area_every_half_second_without_overlapping_jobs(self):
        self.enable_hover()
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.gui.unified_ocr.monotonic", return_value=10) as clock, \
                patch.object(self.controller, "hit_latest") as hit, \
                patch.object(self.controller, "_request_capture") as capture:
            self.controller.scan()
            self.assertFalse(self.controller.freeze_capture)
            capture.assert_called_once()
            self.controller._last_capture_at = 10
            clock.return_value = 10.3
            self.controller.scan()
            capture.assert_called_once()
            clock.return_value = 10.5
            self.controller.busy = True
            self.controller.scan()
            capture.assert_called_once()
            self.controller.busy = False
            self.controller.scan()
            self.assertEqual(capture.call_count, 2)
            self.assertEqual(hit.call_count, 4)

    def test_hover_exit_rejects_old_results_and_shift_still_scans_outside(self):
        self.enable_hover()
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(self.controller, "_request_capture"):
            self.controller.scan()
        generation = self.controller.generation
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(400, 300)), \
                patch.object(self.controller, "_request_capture") as capture:
            self.controller.deliver(generation, Mock(), Mock(), "")
            self.window.show_entries.assert_not_called()
            self.controller.scan()
            capture.assert_not_called()
            self.controller.hold_changed(True)
            capture.assert_called_once()
            self.assertTrue(self.controller.freeze_capture)

    def test_hover_bounds_are_fixed_and_never_expand_for_clipped_context(self):
        self.enable_hover()
        point = QPoint(100, 100)
        self.controller._update_hover(point)
        screen = QApplication.primaryScreen()
        self.assertEqual(self.controller._capture_bounds(point, screen.geometry(), self.controller.hover_screen),
                         self.controller.hover_region)
        frame = SimpleNamespace(request=SimpleNamespace(revision=1))
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=point), \
                patch.object(self.controller, "hit_latest"), \
                patch("meikipop.ocr.boundaries.expanded_crop") as expand:
            self.controller.accept_frame(self.controller.generation, frame, "")
        expand.assert_not_called()

    def test_pinned_popup_and_menu_pause_hover(self):
        self.enable_hover()
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(self.controller, "_request_capture") as capture:
            self.window.is_pinned = True
            self.controller.scan()
            capture.assert_not_called()
            self.window.is_pinned = False
            with patch.object(QApplication, "activePopupWidget", return_value=Mock()):
                self.controller.scan()
                capture.assert_not_called()
            self.controller.scan()
            capture.assert_called_once()

    def test_cancelled_reselection_retains_area_and_invalidates_pending_work(self):
        self.enable_hover()
        old = self.controller.generation
        region = QRect(self.controller.hover_region)
        self.controller.busy = True
        def cancel(**options):
            self.assertEqual(options, {"logical": True})
            self.assertTrue(self.controller.session.suspended)
            self.assertFalse(self.controller.timer.isActive())
            self.assertFalse(self.controller.session.accepts(old))
            return None
        with patch("meikipop.gui.region_selector.RegionSelector.get_region", side_effect=cancel):
            self.assertFalse(self.controller.select_scan_area())
        self.assertEqual(self.controller.hover_region, region)
        self.assertTrue(self.controller.timer.isActive())
        self.assertFalse(self.controller.session.suspended)
        self.assertGreater(self.controller.generation, old)
        self.assertFalse(self.controller.busy)

    def test_reselection_replaces_area_and_display_changes_pause_hover(self):
        self.enable_hover()
        replacement = QRect(400, 200, 100, 50)
        with patch("meikipop.gui.region_selector.RegionSelector.get_region", return_value=replacement):
            self.assertTrue(self.controller.select_scan_area())
        self.assertEqual(self.controller.hover_region, replacement)
        self.controller._update_hover(replacement.center())
        self.assertTrue(self.controller.session.scanning())
        self.controller.hover_screen = ("removed display",)
        self.controller._update_hover(replacement.center())
        self.assertFalse(self.controller.session.scanning())

    def test_selector_retains_logical_and_physical_coordinates_for_mixed_dpi(self):
        from meikipop.gui.region_selector import RegionSelector
        with patch("pynput.mouse.Controller") as mouse, \
                patch("meikipop.gui.region_selector.QCursor.pos", return_value=QPoint(0, 0)) as cursor:
            mouse.return_value.position = (1000, 200)
            selector = RegionSelector()
            selector.mousePressEvent(None)
            cursor.return_value = QPoint(200, 100)
            mouse.return_value.position = (1300, 350)
            selector.mouseReleaseEvent(None)
            self.assertEqual(selector.logical_selection_rect, QRect(0, 0, 201, 101))
            self.assertEqual(selector.selection_rect, QRect(1000, 200, 301, 151))
            selector.deleteLater()

    def test_tray_enable_cancel_is_unchecked_and_reselection_is_disabled(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu()
        before = menu.addAction("Settings")
        self.controller.holding = False
        self.controller.add_tray_actions(menu, before)
        hover, area, _ = menu.actions()
        self.assertFalse(hover.isChecked())
        self.assertFalse(area.isEnabled())
        with patch("meikipop.gui.region_selector.RegionSelector.get_region", return_value=None):
            hover.trigger()
            self.app.processEvents()
        menu.aboutToShow.emit()
        self.assertFalse(hover.isChecked())
        self.assertFalse(self.controller.hover_enabled)
        self.assertFalse(area.isEnabled())
        menu.deleteLater()

    def test_visible_manual_search_pauses_hover(self):
        self.enable_hover()
        self.window._peek = False
        self.window.show()
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(self.controller, "_request_capture") as capture:
            self.controller.scan()
        capture.assert_not_called()
        self.assertFalse(self.controller.session.scanning())

    def test_macos_hidden_search_with_stale_focus_allows_hover_scan(self):
        self.enable_hover()
        self.window._peek = False
        with patch("meikipop.gui.unified_ocr.sys.platform", "darwin"), \
                patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(QApplication, "activeWindow", return_value=self.window), \
                patch.object(self.controller, "_request_capture") as capture:
            self.controller.scan()
        capture.assert_called_once()

    def test_hover_can_run_with_all_scan_shortcuts_disabled(self):
        self.enable_hover()
        self.controller.input = SimpleNamespace(activation=Mock(), pin_ready=threading.Event(),
                                               pin_pending=threading.Event(), shutdown=Mock(),
                                               set_pin_shortcut=Mock())
        self.window.settings = SimpleNamespace(value=lambda name, default, kind=None:
                                             "" if name.endswith("/scan_bindings") else default)
        self.controller.reload_settings()
        self.assertTrue(self.controller.enabled)
        self.controller.input.activation.set_bindings.assert_called_once_with("")
        self.controller.set_hover_enabled(False)
        self.assertFalse(self.controller.enabled)

    def test_hover_dismissal_stays_closed_until_pointer_leaves_and_returns(self):
        self.enable_hover()
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(self.controller, "_request_capture") as capture:
            self.controller.scan()
            self.controller.dismiss()
            self.controller.scan()
            capture.assert_called_once()
            self.assertTrue(self.controller.timer.isActive())
            with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(400, 300)):
                self.controller.scan()
            self.controller.scan()
            self.assertEqual(capture.call_count, 2)

    def test_programmatic_search_invalidates_pending_ocr(self):
        generation = self.controller.generation
        self.window.search.setText("typed lookup")
        self.assertGreater(self.controller.generation, generation)
        with patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.deliver(generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()
        self.window.set_context.assert_not_called()

    def test_old_frame_completion_cannot_unlock_new_capture(self):
        old = self.controller.generation
        self.controller.busy = True
        self.controller.invalidate()
        self.controller.busy = True
        self.controller.accept_frame(old, None, "obsolete error")
        self.assertTrue(self.controller.busy)
        self.window.show_message.assert_not_called()

    def test_cancelled_capture_clears_temporary_hide_without_touching_new_work(self):
        old = self.controller.generation
        self.controller._capture_hidden = self.window._capture_visibility = True
        self.controller.invalidate()
        self.assertFalse(self.controller._capture_hidden)
        self.assertFalse(self.window._capture_visibility)
        self.controller.busy = True
        self.controller.capture(old, QPoint(10, 10))
        self.assertTrue(self.controller.busy)

    def test_fresh_hold_from_pinned_result_is_not_a_user_dismissal(self):
        self.controller.input = SimpleNamespace(visible=threading.Event(), pin_ready=threading.Event(),
                                               pin_pending=threading.Event(), shutdown=Mock())
        self.window.show()
        self.window.pin.setChecked(True)
        self.controller.holding = False
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(self.controller, "scan") as scan:
            self.controller.hold_changed(True)
            self.assertFalse(self.window.is_pinned)
            self.assertTrue(self.controller.holding)
            self.assertFalse(self.controller._dismissed_hold)
            scan.assert_called_once()

    def test_boundary_recovery_looks_up_each_frame_before_two_retries(self):
        frame = SimpleNamespace(request=SimpleNamespace(revision=1))
        events = []
        with patch.object(self.controller, "_valid_frame", return_value=True), \
                patch("meikipop.ocr.boundaries.expanded_crop", return_value=(0, 0, 1800, 720)), \
                patch.object(self.controller, "_request_capture", side_effect=lambda *args: events.append("capture")) as capture, \
                patch.object(self.controller, "hit_latest", side_effect=lambda *args: events.append("hit")) as hit:
            for _ in range(4):
                self.controller.accept_frame(self.controller.generation, frame, "")
            self.assertEqual(capture.call_count, 2)
            self.assertEqual(hit.call_count, 4)
            self.assertEqual(events, ["hit", "capture", "hit", "capture", "hit", "hit"])
            self.controller.invalidate()
            self.assertEqual(self.controller._crop_retries, 0)

    def test_stale_or_pinned_delivery_preserves_context(self):
        self.controller.deliver(-1, Mock(), Mock(), "")
        self.window.is_pinned = True
        self.controller.deliver(self.controller.generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()
        self.window.set_context.assert_not_called()

    def test_active_manual_search_cannot_be_replaced_by_ocr(self):
        self.window._peek = False
        self.window.show()
        with patch.object(QApplication, "activeWindow", return_value=self.window):
            self.controller.deliver(self.controller.generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()

    def test_macos_hidden_search_with_stale_active_window_accepts_ocr(self):
        self.window._peek = False
        with patch("meikipop.gui.unified_ocr.sys.platform", "darwin"), \
                patch.object(QApplication, "activeWindow", return_value=self.window):
            self.controller.deliver(self.controller.generation, Mock(entries=(Mock(),)),
                                    ContextHit("kitap", "kitap ev", 0, 5), "")
        self.window.show_entries.assert_called_once()

    def test_windows_active_search_guard_is_preserved_when_hidden(self):
        self.window._peek = False
        with patch("meikipop.gui.unified_ocr.sys.platform", "win32"), \
                patch.object(QApplication, "activeWindow", return_value=self.window):
            self.controller.deliver(self.controller.generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()

    def test_ocr_miss_hides_previous_preview_without_ending_hold(self):
        from meikipop.dictionary.search import SearchResult
        self.window.show()
        with patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.deliver(self.controller.generation, SearchResult("unknown", "tr", "en"),
                                    ContextHit("unknown", "unknown text", 0, 7), "")
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.controller.holding)
        self.assertFalse(self.controller._dismissed_hold)
        self.window.show_entries.assert_not_called()
        self.window.set_context.assert_not_called()
        with patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.deliver(self.controller.generation, Mock(entries=(Mock(),)),
                                    ContextHit("kitap", "kitap ev", 0, 5), "")
        self.window.show_entries.assert_called_once()

    def test_rejected_popup_update_does_not_replace_sentence(self):
        self.window.show_entries.return_value = False
        with patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.deliver(self.controller.generation, Mock(), ContextHit("kitap", "kitap ev", 0, 5), "")
        self.window.show_entries.assert_called_once()
        self.window.set_context.assert_not_called()

    def test_release_timer_hides_only_unpinned_ocr_peeks(self):
        self.controller.holding = False
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(self.window, "hide") as hide:
            self.window._peek = False
            self.controller.finish_peek()
            hide.assert_not_called()
            self.window._peek = True
            self.controller.finish_peek()
            hide.assert_called_once_with()

    def test_entry_and_exit_rearm_preview_grace(self):
        from PyQt6.QtCore import QEvent
        self.controller.holding = False
        self.controller.leave_timer.start()
        self.controller.eventFilter(self.window, QEvent(QEvent.Type.Enter))
        self.assertFalse(self.controller.leave_timer.isActive())
        self.controller.eventFilter(self.window, QEvent(QEvent.Type.Leave))
        self.assertTrue(self.controller.leave_timer.isActive())
        self.window.pin.setChecked(True)
        self.controller.eventFilter(self.window, QEvent(QEvent.Type.Leave))
        self.assertFalse(self.controller.leave_timer.isActive())

    def test_escape_visibility_follows_show_and_hide(self):
        self.controller.input = SimpleNamespace(visible=threading.Event(), shutdown=Mock())
        self.window.show()
        self.assertTrue(self.controller.input.visible.is_set())
        self.window.hide()
        self.assertFalse(self.controller.input.visible.is_set())

    def test_dismiss_does_not_reopen_until_activation_is_released(self):
        self.controller.dismiss()
        with patch.object(self.controller, "scan") as scan:
            self.controller.hold_changed(True)
            scan.assert_not_called()
            self.controller.hold_changed(False)
            self.controller.hold_changed(True)
            scan.assert_called_once_with()

    def test_permission_failure_unchecks_scan_and_keeps_text_search_available(self):
        with patch("meikipop.gui.unified_ocr.sys.platform", "darwin"), \
                patch("meikipop.utils.macos.require_screen_capture_permission", side_effect=RuntimeError("Screen Recording")):
            self.controller.set_enabled(True)
        self.assertFalse(self.controller.enabled)
        self.assertFalse(self.window.scan_toggle.isChecked())
        self.assertTrue(self.window.search.isEnabled())
        self.window.show_message.assert_called_once_with("Screen Recording")

    def test_startup_requests_screen_permission_only_for_enabled_scan(self):
        for bindings in ("shift", ""):
            with self.subTest(bindings=bindings):
                window = FakeWindow()
                window.settings = Mock()
                window.settings.value.side_effect = lambda key, default=None, *args: (
                    bindings if key.endswith("/scan_bindings") else default)
                with patch("meikipop.gui.unified_ocr.sys.platform", "darwin"), \
                        patch("meikipop.utils.macos.require_screen_capture_permission",
                              side_effect=RuntimeError("Screen Recording")) as permission:
                    controller = UnifiedOCR(window)
                if bindings:
                    permission.assert_called_once_with(request_access=True)
                else:
                    permission.assert_not_called()
                controller.shutdown()
                window.deleteLater()

    def test_capture_bounds_remain_stable_for_nearby_words(self):
        geometry = QRect(0, 0, 1920, 1080)
        first = self.controller._capture_bounds(QPoint(800, 500), geometry, ("display", 1.0))
        nearby = self.controller._capture_bounds(QPoint(830, 520), geometry, ("display", 1.0))
        self.assertEqual(first, nearby)
        edge = QPoint(first.right() - 10, first.center().y())
        shifted = self.controller._capture_bounds(edge, geometry, ("display", 1.0))
        self.assertNotEqual(first, shifted)
        self.assertTrue(shifted.contains(edge))

    def test_pointer_retest_skips_capture_until_frame_expires(self):
        from meikipop.ocr.frames import RecognizedFrame
        from meikipop.utils.capture import CaptureRequest
        controller = self.controller
        controller.freeze_while_held = False
        controller.capture_region = QRect(0, 0, 400, 200)
        controller._last_capture_at = 10
        controller.worker = SimpleNamespace(queue=Queue(), stop=Mock(), join=Mock())
        controller.hit_worker = SimpleNamespace(queue=Queue(), stop=Mock(), join=Mock())
        screen = QApplication.primaryScreen()
        geometry = screen.geometry()
        request = CaptureRequest(1, screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), controller.generation)
        controller.frame = RecognizedFrame(request, tuple(recognized()), "tr", (), 1, 10)
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.gui.unified_ocr.monotonic", return_value=10.05) as clock, \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot") as capture:
            controller.scan()
            capture.assert_not_called()
            self.assertEqual(controller.hit_worker.queue.get_nowait()[2].query, "kitap")
            self.assertTrue(controller.worker.queue.empty())
            controller.busy = False
            controller.last_point = QPoint(100, 100)
            clock.return_value = 10.3
            controller.scan()
            capture.assert_called_once()

    def test_capture_exclusion_is_reused_and_restored_when_pinned(self):
        self.window.show()
        self.controller._capture_excluded = True
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.utils.capture.exclude_from_capture", return_value=True) as exclude, \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot"):
            self.controller.scan()
            exclude.assert_not_called()
            self.window.pin.setChecked(True)
            exclude.assert_called_once_with(self.window, False)

    def test_supported_capture_excludes_popup_without_hiding_it(self):
        self.window.show()
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.utils.capture.exclude_from_capture", return_value=True) as exclude, \
                patch.object(self.window, "hide") as hide, \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot") as dispatch:
            self.controller.scan()
            hide.assert_not_called()
            self.assertTrue(self.window.isVisible())
            self.assertEqual(dispatch.call_args.args[0], 0)
            self.controller.restore_capture_visibility()
            self.assertEqual([c.args[1] for c in exclude.call_args_list], [True, False])

    def test_new_scan_replaces_pinned_result(self):
        self.window.show()
        self.window.pin.setChecked(True)
        self.controller.holding = False
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(self.controller, "scan") as scan:
            self.controller.hold_changed(True)
            self.assertFalse(self.window.is_pinned)
            scan.assert_called_once()

    def test_explicit_scan_outside_focused_search_resumes_ocr(self):
        self.window._peek = False
        self.window.show()
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(QApplication, "activeWindow", return_value=self.window), \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot") as dispatch:
            self.controller.scan()
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.controller.busy)
        dispatch.assert_called_once()

    def test_search_keeps_focus_for_inside_trigger_and_automatic_scan(self):
        self.window._peek = False
        self.window.show()
        with patch.object(QApplication, "activeWindow", return_value=self.window), \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot") as dispatch:
            with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=self.window.geometry().center()):
                self.controller.scan()
            self.controller.holding = False
            self.controller.auto_scan = True
            with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)):
                self.controller.scan()
        self.assertTrue(self.window.isVisible())
        dispatch.assert_not_called()

    def test_active_ocr_preview_stays_visible_during_held_scan(self):
        self.window.show()
        self.controller.busy = True
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(QApplication, "activeWindow", return_value=self.window):
            self.controller.scan()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.controller.holding)

    def test_active_ocr_preview_accepts_new_results(self):
        self.window.show()
        result = SimpleNamespace(entries=[Mock()], text="kitap", source="tr", kanji=[])
        hit = ContextHit("kitap", "kitap", 0, 5)
        with patch.object(QApplication, "activeWindow", return_value=self.window):
            self.controller.deliver(self.controller.generation, result, hit, "")
        self.window.show_entries.assert_called_once_with(result.entries, text="kitap", source="tr",
                                                         peek=True, kanji=[])

    def test_ocr_keeps_suggestions_and_grammar_without_a_definition(self):
        from meikipop.dictionary.search import SearchResult
        from meikipop.language.turkish_analyzer import TrAnalysis
        hit = ContextHit('cevrimizi', 'cevrimizi', 0, 9, 'tr')
        result = SearchResult('cevrimizi', 'tr', 'en', analyses=(TrAnalysis('cevir', 'NOUN'),),
                              message='No dictionary entry.')
        with patch.object(QApplication, 'activeWindow', return_value=None):
            self.controller.deliver(self.controller.generation, result, hit, '')
        self.assertEqual(self.window.show_entries.call_args.kwargs['analyses'], result.analyses)
        result = SearchResult('kitpa', 'tr', 'en', suggestions=('kitap',))
        with patch.object(QApplication, 'activeWindow', return_value=None):
            self.controller.deliver(self.controller.generation, result, hit, '')
        self.assertEqual(self.window.show_entries.call_args.kwargs['suggestions'], ('kitap',))

    def test_outside_click_dismisses_pinned_popup(self):
        self.window.show()
        self.window.pin.setChecked(True)
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)):
            self.controller.outside_click()
        self.assertFalse(self.window.isVisible())

    def test_empty_scan_bindings_disable_ocr_without_affecting_search(self):
        values = {"profiles/tr/scan_bindings": ""}
        self.window.settings = SimpleNamespace(value=lambda name, default, kind=None: values.get(name, default))
        self.controller.reload_settings()
        self.assertFalse(self.controller.enabled)
        self.assertTrue(self.window.search.isEnabled())

    def test_capture_bounds_reset_for_mode_screen_and_scale_changes(self):
        geometry = QRect(0, 0, 1920, 1080)
        point = QPoint(800, 500)
        first = self.controller._capture_bounds(point, geometry, ("display", 1.0))
        self.window.mode_changed.emit("ja")
        self.assertIsNone(self.controller.capture_region)
        self.controller._capture_bounds(point, geometry, ("display", 1.0))
        second = self.controller._capture_bounds(point + QPoint(20, 0), geometry, ("display", 2.0))
        self.assertNotEqual(first, second)
        monitor = QRect(-1920, 0, 1920, 1080)
        third = self.controller._capture_bounds(QPoint(-900, 500), monitor, ("other", 2.0))
        self.assertTrue(monitor.contains(third))
        self.assertTrue(third.contains(QPoint(-900, 500)))

    def test_preview_stays_anchored_while_pointer_moves_and_inference_runs(self):
        self.window.show()
        self.controller.busy = True
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.follow_cursor()
            self.window._place.assert_not_called()
            self.window.pin.setChecked(True)
            self.controller.follow_cursor()
            self.window._place.assert_not_called()
            self.controller.hold_changed(False)
            self.controller.finish_peek()
        self.assertTrue(self.window.isVisible())

    def test_pending_pin_wins_over_key_release_and_stale_ocr(self):
        self.window.show()
        generation = self.controller.generation
        self.controller.hold_changed(False)
        self.controller.pin_requested()
        self.assertTrue(self.window.is_pinned)
        self.assertFalse(self.controller.leave_timer.isActive())
        self.controller.deliver(generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()
        self.window.set_context.assert_not_called()

    def test_manual_result_never_follows_or_accepts_global_pin(self):
        self.window.show()
        self.window._peek = False
        with patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.follow_cursor()
            self.controller.pin_requested()
        self.window._place.assert_not_called()
        self.assertFalse(self.window.is_pinned)

    def test_scanning_requires_held_trigger_even_with_legacy_hover_flag(self):
        self.controller.holding = False
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.gui.unified_ocr.monotonic", return_value=10) as clock, \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot") as capture:
            self.controller.scan()
            capture.assert_not_called()
            self.controller.auto_scan = True
            self.controller.scan()
            capture.assert_not_called()
            clock.return_value = 12
            self.controller.scan()
            capture.assert_not_called()

    def test_dismissed_scan_requires_release_and_new_trigger(self):
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)) as cursor, \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.gui.unified_ocr.monotonic", return_value=10) as clock, \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot") as capture:
            self.controller.dismiss()
            self.controller.scan()
            clock.return_value = 15
            self.controller.scan()
            capture.assert_not_called()
            cursor.return_value = QPoint(-150, -100)
            self.controller.scan()
            capture.assert_not_called()
            clock.return_value = 15.4
            self.controller.scan()
            capture.assert_not_called()
            self.controller.hold_changed(False)
            self.controller.hold_changed(True)
            self.assertEqual(capture.call_count, 1)

    def test_capture_restores_previous_preview_while_worker_runs(self):
        self.controller.freeze_while_held = False
        self.window.show()
        self.controller._capture_hidden = True
        self.window.hide()
        screen = Mock()
        screen.geometry.return_value = QRect(0, 0, 100, 50)
        screen.name.return_value = "fixture"
        from PyQt6.QtGui import QPixmap
        pixmap = QPixmap(100, 50)
        pixmap.fill()
        screen.grabWindow.return_value = pixmap
        self.controller.worker = SimpleNamespace(queue=Queue(), stop=Mock(), join=Mock())
        with patch.object(QApplication, "screenAt", return_value=screen), \
                patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.capture(self.controller.generation, QPoint(50, 25))
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.controller.worker.queue.qsize(), 1)
        self.assertIsInstance(self.controller.worker.queue.get_nowait()[1], QImage)

    def test_pin_during_capture_gap_restores_preview_and_rejects_pending_capture(self):
        self.controller.input = SimpleNamespace(visible=threading.Event(), pin_ready=threading.Event(),
                                                pin_pending=threading.Event(), shutdown=Mock())
        self.window.show()
        generation = self.controller.generation
        self.controller._capture_hidden = True
        self.window.hide()
        self.controller._sync_pin_ready()
        self.assertTrue(self.controller.input.visible.is_set())
        self.assertTrue(self.controller.input.pin_ready.is_set())
        self.controller.pin_requested()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.is_pinned)
        with patch.object(QApplication, "screenAt") as capture:
            self.controller.capture(generation, QPoint(0, 0))
        capture.assert_not_called()
        self.assertTrue(self.window.isVisible())

    def test_modal_settings_prevent_global_pinning(self):
        self.controller.input = SimpleNamespace(visible=threading.Event(), pin_ready=threading.Event(),
                                                pin_pending=threading.Event(), shutdown=Mock())
        self.window.show()
        with patch.object(QApplication, "activeModalWidget", return_value=Mock()):
            self.controller._sync_pin_ready()
            self.assertFalse(self.controller.input.pin_ready.is_set())
            self.controller.pin_requested()
        self.assertFalse(self.window.is_pinned)

    def test_close_button_suppresses_reopen_for_current_hold(self):
        self.window.show()
        self.window.dismiss_button.click()
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.controller._dismissed_hold)
        with patch.object(self.controller, "scan") as scan:
            self.controller.hold_changed(True)
        scan.assert_not_called()

    def test_provider_setting_change_invalidates_inflight_result(self):
        values = {f"profiles/{self.window.preferred_foreign}/ocr_provider": "screenai", "screenai_directory": "local/component"}
        self.window.settings = SimpleNamespace(value=lambda name, default, kind=None: values.get(name, default))
        generation = self.controller.generation
        self.window.scan_settings_changed.emit()
        self.assertGreater(self.controller.generation, generation)
        self.assertEqual((self.controller.profile_ocr_provider, self.controller.screenai_directory),
                         ("screenai", "local/component"))
        self.controller.deliver(generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()


if __name__ == "__main__":
    unittest.main()
