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

from meikipop.gui.unified_ocr import ScanWorker, UnifiedOCR
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


class FakeWindow(QWidget):
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

    def test_programmatic_search_invalidates_pending_ocr(self):
        generation = self.controller.generation
        self.window.search.setText("typed lookup")
        self.assertGreater(self.controller.generation, generation)
        with patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.deliver(generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()
        self.window.set_context.assert_not_called()

    def test_stale_or_pinned_delivery_preserves_context(self):
        self.controller.deliver(-1, Mock(), Mock(), "")
        self.window.is_pinned = True
        self.controller.deliver(self.controller.generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()
        self.window.set_context.assert_not_called()

    def test_active_manual_search_cannot_be_replaced_by_ocr(self):
        with patch.object(QApplication, "activeWindow", return_value=self.window):
            self.controller.deliver(self.controller.generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()

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
        controller = self.controller
        controller.capture_region = QRect(0, 0, 400, 200)
        controller._last_capture_at = 10
        controller.worker = SimpleNamespace(queue=Queue(), stop=Mock(), join=Mock())
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(100, 100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("meikipop.gui.unified_ocr.monotonic", return_value=10.05) as clock, \
                patch("meikipop.gui.unified_ocr.QTimer.singleShot") as capture:
            controller.scan()
            capture.assert_not_called()
            self.assertIsNone(controller.worker.queue.get_nowait()[1])
            controller.busy = False
            controller.last_point = QPoint(120, 100)
            clock.return_value = 10.2
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

    def test_cursor_follow_is_independent_of_inference_and_stops_when_pinned(self):
        self.window.show()
        self.controller.busy = True
        with patch("meikipop.gui.unified_ocr.QCursor.pos", return_value=QPoint(-100, -100)), \
                patch.object(QApplication, "activeWindow", return_value=None):
            self.controller.follow_cursor()
            self.window._place.assert_called_once_with()
            self.window.pin.setChecked(True)
            self.controller.follow_cursor()
            self.window._place.assert_called_once_with()
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

    def test_hover_is_opt_in_waits_for_dwell_and_limits_repeat_capture(self):
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
            clock.return_value = 10.36
            self.controller.scan()
            self.assertEqual(capture.call_count, 1)
            self.controller.busy = False
            clock.return_value = 10.8
            self.controller.scan()
            self.assertEqual(capture.call_count, 1)
            clock.return_value = 11.4
            self.controller.scan()
            self.assertEqual(capture.call_count, 2)

    def test_hover_dismissal_waits_for_pointer_move_and_new_dwell(self):
        self.controller.holding = False
        self.controller.auto_scan = True
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
            self.assertEqual(capture.call_count, 1)

    def test_capture_restores_previous_preview_while_worker_runs(self):
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
        values = {"ja_ocr_provider": "screenai", "screenai_directory": "local/component"}
        self.window.settings = SimpleNamespace(value=lambda name, default, kind=None: values.get(name, default))
        generation = self.controller.generation
        self.window.scan_settings_changed.emit()
        self.assertGreater(self.controller.generation, generation)
        self.assertEqual((self.controller.ja_ocr_provider, self.controller.screenai_directory),
                         ("screenai", "local/component"))
        self.controller.deliver(generation, Mock(), Mock(), "")
        self.window.show_entries.assert_not_called()


if __name__ == "__main__":
    unittest.main()
