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
from meikipop.utils.lastest_queue import LatestValueQueue


class ScanWorker(threading.Thread):
    def __init__(self, completed, directory=None):
        super().__init__(daemon=True, name="UnifiedOCR")
        self.completed = completed
        self.directory = directory
        self.queue = LatestValueQueue()
        self._stopped = threading.Event()

    def stop(self):
        self._stopped.set()
        self.queue.put(None)

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
        providers, caches = {}, {}
        try:
            while True:
                job = self.queue.get()
                if job is None or self._stopped.is_set():
                    return
                generation, pixels, point, language, *options = job
                try:
                    if engine is None:
                        engine = SearchEngine(self.directory)
                    selection = tuple(options[0]) if options else ()
                    provider_key = (language, *selection)
                    if provider_key not in providers:
                        providers[provider_key] = self.provider(language, *selection)
                        caches[provider_key] = ScanCache()
                    if pixels is None:
                        paragraphs = caches[provider_key].result
                    else:
                        pixels = pixels.convertToFormat(QImage.Format.Format_RGB888)
                        image = Image.frombytes("RGB", (pixels.width(), pixels.height()),
                                                pixels.constBits().asstring(pixels.sizeInBytes()),
                                                "raw", "RGB", pixels.bytesPerLine())
                        paragraphs = caches[provider_key].scan(image, providers[provider_key])
                    if self._stopped.is_set():
                        return
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
                    self._emit(generation, None, None, detail[:300])
        finally:
            if engine:
                engine.close()

    @staticmethod
    def provider(language, selected=None, component_directory=""):
        if selected == "screenai":
            from meikipop.ocr.providers.screenai.provider import ScreenAiOcr
            return ScreenAiOcr(component_directory or None, language=language).scan
        if selected == "paddle" or language != "ja" and selected is None and sys.platform != "darwin":
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


class UnifiedOCR(QObject):
    completed = pyqtSignal(int, object, object, str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.input = None
        self.worker = None
        self.enabled = False
        self.holding = False
        self.auto_scan = False
        self.pin_gesture = "left"
        self._dismissed_hold = False
        self._dismissed_point = None
        self._hover_point = None
        self._hover_since = 0
        self._last_scan_at = 0
        self._last_capture_at = 0
        self._capture_hidden = False
        self._capture_excluded = False
        self._follow_point = None
        self.busy = False
        self.generation = 0
        self.last_point = None
        self.job_point = None
        self.capture_region = None
        self.capture_screen = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.scan)
        self.follow_timer = QTimer(self)
        self.follow_timer.setInterval(16)
        self.follow_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.follow_timer.timeout.connect(self.follow_cursor)
        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.setInterval(450)
        self.leave_timer.timeout.connect(self.finish_peek)
        self.completed.connect(self.deliver)
        window.ocr_enabled_changed.connect(self.set_enabled)
        window.mode_changed.connect(lambda _: self.invalidate())
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

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return True
        if watched is self.window and self.input:
            if event.type() == QEvent.Type.Show:
                self.input.visible.set()
                self._sync_pin_ready()
            elif event.type() == QEvent.Type.Hide and not self._capture_hidden:
                self.restore_capture_visibility()
                self.input.visible.clear()
                if hasattr(self.input, "pin_ready"):
                    self.input.pin_ready.clear()
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
        morphology = profile != "ja" and settings.value(f"profiles/{profile}/morphology", False, bool) if settings else False
        if morphology != getattr(self, "morphology", False):
            self.invalidate()
        self.morphology = morphology
        previous_profile_provider = getattr(self, "profile_ocr_provider", None)
        default = self.ja_ocr_provider if profile == "ja" else self.tr_ocr_provider if profile == "tr" else "vision" if sys.platform == "darwin" else "paddle"
        self.profile_ocr_provider = settings.value(f"profiles/{profile}/ocr_provider", default) if settings else default
        if previous_profile_provider != self.profile_ocr_provider:
            self.invalidate()
        self.auto_scan = settings.value(f"profiles/{profile}/auto_scan", settings.value("auto_scan", False, bool), bool) if settings else False
        self.pin_gesture = settings.value(f"profiles/{profile}/pin_gesture", settings.value("pin_gesture", "left")) if settings else "left"
        if self.pin_gesture not in ("left", "middle", "popup"):
            self.pin_gesture = "left"
        if self.input:
            self.input.pin_gesture = self.pin_gesture
            self.input.set_pin_shortcut(settings.value(f"profiles/{profile}/pin_shortcut", "c") if settings else "c")
        if self.enabled and (self.holding or self.auto_scan):
            self.timer.start()
            self.follow_timer.start()
        else:
            self.timer.stop()
            self.follow_timer.stop()
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
            ready = (self.enabled and self.holding and not self._dismissed_hold and
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
        self._sync_pin_ready()
        if (not self.enabled or not (self.holding or self.auto_scan) or self.window.is_pinned or
                not self.window.isVisible() or not getattr(self.window, "_peek", False)):
            return
        if self.input and hasattr(self.input, "pin_pending") and self.input.pin_pending.is_set():
            return
        point = QCursor.pos()
        if (QApplication.activeModalWidget() or QApplication.activeWindow() is self.window or
                self.window.geometry().contains(point) or point == self._follow_point):
            return
        self._follow_point = QPoint(point)
        self.window._place()

    def invalidate(self):
        self.generation += 1
        self.last_point = None
        self.capture_region = None
        self.capture_screen = None

    def _capture_bounds(self, point, geometry, screen_key):
        # A cursor-centered crop changes pixels on every tiny pointer move,
        # defeating recognition caching even when the screen is static.
        if (self.capture_region is None or self.capture_screen != screen_key or
                not self.capture_region.adjusted(16, 16, -16, -16).contains(point)):
            self.capture_region = QRect(point.x() - 600, point.y() - 240, 1200, 480).intersected(geometry)
            self.capture_screen = screen_key
        return QRect(self.capture_region)

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.invalidate()
        if not enabled:
            self.restore_capture_visibility()
            self.timer.stop()
            self.follow_timer.stop()
            self.holding = False
            if hasattr(self.window, "scan_hold_changed"):
                self.window.scan_hold_changed(False)
            self._dismissed_hold = False
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
                self.worker = ScanWorker(self.completed, getattr(self.window, "directory", None))
                self.worker.start()
            self.reload_settings()
        except Exception as error:
            self.enabled = False
            self.window.scan_toggle.setChecked(False)
            self.window.show_message(str(error) or "Global scan keys are unavailable. Check input permissions in system settings.")

    def hold_changed(self, active):
        if not active:
            self._dismissed_hold = False
            if hasattr(self.window, "scan_hold_changed"):
                self.window.scan_hold_changed(False)
        elif self._dismissed_hold:
            return
        if not self.enabled or active == self.holding:
            return
        self.holding = active
        if active and hasattr(self.window, "scan_hold_changed"):
            self.window.scan_hold_changed(True)
        if active:
            if self.window.is_pinned and not self.window.geometry().contains(QCursor.pos()):
                self.window.pin.setChecked(False)
                self.window.hide()
            self.leave_timer.stop()
            self.last_point = None
            self._dismissed_point = None
            self.timer.start()
            self.follow_timer.start()
            self.scan()
        else:
            self.restore_capture_visibility()
            if not self.auto_scan:
                self.timer.stop()
                self.follow_timer.stop()
            self.invalidate()
            self.leave_timer.start()
        self._sync_pin_ready()

    def dismiss(self):
        self.restore_capture_visibility()
        self._dismissed_hold = self.holding
        self._dismissed_point = QCursor.pos()
        self.holding = False
        self._capture_hidden = False
        if not self.auto_scan:
            self.timer.stop()
            self.follow_timer.stop()
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
        if (getattr(self.window, "_peek", False) and not self.holding and not self.window.is_pinned and
                not self.window.geometry().contains(QCursor.pos())):
            self.window.hide()

    def scan(self):
        if (not self.enabled or not (self.holding or self.auto_scan) or self._dismissed_hold or
                self.busy or self.window.is_pinned):
            return
        point = QCursor.pos()
        if self.window.isVisible() and self.window.geometry().contains(point):
            return
        if QApplication.activeModalWidget():
            return
        if QApplication.activeWindow() is self.window:
            if not self.holding:
                return
            # An explicit scan outside Search hands focus back to the source app.
            # Do this here too: the trigger may have been pressed inside Search.
            self.window.hide()
        now = monotonic()
        if self._dismissed_point is not None:
            if (point - self._dismissed_point).manhattanLength() < 24:
                return
            self._dismissed_point = None
            self._hover_point = None
        if not self.holding:
            if self._hover_point is None or (point - self._hover_point).manhattanLength() >= 4:
                self._hover_point, self._hover_since = QPoint(point), now
                return
            if now - self._hover_since < 0.35 or now - self._last_scan_at < 1:
                return
        if (self.last_point is not None and (point - self.last_point).manhattanLength() < 4
                and now - self._last_scan_at < 1):
            return
        self._last_scan_at = now
        self.last_point = QPoint(point)
        self.job_point = QPoint(point)
        self.busy = True
        self.generation += 1
        generation = self.generation
        # Retest the pointer against the recognized frame between fresh captures.
        # A short lifetime also keeps animated or scrolling content current.
        if (self.capture_region is not None and now - self._last_capture_at < .15
                and self.capture_region.adjusted(16, 16, -16, -16).contains(point)):
            self._queue_scan(generation, point)
            return
        visible = self.window.isVisible()
        from meikipop.utils.capture import exclude_from_capture
        if visible and not self._capture_excluded:
            self._capture_excluded = exclude_from_capture(self.window, True)
        if visible and not self._capture_excluded:
            self._capture_hidden = True
            self.window.hide()
        QTimer.singleShot(60 if self._capture_hidden else 0, lambda: self.capture(generation, point))

    def capture(self, generation, point):
        if (generation != self.generation or not self.enabled or not (self.holding or self.auto_scan)
                or self.window.is_pinned):
            self.restore_capture_visibility()
            self.busy = False
            self._capture_hidden = False
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
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError("Screen capture unavailable. Allow screen recording in system settings.")
            scale_x, scale_y = pixmap.width() / geometry.width(), pixmap.height() / geometry.height()
            screen_key = (screen.name(), geometry.x(), geometry.y(), geometry.width(), geometry.height(), scale_x, scale_y)
            region = self._capture_bounds(point, geometry, screen_key)
            pixels = pixmap.toImage().copy(round((region.x() - geometry.x()) * scale_x),
                                           round((region.y() - geometry.y()) * scale_y),
                                           round(region.width() * scale_x), round(region.height() * scale_y))
            self._queue_scan(generation, point, pixels)
            self._last_capture_at = monotonic()
        except Exception as error:
            self.busy = False
            self.invalidate()
            self.restore_capture_visibility()
            self.window.show_message(str(error))
        finally:
            if self._capture_hidden:
                self._capture_hidden = False
                # Keep the prior peek usable while native recognition runs.
                # The capture itself never contains our dictionary window.
                if generation == self.generation and (self.holding or self.auto_scan):
                    self.window.show()
                    self.follow_cursor()

    def _queue_scan(self, generation, point, pixels=None):
        region = self.capture_region
        language = self.window.preferred_foreign
        self.worker.queue.put((generation, pixels,
                               ((point.x() - region.x()) / region.width(),
                                (point.y() - region.y()) / region.height()), language,
                               (self.profile_ocr_provider, self.screenai_directory), self.morphology))

    def restore_capture_visibility(self):
        if self._capture_excluded:
            from meikipop.utils.capture import exclude_from_capture
            exclude_from_capture(self.window, False)
            self._capture_excluded = False

    def deliver(self, generation, result, hit, error):
        self.busy = False
        if (generation != self.generation or not self.enabled or not (self.holding or self.auto_scan)
                or self._dismissed_hold or self.window.is_pinned):
            return
        if QApplication.activeWindow() is self.window:
            return
        if self.job_point is not None and (QCursor.pos() - self.job_point).manhattanLength() > 12:
            return
        if error:
            self.window.show_message(error)
            return
        if result is None:
            self.window.hide()
            return
        if self.window.show_entries(result.entries, text=result.text, source=result.source,
                                    peek=True, kanji=result.kanji):
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
