"""Optional local OCR for the shared popup; no inference on the Qt thread."""
from dataclasses import replace
import sys
import threading
from time import monotonic

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QImage
from PyQt6.QtWidgets import QApplication

from meikipop.ocr.context import hit_paragraphs, paddle_paragraphs
from meikipop.ocr.scan_cache import ScanCache
from meikipop.ocr.frames import RecognizedFrame
from meikipop.utils.lastest_queue import LatestValueQueue
from meikipop.utils.capture import CaptureRequest, PixelFrame, RegionCapture
from meikipop.utils.timing import mark
from meikipop.gui.lookup_session import LookupSession


class ScanWorker(threading.Thread):
    def __init__(self, completed, directory=None, frames=None):
        super().__init__(daemon=True, name="UnifiedOCR")
        self.completed = completed
        self.directory = directory
        self.frames = frames
        self.queue = LatestValueQueue()
        self._stopped = threading.Event()
        self._generation = None
        self._frozen = None

    def invalidate(self, generation):
        self._generation = generation
        self._frozen = None

    def _obsolete(self, generation):
        return self.frames is not None and self._generation is not None and generation != self._generation

    def stop(self):
        self._stopped.set()
        self._frozen = None
        self.queue.put(None)

    def refresh(self):
        self.queue.put("refresh")

    def _emit(self, *args):
        if self._stopped.is_set():
            return
        try:
            self.completed.emit(*args)
        except RuntimeError:
            pass  # The Qt receiver may be gone after a long native inference.

    def run(self):
        from PIL import Image
        from meikipop.dictionary.search import SearchEngine
        engine = None
        capture = None
        providers, caches = {}, {}
        try:
            while True:
                job = self.queue.get()
                if job is None or self._stopped.is_set():
                    return
                if job == "refresh":
                    if engine:
                        engine.refresh()
                    continue
                generation, pixels, point, language, *options = job
                capture_request = pixels if isinstance(pixels, CaptureRequest) else (
                    pixels.request if isinstance(pixels, PixelFrame) else options[2] if len(options) > 2 else None)
                mark("ocr_dequeue", capture_request.revision if capture_request else generation)
                capture_phase = False
                try:
                    if self._obsolete(generation):
                        self.frames.emit(generation, None, "")
                        continue
                    if engine is None and self.frames is None:
                        engine = SearchEngine(self.directory)
                    selection = tuple(options[0]) if options else ()
                    provider_key = (language, *selection)
                    if provider_key not in providers:
                        providers[provider_key] = self.provider(language, *selection)
                        caches[provider_key] = ScanCache()
                    if self._obsolete(generation):
                        self.frames.emit(generation, None, "")
                        continue
                    if pixels is None:
                        paragraphs = caches[provider_key].result
                    else:
                        if isinstance(pixels, CaptureRequest):
                            capture_phase = True
                            mark("capture_begin", pixels.revision)
                            if capture is None:
                                capture = RegionCapture()
                            if pixels.frozen:
                                key = (pixels.generation, pixels.screen, pixels.geometry, pixels.scale)
                                frozen = self._frozen
                                if frozen is None or frozen[0] != key:
                                    snapshot = capture.capture(replace(pixels, crop=pixels.geometry))
                                    if self._obsolete(generation):
                                        self.frames.emit(generation, None, "")
                                        continue
                                    self._frozen = frozen = (key, snapshot)
                                pixels = frozen[1].cropped(pixels)
                            else:
                                pixels = capture.capture(pixels)
                            capture_phase = False
                            mark("capture_done", pixels.request.revision)
                        if isinstance(pixels, PixelFrame):
                            image = pixels.image()
                        else:
                            pixels = pixels.convertToFormat(QImage.Format.Format_RGB888)
                            image = Image.frombytes("RGB", (pixels.width(), pixels.height()),
                                                    pixels.constBits().asstring(pixels.sizeInBytes()),
                                                    "raw", "RGB", pixels.bytesPerLine())
                        mark("pixels_ready", generation)
                        paragraphs = caches[provider_key].scan(image, providers[provider_key])
                        mark("ocr_done", generation)
                    if self._stopped.is_set():
                        return
                    if self.frames is not None:
                        request = pixels.request if isinstance(pixels, PixelFrame) else options[2]
                        captured_at = pixels.captured_at if isinstance(pixels, PixelFrame) else options[3]
                        frame = RecognizedFrame(request, tuple(replace(p, words=tuple(p.words)) for p in paragraphs or ()),
                                                language, selection, caches[provider_key].revision, captured_at,
                                                image.size, pixels.physical_crop if isinstance(pixels, PixelFrame) else ())
                        self.frames.emit(generation, frame, "")
                        continue
                    hit = hit_paragraphs(paragraphs, point, language)
                    if hit is None:
                        self._emit(generation, None, None, "")
                        continue
                    engine.refresh_if_changed()
                    morphology = bool(options[1]) if len(options) > 1 else False
                    analysis = {"morphology": True, "context": (hit.text, hit.start, hit.end)} if morphology else {}
                    result = engine.search(hit.query, source=language, foreign=language, **analysis)
                    # A Japanese lookup can cover several recognized character boxes.
                    if language == "ja" and result.entries:
                        surface = result.entries[0].term
                        if hit.text.startswith(surface, hit.start):
                            hit = replace(hit, end=hit.start + len(surface))
                    self._emit(generation, result, hit, "")
                except Exception as error:
                    detail = str(error).strip() or type(error).__name__
                    if self.frames is not None and not self._stopped.is_set():
                        try:
                            self.frames.emit(generation, pixels if capture_phase else None, detail[:300])
                        except RuntimeError:
                            pass
                    else:
                        self._emit(generation, None, None, detail[:300])
        finally:
            self._frozen = None
            if engine:
                engine.close()
            if capture:
                capture.close()

    @staticmethod
    def provider(language, selected=None, component_directory=""):
        from meikipop.language.support import PADDLE_LANGUAGES, default_ocr_provider
        selected = selected or default_ocr_provider(language)
        if selected == "screenai":
            from meikipop.ocr.providers.screenai.provider import ScreenAiOcr
            return ScreenAiOcr(component_directory or None, language=language).scan
        if selected == "paddle":
            if language not in PADDLE_LANGUAGES:
                raise RuntimeError("This Paddle model does not support this language. Choose Chrome Screen AI in Settings → OCR.")
            from meikipop.ocr.turkish_paddle import LocalOCR
            import numpy as np
            provider = LocalOCR()
            return lambda image: paddle_paragraphs(provider.recognize(np.asarray(image)[:, :, ::-1].copy()), *image.size)
        if language == "ja":
            selected = selected or ("vision" if sys.platform == "darwin" else "meikiocr")
            if selected == "vision":
                if sys.platform != "darwin":
                    raise RuntimeError("Apple Vision is available only on macOS.")
                from meikipop.ocr.macos_vision import recognize
                return lambda image: recognize(image, language)
            if selected != "meikiocr":
                raise RuntimeError("Choose a Japanese OCR provider in Settings → Screen lookup.")
            try:
                from meikipop.ocr.providers.meikiocr.provider import MeikiOcrProvider
            except ImportError as error:
                raise RuntimeError("Install Japanese OCR dependencies in Settings before scanning.") from error
            provider = MeikiOcrProvider(execution_provider="CPUExecutionProvider")
            if provider.ocr_client is None:
                raise RuntimeError("Japanese OCR could not start. Check its local model installation.")
            return provider.scan
        if sys.platform == "darwin" and selected != "paddle":
            from meikipop.ocr.macos_vision import recognize
            return lambda image: recognize(image, language)
        if language == "tr":
            from meikipop.ocr.turkish_paddle import LocalOCR
            import numpy as np
            provider = LocalOCR()
            return lambda image: paddle_paragraphs(provider.recognize(np.asarray(image)[:, :, ::-1].copy()), *image.size)
        raise RuntimeError("Screen OCR is available for Japanese and Turkish here. Other languages support text lookup.")


class HitWorker(threading.Thread):
    def __init__(self, completed, directory=None):
        super().__init__(daemon=True, name="OCRDictionary")
        self.completed, self.directory = completed, directory
        self.queue = LatestValueQueue()
        self.stopped = threading.Event()
        self.refresh_needed = threading.Event()
        self.generation = None

    def invalidate(self, generation):
        self.generation = generation

    def refresh(self):
        self.refresh_needed.set()
        self.queue.put("refresh")

    def stop(self):
        self.stopped.set()
        self.queue.put(None)

    def run(self):
        from meikipop.dictionary.search import SearchEngine
        engine = None
        try:
            while not self.stopped.is_set():
                job = self.queue.get()
                if job is None or self.stopped.is_set():
                    return
                generation, frame, hit, morphology = job if job != "refresh" else (-1, None, None, False)
                try:
                    if job != "refresh" and self.generation is not None and generation != self.generation:
                        continue
                    if engine is None:
                        engine = SearchEngine(self.directory)
                    if self.refresh_needed.is_set():
                        self.refresh_needed.clear()
                        engine.refresh()
                    if job == "refresh":
                        continue
                    mark("hit_lookup_begin", frame.request.revision)
                    options = {"morphology": True, "context": (hit.text, hit.start, hit.end)} if morphology else {}
                    result = engine.search(hit.query, source=frame.language, foreign=frame.language, **options)
                    if frame.language == "ja" and result.entries:
                        surface = result.entries[0].term
                        if hit.text.startswith(surface, hit.start):
                            hit = replace(hit, end=hit.start + len(surface))
                    mark("hit_lookup_done", frame.request.revision)
                    if not self.stopped.is_set():
                        self.completed.emit(generation, result, (frame, hit), "")
                except Exception as error:
                    if not self.stopped.is_set():
                        try:
                            self.completed.emit(generation, None, (frame, hit) if job != "refresh" else None, str(error)[:300])
                        except RuntimeError:
                            pass
        finally:
            if engine:
                engine.close()


class UnifiedOCR(QObject):
    completed = pyqtSignal(int, object, object, str)
    frame_ready = pyqtSignal(int, object, str)

    def __init__(self, window):
        super().__init__(window)
        self.session = LookupSession()
        self.window = window
        self.input = None
        self.worker = None
        self.hit_worker = None
        self.frame = None
        self._hit_key = None
        self._last_dictionary_at = 0
        self.pin_gesture = "left"
        self._last_scan_at = 0
        self._last_capture_at = 0
        self._capture_hidden = False
        self._capture_excluded = False
        self.last_point = None
        self.job_point = None
        self.capture_region = None
        self.capture_screen = None
        self._capture_revision = 0
        self._fallback_capture = False
        self._crop_retries = 0
        self.freeze_while_held = False
        self._frozen_pixels = None
        self._frozen_screen = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.scan)
        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.setInterval(450)
        self.leave_timer.timeout.connect(self.finish_peek)
        self.completed.connect(self.deliver)
        self.frame_ready.connect(self.accept_frame)
        window.ocr_enabled_changed.connect(self.set_enabled)
        window.mode_changed.connect(lambda _: self.invalidate())
        window.dictionaries_changed.connect(self.refresh_library)
        window.search.textChanged.connect(lambda _: self.invalidate())
        if hasattr(window, "scan_settings_changed"):
            window.scan_settings_changed.connect(self.reload_settings)
        if hasattr(window, "pin"):
            window.pin.toggled.connect(self.pin_changed)
        if hasattr(window, "dismiss_button"):
            window.dismiss_button.clicked.connect(self.dismiss)
        window.installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.reload_settings()

    @property
    def enabled(self):
        return self.session.enabled

    @enabled.setter
    def enabled(self, value):
        self.session.enabled = value

    @property
    def holding(self):
        return self.session.holding

    @holding.setter
    def holding(self, value):
        self.session.holding = value

    @property
    def _dismissed_hold(self):
        return self.session.dismissed

    @_dismissed_hold.setter
    def _dismissed_hold(self, value):
        self.session.dismissed = value

    @property
    def generation(self):
        return self.session.generation

    @property
    def busy(self):
        return self.session.capture_generation == self.generation

    @busy.setter
    def busy(self, value):
        self.session.capture_generation = self.generation if value else None

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() == QEvent.Type.Enter:
                self.leave_timer.stop()
            elif event.type() == QEvent.Type.Leave and not self.window.is_pinned and not self.holding:
                self.leave_timer.start()
        if watched is self.window and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return True
        if watched is self.window and self.input:
            if event.type() == QEvent.Type.Show:
                self.input.visible.set()
                self._sync_pin_ready()
            elif event.type() == QEvent.Type.Hide and not self._capture_hidden:
                if not getattr(self.window, "_capture_visibility", False):
                    self.restore_capture_visibility()
                self.input.visible.clear()
                if hasattr(self.input, "pin_ready"):
                    self.input.pin_ready.clear()
                if not getattr(self.window, "_capture_visibility", False):
                    self.invalidate()
                    self.session.hide()
        return super().eventFilter(watched, event)

    def reload_settings(self):
        settings = getattr(self.window, "settings", None)
        previous = (getattr(self, "ja_ocr_provider", None), getattr(self, "tr_ocr_provider", None),
                    getattr(self, "screenai_directory", None))
        default_provider = "vision" if sys.platform == "darwin" else "meikiocr"
        self.ja_ocr_provider = settings.value("ja_ocr_provider", default_provider) if settings else default_provider
        tr_default = "vision" if sys.platform == "darwin" else "paddle"
        self.tr_ocr_provider = settings.value("tr_ocr_provider", tr_default) if settings else tr_default
        self.screenai_directory = settings.value("screenai_directory", "") if settings else ""
        if previous != (self.ja_ocr_provider, self.tr_ocr_provider, self.screenai_directory):
            self.invalidate()
        profile = self.window.preferred_foreign
        frozen = settings.value(f"profiles/{profile}/freeze_while_held", False, bool) if settings else False
        if frozen != self.freeze_while_held:
            self.invalidate()
        self.freeze_while_held = frozen
        morphology = profile != "ja" and settings.value(f"profiles/{profile}/morphology", False, bool) if settings else False
        if morphology != getattr(self, "morphology", False):
            self.invalidate()
        self.morphology = morphology
        previous_profile_provider = getattr(self, "profile_ocr_provider", None)
        from meikipop.language.support import default_ocr_provider
        default = self.ja_ocr_provider if profile == "ja" else self.tr_ocr_provider if profile == "tr" else default_ocr_provider(profile)
        self.profile_ocr_provider = settings.value(f"profiles/{profile}/ocr_provider", default) if settings else default
        if previous_profile_provider != self.profile_ocr_provider:
            self.invalidate()
        self.pin_gesture = settings.value(f"profiles/{profile}/pin_gesture", settings.value("pin_gesture", "left")) if settings else "left"
        if self.pin_gesture not in ("left", "middle", "popup"):
            self.pin_gesture = "left"
        if self.input:
            self.input.pin_gesture = self.pin_gesture
            self.input.set_pin_shortcut(settings.value(f"profiles/{profile}/pin_shortcut", "c") if settings else "c")
        if self.enabled and self.holding:
            self.timer.start()
        else:
            self.timer.stop()
        self._sync_pin_ready()

        if settings is not None:
            from meikipop.config.config import config
            bindings = settings.value(f"profiles/{profile}/scan_bindings", "shift")
            previous_bindings = getattr(self, "activation_bindings", None)
            self.activation_bindings = bindings
            if self.input and bindings and bindings != previous_bindings:
                self.input.activation.set_bindings(bindings)
                self.holding = False
            if bool(bindings) != self.enabled:
                self.set_enabled(bool(bindings))

    def _sync_pin_ready(self):
        if self.input and hasattr(self.input, "pin_ready"):
            ready = (self.session.scanning(self.window.is_pinned) and
                     QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None and
                     (self.window.isVisible() or self._capture_hidden) and getattr(self.window, "_peek", False) and
                     not self.window.is_pinned and not self.input.pin_pending.is_set())
            (self.input.pin_ready.set if ready else self.input.pin_ready.clear)()

    def pin_requested(self):
        # The native hook already checked the trigger state at mouse-down.
        # A queued key release must not discard that intentional pin.
        if (self.enabled and (self.window.isVisible() or self._capture_hidden) and getattr(self.window, "_peek", False)
                and not self.window.is_pinned and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            if self._capture_hidden:
                self._capture_hidden = False
                self.window._capture_visibility = False
                self.window.show()
            self.window.pin.setChecked(True)
        if self.input:
            self.input.pin_pending.clear()
        self._sync_pin_ready()

    def pin_changed(self, pinned):
        if pinned:
            self.restore_capture_visibility()
            self.invalidate()
            self.leave_timer.stop()
        self._sync_pin_ready()

    def follow_cursor(self):
        # Keep the native pin hook ready without chasing every pointer movement.
        # A new lookup result places the popup beside its word.
        self._sync_pin_ready()

    def invalidate(self):
        self.session.invalidate()
        if self._capture_hidden:
            self._capture_hidden = False
            self.window._capture_visibility = False
        for worker in (self.worker, self.hit_worker):
            if worker is not None and callable(getattr(worker, "invalidate", None)):
                worker.invalidate(self.generation)
        self.frame = None
        self._hit_key = None
        self.last_point = None
        self.capture_region = None
        self.capture_screen = None
        self._crop_retries = 0
        self._frozen_pixels = None
        self._frozen_screen = None

    def refresh_library(self):
        self.invalidate()
        if self.hit_worker:
            self.hit_worker.refresh()

    def _capture_bounds(self, point, geometry, screen_key):
        # A cursor-centered crop changes pixels on every tiny pointer move,
        # defeating recognition caching even when the screen is static.
        if (self.capture_region is None or self.capture_screen != screen_key or
                not self.capture_region.adjusted(16, 16, -16, -16).contains(point)):
            self.capture_region = QRect(point.x() - 600, point.y() - 240, 1200, 480).intersected(geometry)
            self.capture_screen = screen_key
            self._crop_retries = 0
        return QRect(self.capture_region)

    def set_enabled(self, enabled):
        self.session.enable(enabled)
        self.invalidate()
        if not enabled:
            self.restore_capture_visibility()
            self.timer.stop()
            if hasattr(self.window, "scan_hold_changed"):
                self.window.scan_hold_changed(False)
            if self.input:
                self.input.shutdown()
                self.input = None
            return
        try:
            if sys.platform == "darwin":
                from meikipop.utils.macos import require_screen_capture_permission
                require_screen_capture_permission(request_access=True)
            if self.input is None:
                from meikipop.gui.turkish.desktop_input import DesktopInput
                from meikipop.config.config import config
                self.input = DesktopInput(getattr(self, "activation_bindings", config.activation_bindings), "", "", QApplication.doubleClickInterval(), self)
                self.input.hold_changed.connect(self.hold_changed)
                self.input.dismissed.connect(self.dismiss)
                self.input.clicked.connect(self.outside_click)
                self.input.pin_requested.connect(self.pin_requested)
                if self.window.isVisible():
                    self.input.visible.set()
                else:
                    self.input.visible.clear()
            if self.worker is None:
                self.worker = ScanWorker(self.completed, getattr(self.window, "directory", None), self.frame_ready)
                self.worker.start()
            if self.hit_worker is None:
                self.hit_worker = HitWorker(self.completed, getattr(self.window, "directory", None))
                self.hit_worker.start()
            self.reload_settings()
        except Exception as error:
            self.enabled = False
            self.window.scan_toggle.setChecked(False)
            self.window.show_message(str(error) or "Global scan keys are unavailable. Check input permissions in system settings.")

    def hold_changed(self, active):
        changed = self.session.hold(active)
        if not active:
            if hasattr(self.window, "scan_hold_changed"):
                self.window.scan_hold_changed(False)
        if not changed:
            return
        if active and hasattr(self.window, "scan_hold_changed"):
            self.window.scan_hold_changed(True)
        if active:
            if self.window.is_pinned and not self.window.geometry().contains(QCursor.pos()):
                self.window.pin.setChecked(False)
                self._hide_preview()
            self.leave_timer.stop()
            self.last_point = None
            self._last_capture_at = 0
            self.timer.start()
            self.scan()
        else:
            self.restore_capture_visibility()
            self.timer.stop()
            self.invalidate()
            self.leave_timer.start()
        self._sync_pin_ready()

    def dismiss(self):
        self.restore_capture_visibility()
        self.session.dismiss()
        self._capture_hidden = False
        self.window._capture_visibility = False
        self.timer.stop()
        self.invalidate()
        self.window.hide()
        if self.input:
            self.input.visible.clear()
        self._sync_pin_ready()

    def outside_click(self):
        if self.input and self.input.pin_pending.is_set():
            return
        if (self.window.isVisible() and not self.window.geometry().contains(QCursor.pos())
                and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None):
            self.dismiss()

    def finish_peek(self):
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            self.leave_timer.start()
            return
        if (getattr(self.window, "_peek", False) and not self.holding and not self.window.is_pinned and
                not self.window.geometry().contains(QCursor.pos())):
            self.window.hide()

    def scan(self):
        if not self.session.scanning(self.window.is_pinned):
            return
        self._sync_pin_ready()
        point = QCursor.pos()
        if self.window.isVisible() and self.window.geometry().contains(point):
            return
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return
        if QApplication.activeWindow() is self.window:
            if not self.holding:
                return
            # An explicit scan outside Search hands focus back to the source app.
            # Do this here too: the trigger may have been pressed inside Search.
            self._hide_preview()
        now = monotonic()
        self.hit_latest(point, now)
        if self.freeze_while_held:
            if self.frame is not None and self._valid_frame(self.frame, point, now):
                return
            screen = QApplication.screenAt(point) or QApplication.primaryScreen()
            if self._frozen_screen is not None and self._screen_key(screen) != self._frozen_screen:
                return
        if self.busy or now - self._last_capture_at < .25:
            return
        self._request_capture(point)

    def _request_capture(self, point):
        now = monotonic()
        self._last_scan_at = now
        self.last_point = QPoint(point)
        self.job_point = QPoint(point)
        self.busy = True
        generation = self.generation
        self._last_capture_at = now
        visible = self.window.isVisible()
        from meikipop.utils.capture import exclude_from_capture
        if (visible or sys.platform == "win32") and not self._capture_excluded:
            self._capture_excluded = exclude_from_capture(self.window, True)
        if visible and not self._capture_excluded:
            self._capture_hidden = True
            self.window._capture_visibility = True
            self.window.hide()
        QTimer.singleShot(60 if self._capture_hidden else 0, lambda: self.capture(generation, point))

    @staticmethod
    def _screen_key(screen):
        geometry = screen.geometry()
        return (screen.name(), geometry.x(), geometry.y(), geometry.width(), geometry.height(), screen.devicePixelRatio())

    def capture(self, generation, point):
        if generation != self.generation:
            return
        if not self.session.accepts(generation, self.window.is_pinned):
            self.restore_capture_visibility()
            self.busy = False
            self._capture_hidden = False
            self.window._capture_visibility = False
            if self.input and not self.window.isVisible():
                self.input.visible.clear()
                self._sync_pin_ready()
            return
        try:
            if sys.platform == "darwin":
                from meikipop.utils.macos import require_screen_capture_permission
                require_screen_capture_permission()
            screen = QApplication.screenAt(point) or QApplication.primaryScreen()
            geometry = screen.geometry()
            scale = screen.devicePixelRatio()
            screen_key = self._screen_key(screen)
            if self.freeze_while_held:
                if self._frozen_screen is not None and self._frozen_screen != screen_key:
                    self.busy = False
                    return
                self._frozen_screen = screen_key
            region = self._capture_bounds(point, geometry, screen_key)
            self._capture_revision += 1
            request = CaptureRequest(self._capture_revision, screen.name(),
                                     (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                     (region.x(), region.y(), region.width(), region.height()), scale, generation,
                                     self.freeze_while_held)
            if sys.platform == "win32" and not self._fallback_capture and self._capture_excluded:
                self._queue_scan(generation, point, request, region)
                self._last_capture_at = monotonic()
                return
            if self.freeze_while_held and self._frozen_pixels is not None:
                snapshot, captured_at = self._frozen_pixels
            else:
                pixmap = screen.grabWindow(0)
                if pixmap.isNull():
                    raise RuntimeError("Screen capture unavailable. Allow screen recording in system settings.")
                snapshot, captured_at = pixmap.toImage(), monotonic()
                if self.freeze_while_held:
                    self._frozen_pixels = (snapshot, captured_at)
            scale_x, scale_y = snapshot.width() / geometry.width(), snapshot.height() / geometry.height()
            pixels = snapshot.copy(round((region.x() - geometry.x()) * scale_x),
                                           round((region.y() - geometry.y()) * scale_y),
                                           round(region.width() * scale_x), round(region.height() * scale_y))
            self._queue_scan(generation, point, pixels, region, request, captured_at)
            self._last_capture_at = monotonic()
        except Exception as error:
            self.busy = False
            self.invalidate()
            generation = self.generation
            self.restore_capture_visibility()
            self.window.show_message(str(error))
        finally:
            if self._capture_hidden:
                self._capture_hidden = False
                self.window._capture_visibility = False
                # Keep the prior peek usable while native recognition runs.
                # The capture itself never contains our dictionary window.
                if generation == self.generation and self.holding and not self._dismissed_hold:
                    self.window.show()
                    self.follow_cursor()

    def _queue_scan(self, generation, point, pixels=None, region=None, request=None, captured_at=None):
        region = region if region is not None else self.capture_region
        language = self.window.preferred_foreign
        capture_request = pixels if isinstance(pixels, CaptureRequest) else request
        mark("capture_dispatch", capture_request.revision if capture_request else generation, session=generation)
        self.worker.queue.put((generation, pixels,
                               ((point.x() - region.x()) / region.width(),
                                (point.y() - region.y()) / region.height()), language,
                               (self.profile_ocr_provider, self.screenai_directory), self.morphology, request,
                               monotonic() if captured_at is None else captured_at))

    def _valid_frame(self, frame, point, now):
        if (frame is None or frame.request.generation != self.generation or
                frame.language != self.window.preferred_foreign or
                not frame.request.frozen and now - frame.captured_at > 2):
            return False
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        return (screen is not None and screen.name() == frame.request.screen
                and screen.devicePixelRatio() == frame.request.scale
                and QRect(*frame.request.geometry) == screen.geometry()
                and QRect(*frame.request.crop).contains(point))

    def accept_frame(self, generation, frame, error):
        self.session.finish_capture(generation)
        if not self.session.accepts(generation, self.window.is_pinned):
            mark("discard", generation, reason="obsolete_frame")
            return
        if error:
            self.frame = None
            self._hit_key = None
            self.restore_capture_visibility()
            if isinstance(frame, CaptureRequest):
                self._fallback_capture = True
            self.window.show_message(error)
            return
        self.frame = frame
        mark("frame_accepted", frame.request.revision)
        point = QCursor.pos()
        if self._crop_retries < 2 and self._valid_frame(frame, point, monotonic()):
            from meikipop.ocr.boundaries import expanded_crop
            crop = expanded_crop(frame, (point.x(), point.y()))
            if crop is not None:
                self._crop_retries += 1
                self.capture_region = QRect(*crop)
                self._request_capture(point)
                return
        self.hit_latest(QCursor.pos(), monotonic())

    def hit_latest(self, point, now):
        if not self._valid_frame(self.frame, point, now):
            return
        if (self.window.isVisible() and self.window.geometry().contains(point) or
                QApplication.activeModalWidget() or QApplication.activePopupWidget()):
            return
        mark("hit_test_begin", self.frame.request.revision)
        hit = hit_paragraphs(self.frame.paragraphs, self.frame.point(point.x(), point.y()), self.frame.language)
        mark("hit_test_done", self.frame.request.revision)
        if hit is None:
            self._hit_key = None
            self._hide_preview()
            return
        key = (self.frame.identity, hit.text, hit.start, hit.query, self.morphology)
        if key == self._hit_key and now - self._last_dictionary_at < 2:
            mark("duplicate_hit", self.frame.request.revision)
            return
        self._hit_key, self._last_dictionary_at = key, now
        if self.hit_worker:
            self.hit_worker.queue.put((self.generation, self.frame, hit, self.morphology))

    def _hide_preview(self):
        self.window._capture_visibility = True
        try:
            self.window.hide()
        finally:
            self.window._capture_visibility = False

    def restore_capture_visibility(self):
        if self._capture_excluded:
            from meikipop.utils.capture import exclude_from_capture
            exclude_from_capture(self.window, False)
            self._capture_excluded = False

    def deliver(self, generation, result, hit, error):
        frame = None
        if not self.session.accepts(generation, self.window.is_pinned):
            mark("discard", generation, reason="obsolete_hit")
            return
        if QApplication.activeWindow() is self.window:
            return
        if isinstance(hit, tuple):
            frame, hit = hit
            point = QCursor.pos()
            current = hit_paragraphs(frame.paragraphs, frame.point(point.x(), point.y()), frame.language)
            if (not self._valid_frame(frame, point, monotonic()) or self.frame is None or
                    frame.identity != self.frame.identity or current is None or
                    (current.text, current.start, current.query) != (hit.text, hit.start, hit.query)):
                mark("discard", frame.request.revision, reason="lexical_hit_changed")
                return
        if error:
            self.restore_capture_visibility()
            self.window.show_message(error)
            return
        if result is None:
            self._hide_preview()
            return
        if self.window.show_entries(result.entries, text=result.text, source=result.source,
                                    peek=True, kanji=result.kanji):
            mark("hit_delivery", frame.request.revision if frame is not None else generation,
                 popup_revision=getattr(self.window, "revision", 0))
            self.window.set_context(*hit.sentence)
            self._sync_pin_ready()

    def shutdown(self):
        self.restore_capture_visibility()
        self.set_enabled(False)
        self.leave_timer.stop()
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=1)
            self.worker = None
        if self.hit_worker:
            self.hit_worker.stop()
            self.hit_worker.join(timeout=1)
            self.hit_worker = None
