"""Optional local OCR for the shared popup; no inference on the Qt thread."""
from dataclasses import replace
import sys
import threading
from time import monotonic

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QImage
from PyQt6.QtWidgets import QApplication

from meikipop.config.config import config
from meikipop.ocr.context import hit_paragraphs, paddle_paragraphs
from meikipop.ocr.scan_cache import ScanCache
from meikipop.ocr.frames import RecognizedFrame
from meikipop.utils.lastest_queue import LatestValueQueue
from meikipop.utils.capture import CaptureRequest, PixelFrame, RegionCapture
from meikipop.utils.timing import mark
from meikipop.gui.lookup_session import LookupSession
from meikipop.language.profiles import get_profile


def _matched_hit(hit, result, language):
    if result.entries:
        if language == "ja":
            surface = result.entries[0].term
            if hit.text.startswith(surface, hit.start):
                return replace(hit, end=hit.start + len(surface))
        elif get_profile(language).word_mode == "unspaced" and result.matched_length:
            return replace(hit, end=min(len(hit.text), hit.start + result.matched_length))
    return hit


class PaddleScan:
    def __init__(self, provider, language):
        self.provider, self.language = provider, language

    def __call__(self, image):
        return self.scan(image, self.language)

    def scan(self, image, language):
        import numpy as np
        results = self.provider.recognize(np.asarray(image)[:, :, ::-1].copy())
        return paddle_paragraphs(results, *image.size, language=language)


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
        self._reset_models = threading.Event()

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

    def refresh_models(self):
        self._reset_models.set()
        self.queue.put("models")

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
        providers, caches, scanners = {}, {}, {}
        try:
            while True:
                job = self.queue.get()
                if job is None or self._stopped.is_set():
                    return
                if self._reset_models.is_set():
                    providers.clear()
                    caches.clear()
                    scanners.clear()
                    self._frozen = None
                    self._reset_models.clear()
                if job == "refresh":
                    if engine:
                        engine.refresh()
                    continue
                if job == "models":
                    continue
                generation, pixels, point, language, *options = job
                capture_request = pixels if isinstance(pixels, CaptureRequest) else (
                    pixels.request if isinstance(pixels, PixelFrame) else options[2] if len(options) > 2 else None)
                mark("ocr_dequeue", capture_request.revision if capture_request else generation)
                capture_phase = False
                snapshot = None
                try:
                    if self._obsolete(generation):
                        self.frames.emit(generation, None, "")
                        continue
                    if engine is None and self.frames is None:
                        engine = SearchEngine(self.directory)
                    selection = tuple(options[0]) if options else ()
                    from meikipop.language.support import default_ocr_provider, ocr_supported
                    selected = (selection[0] if selection else None) or default_ocr_provider(language)
                    if selected is None or not ocr_supported(language, selected):
                        raise RuntimeError("This OCR provider does not support this language.")
                    component = selection[1] if selected == "screenai" and len(selection) > 1 else ""
                    provider_key = (language, selected, component)
                    # Paddle's installed multilingual model is identical across profiles.
                    model_key = ("paddle",) if selected == "paddle" else provider_key
                    if pixels is not None:
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
                            elif pixels.full_snapshot:
                                snapshot = capture.capture(replace(pixels, crop=pixels.geometry))
                                pixels = snapshot.cropped(pixels)
                            else:
                                pixels = capture.capture(pixels)
                            capture_phase = False
                            mark("capture_done", pixels.request.revision)
                        if isinstance(pixels, PixelFrame):
                            image = pixels.image()
                        else:
                            pixels = pixels.convertToFormat(QImage.Format.Format_RGB888)
                            if capture_request is not None and capture_request.full_snapshot:
                                snapshot = PixelFrame(replace(capture_request, crop=capture_request.geometry),
                                                      (pixels.width(), pixels.height()),
                                                      pixels.constBits().asstring(pixels.sizeInBytes()), options[3],
                                                      stride=pixels.bytesPerLine())
                                pixels = snapshot.cropped(capture_request)
                                image = pixels.image()
                            else:
                                image = Image.frombytes("RGB", (pixels.width(), pixels.height()),
                                                        pixels.constBits().asstring(pixels.sizeInBytes()),
                                                        "raw", "RGB", pixels.bytesPerLine())
                        mark("pixels_ready", generation)
                    if self._stopped.is_set():
                        return
                    if self._obsolete(generation):
                        self.frames.emit(generation, None, "")
                        continue
                    if model_key not in providers:
                        mark("provider_load_begin", generation, provider=selected)
                        providers[model_key] = self.provider(language, *selection)
                        mark("provider_load_done", generation, provider=selected)
                    if self._stopped.is_set():
                        return
                    if self._obsolete(generation):
                        self.frames.emit(generation, None, "")
                        continue
                    cache = caches.setdefault(provider_key, ScanCache())
                    if pixels is None:
                        paragraphs = cache.result
                    else:
                        if provider_key not in scanners:
                            scanner = providers[model_key]
                            if isinstance(scanner, PaddleScan):
                                scanner = lambda image, shared=scanner, code=language: shared.scan(image, code)
                            scanners[provider_key] = scanner
                        scanner = scanners[provider_key]
                        paragraphs = cache.scan(image, scanner)
                        mark("ocr_done", generation)
                    if self._stopped.is_set():
                        return
                    if self.frames is not None:
                        request = pixels.request if isinstance(pixels, PixelFrame) else options[2]
                        captured_at = pixels.captured_at if isinstance(pixels, PixelFrame) else options[3]
                        if snapshot is None:
                            snapshot = pixels if isinstance(pixels, PixelFrame) else PixelFrame(
                                request, image.size, image.tobytes(), captured_at)
                        if request.frozen and isinstance(pixels, PixelFrame) and self._frozen is not None:
                            snapshot = self._frozen[1]
                        frame = RecognizedFrame(request, tuple(replace(p, words=tuple(p.words)) for p in paragraphs or ()),
                                                language, selection, caches[provider_key].revision, captured_at,
                                                image.size, pixels.physical_crop if isinstance(pixels, PixelFrame) else (), snapshot)
                        self.frames.emit(generation, frame, "")
                        continue
                    hit = hit_paragraphs(paragraphs, point, language)
                    if hit is None:
                        self._emit(generation, None, None, "")
                        continue
                    engine.refresh_if_changed()
                    morphology = bool(options[1]) if len(options) > 1 else False
                    analysis = {"morphology": True, "context": (hit.text, hit.start, hit.end)} if morphology else {}
                    if language == "ja":
                        analysis["max_lookup_length"] = config.max_lookup_length
                    result = engine.search(hit.query, source=language, foreign=language, **analysis)
                    hit = _matched_hit(hit, result, language)
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
        from meikipop.language.support import default_ocr_provider, ocr_supported
        selected = selected or default_ocr_provider(language)
        if selected is None:
            raise RuntimeError("Screen recognition support is unverified for this language.")
        if not ocr_supported(language, selected):
            raise RuntimeError("This OCR provider does not support this language.")
        if selected == "screenai":
            from meikipop.ocr.providers.screenai.provider import ScreenAiOcr
            return ScreenAiOcr(component_directory or None, language=language).scan
        if selected == "paddle":
            from meikipop.ocr.turkish_paddle import LocalOCR
            return PaddleScan(LocalOCR(), language)
        if selected == "vision":
            from meikipop.ocr.macos_vision import recognize
            return lambda image: recognize(image, language)
        if selected == "meikiocr":
            try:
                from meikipop.ocr.providers.meikiocr.provider import MeikiOcrProvider
            except ImportError as error:
                raise RuntimeError("Install Japanese OCR dependencies in Settings before scanning.") from error
            provider = MeikiOcrProvider(execution_provider="CPUExecutionProvider")
            if provider.ocr_client is None:
                raise RuntimeError("Japanese OCR could not start. Check its local model installation.")
            return provider.scan
        raise RuntimeError("Choose a supported OCR provider in Settings.")


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
                    if frame.language == "ja":
                        options["max_lookup_length"] = config.max_lookup_length
                    result = engine.search(hit.query, source=frame.language, foreign=frame.language, **options)
                    hit = _matched_hit(hit, result, frame.language)
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
        self.freeze_while_held = True
        self.hover_enabled = False
        self.hover_region = None
        self.hover_screen = None
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
        if hasattr(window, "models_changed"):
            window.models_changed.connect(self.refresh_models)
        window.search.textChanged.connect(lambda _: self.invalidate())
        if hasattr(window, "scan_settings_changed"):
            window.scan_settings_changed.connect(self.reload_settings)
        if hasattr(window, "pin"):
            window.pin.toggled.connect(self.pin_changed)
        if hasattr(window, "dismiss_button"):
            window.dismiss_button.clicked.connect(self.dismiss)
        window.installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self._restore_scan_area()
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

    @property
    def freeze_capture(self):
        return self.freeze_while_held and not self.session.hovering

    def _sync_timer(self):
        if self.enabled and (self.holding or self.hover_enabled) and not self.session.suspended:
            self.timer.start()
        else:
            self.timer.stop()

    def add_tray_actions(self, menu, before):
        from PyQt6.QtGui import QAction
        hover = QAction("Hover scan", menu)
        hover.setCheckable(True)
        area = QAction("Select scan area…", menu)
        menu.insertAction(before, hover)
        menu.insertAction(before, area)
        hover.triggered.connect(lambda checked: QTimer.singleShot(0, lambda: self.set_hover_enabled(checked)))
        area.triggered.connect(lambda: QTimer.singleShot(0, self.select_scan_area))
        def sync():
            from meikipop.language.support import ocr_supported
            hover.setChecked(self.hover_enabled)
            hover.setEnabled(ocr_supported(self.window.preferred_foreign, self.profile_ocr_provider))
            area.setEnabled(self.hover_enabled)
        menu.aboutToShow.connect(sync)
        sync()

    def set_hover_enabled(self, enabled):
        if enabled and self.hover_region is None and not self.select_scan_area():
            return
        self.hover_enabled = bool(enabled)
        self.session.hover(False)
        if not self.holding and hasattr(self.window, "scan_hold_changed"):
            self.window.scan_hold_changed(False)
        self.invalidate()
        self.reload_settings()
        self._sync_timer()
        self._sync_pin_ready()
        if not enabled and not self.holding:
            self.restore_capture_visibility()
            self.leave_timer.start()

    def _restore_scan_area(self):
        settings = getattr(self.window, "settings", None)
        if settings is None:
            return
        region = settings.value("hover_scan/region")
        screen_key = settings.value("hover_scan/screen", [])
        if not isinstance(region, QRect) or region.width() < 2 or region.height() < 2:
            return
        if not isinstance(screen_key, (list, tuple)):
            return
        for screen in QApplication.screens():
            if self._screen_key(screen) == tuple(screen_key) and screen.geometry().contains(region):
                self.hover_region = QRect(region)
                self.hover_screen = self._screen_key(screen)
                return

    def select_scan_area(self):
        from meikipop.gui.region_selector import RegionSelector
        self.session.suspended = True
        self.restore_capture_visibility()
        self.invalidate()
        self._sync_timer()
        self._sync_pin_ready()
        try:
            region = RegionSelector.get_region(logical=True)
            if region is None or region.width() < 2 or region.height() < 2:
                return False
            screen = QApplication.screenAt(region.center())
            if screen is None or not screen.geometry().contains(region):
                return False
            self.hover_region = QRect(region)
            self.hover_screen = self._screen_key(screen)
            settings = getattr(self.window, "settings", None)
            if settings is not None:
                settings.setValue("hover_scan/region", self.hover_region)
                settings.setValue("hover_scan/screen", list(self.hover_screen))
            self.session.hover(False)
            return True
        finally:
            self.session.suspended = False
            self.invalidate()
            self._sync_timer()
            self._sync_pin_ready()

    def _update_hover(self, point):
        if not self.hover_enabled and not self.session.hovering:
            return
        screen = QApplication.screenAt(point)
        active = (self.hover_enabled and self.hover_region is not None and
                  self.hover_region.contains(point) and screen is not None and
                  self._screen_key(screen) == self.hover_screen and not self.session.suspended and
                  QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None and
                  not (self.window.isVisible() and not self.window._peek))
        was_scanning = self.session.scanning(self.window.is_pinned)
        if self.session.hover(active):
            self.invalidate()
            self._last_capture_at = 0
            scanning = self.session.scanning(self.window.is_pinned)
            if not self.holding and hasattr(self.window, "scan_hold_changed"):
                self.window.scan_hold_changed(scanning)
            if scanning:
                self.leave_timer.stop()
            elif was_scanning:
                self.restore_capture_visibility()
                self.leave_timer.start()
        self._sync_pin_ready()

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
        previous = getattr(self, "screenai_directory", None)
        self.screenai_directory = settings.value("screenai_directory", "") if settings else ""
        if previous != self.screenai_directory:
            self.invalidate()
        profile = self.window.preferred_foreign
        frozen = settings.value(f"profiles/{profile}/freeze_while_held", True, bool) if settings else True
        if frozen != self.freeze_while_held:
            self.invalidate()
        self.freeze_while_held = frozen
        from meikipop.language.morphology import model_available
        morphology = model_available(profile)
        if morphology != getattr(self, "morphology", False):
            self.invalidate()
        self.morphology = morphology
        previous_profile_provider = getattr(self, "profile_ocr_provider", None)
        from meikipop.language.support import default_ocr_provider, ocr_supported
        default = default_ocr_provider(profile)
        self.profile_ocr_provider = settings.value(f"profiles/{profile}/ocr_provider", default) if settings else default
        if previous_profile_provider != self.profile_ocr_provider:
            self.invalidate()
        self.pin_gesture = settings.value(f"profiles/{profile}/pin_gesture", "left") if settings else "left"
        if self.pin_gesture not in ("left", "middle", "popup"):
            self.pin_gesture = "left"
        if self.input:
            self.input.pin_gesture = self.pin_gesture
            self.input.set_pin_shortcut(settings.value(f"profiles/{profile}/pin_shortcut", "c") if settings else "c")
            self._reload_popup_bindings()
        self._sync_timer()
        self._sync_pin_ready()

        if settings is not None:
            from meikipop.config.config import config
            bindings = settings.value(f"profiles/{profile}/scan_bindings", "shift,middle")
            previous_bindings = getattr(self, "activation_bindings", None)
            self.activation_bindings = bindings
            if self.input and bindings != previous_bindings:
                self.input.activation.set_bindings(bindings)
                self.holding = False
            enabled = (bool(bindings) or self.hover_enabled) and ocr_supported(profile, self.profile_ocr_provider)
            if enabled != self.enabled:
                self.set_enabled(enabled)
        self._sync_timer()

    def _reload_popup_bindings(self):
        settings = getattr(self.window, "settings", None)
        if self.input is None or sys.platform != "win32" or settings is None:
            return
        from meikipop.gui.popup_shortcuts import popup_bindings, native_chord
        profile, bindings = self.window.preferred_foreign, {}
        for action, value in popup_bindings(settings, profile).items():
            if not value or action == "anki" and not settings.value(f"profiles/{profile}/anki/enabled", False, bool):
                continue
            try:
                bindings[native_chord(value)] = action
            except ValueError:
                continue
        self.input.popup_bindings = bindings

    def _sync_pin_ready(self):
        if self.input and hasattr(self.input, "popup_controls_active"):
            active = self.window.isVisible() and self.window.is_pinned
            (self.input.popup_controls_active.set if active else self.input.popup_controls_active.clear)()
        if self.input:
            self.input.navigation_source = (getattr(self.window, "_previous_foreground", None)
                if (getattr(self.window, "_fullscreen_overlay", False) and self.window.is_pinned
                    and self.window.isVisible() and QApplication.activeModalWidget() is None
                    and QApplication.activePopupWidget() is None) else None)
        if self.input and hasattr(self.input, "hover_active"):
            active = self.session.hovering and self.session.scanning(self.window.is_pinned)
            (self.input.hover_active.set if active else self.input.hover_active.clear)()
        if self.input and hasattr(self.input, "pin_ready"):
            ready = (self.session.scanning(self.window.is_pinned) and
                     QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None and
                     (self.window.isVisible() or self._capture_hidden) and getattr(self.window, "_peek", False) and
                     not self.window.is_pinned and not self.input.pin_pending.is_set())
            (self.input.pin_ready.set if ready else self.input.pin_ready.clear)()

    def navigate_overlay(self, virtual_key):
        self.window.navigate_overlay(virtual_key)

    def popup_action(self, action):
        if (getattr(self.window, "_fullscreen_overlay", False) and self.window.is_pinned
                and self.window.isVisible() and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            self.window.popup_action(action)

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
        if self.hover_enabled and not self.holding and hasattr(self.window, "scan_hold_changed"):
            self.window.scan_hold_changed(self.session.scanning(pinned))
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

    def refresh_models(self):
        self.invalidate()
        if self.worker:
            self.worker.refresh_models()

    def _capture_bounds(self, point, geometry, screen_key):
        if self.session.hovering:
            self.capture_region = self.hover_region.intersected(geometry)
            self.capture_screen = screen_key
            return QRect(self.capture_region)
        # A cursor-centered crop changes pixels on every tiny pointer move,
        # defeating recognition caching even when the screen is static.
        if (self.capture_region is None or self.capture_screen != screen_key or
                not self.capture_region.adjusted(16, 16, -16, -16).contains(point)):
            self.capture_region = QRect(point.x() - 600, point.y() - 240, 1200, 480).intersected(geometry)
            self.capture_screen = screen_key
            self._crop_retries = 0
        return QRect(self.capture_region)

    def set_enabled(self, enabled, *, request_access=True):
        if enabled:
            from meikipop.language.support import ocr_supported
            if not ocr_supported(self.window.preferred_foreign, self.profile_ocr_provider):
                enabled = False
                self.window.scan_toggle.setChecked(False)
                self.window.show_message("Screen recognition is unavailable for this language.")
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
                require_screen_capture_permission(request_access=request_access)
            if self.input is None:
                from meikipop.gui.turkish.desktop_input import DesktopInput
                from meikipop.config.config import config
                self.input = DesktopInput(getattr(self, "activation_bindings", config.activation_bindings), "", "", QApplication.doubleClickInterval(), self)
                self.input.hold_changed.connect(self.hold_changed)
                self.input.dismissed.connect(self.dismiss)
                self.input.clicked.connect(self.outside_click)
                self.input.pin_requested.connect(self.pin_requested)
                self.input.navigation_requested.connect(self.navigate_overlay)
                self.input.popup_action_requested.connect(self.popup_action)
                self._reload_popup_bindings()
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
            if self.input:
                self.input.shutdown()
                self.input = None
            self.enabled = False
            self.window.scan_toggle.setChecked(False)
            self.window.show_message(str(error) or "Global scan keys are unavailable. Check input permissions in system settings.")

    def hold_changed(self, active):
        changed = self.session.hold(active)
        if not active:
            if hasattr(self.window, "scan_hold_changed"):
                self.window.scan_hold_changed(self.session.scanning(self.window.is_pinned))
        if not changed:
            return
        if active and hasattr(self.window, "scan_hold_changed"):
            self.window.scan_hold_changed(True)
        if active:
            self.invalidate()
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
            self._sync_timer()
            self.invalidate()
            self.leave_timer.start()
        self._sync_pin_ready()

    def dismiss(self):
        self.restore_capture_visibility()
        self.session.dismiss()
        if hasattr(self.window, "scan_hold_changed"):
            self.window.scan_hold_changed(False)
        self._capture_hidden = False
        self.window._capture_visibility = False
        self._sync_timer()
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
        if (getattr(self.window, "_peek", False) and not self.session.scanning(self.window.is_pinned) and not self.window.is_pinned and
                not self.window.geometry().contains(QCursor.pos())):
            self.window.hide()

    def scan(self):
        point = QCursor.pos()
        self._update_hover(point)
        if not self.session.scanning(self.window.is_pinned):
            return
        self._sync_pin_ready()
        if self.window.isVisible() and self.window.geometry().contains(point):
            return
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return
        if QApplication.activeWindow() is self.window and self.window.isVisible() and not self.window._peek:
            if not self.holding:
                return
            # An explicit scan outside Search hands focus back to the source app.
            # Do this here too: the trigger may have been pressed inside Search.
            self._hide_preview()
        now = monotonic()
        self.hit_latest(point, now)
        if self.freeze_capture:
            if self.frame is not None and self._valid_frame(self.frame, point, now):
                return
            screen = QApplication.screenAt(point) or QApplication.primaryScreen()
            if self._frozen_screen is not None and self._screen_key(screen) != self._frozen_screen:
                return
        interval = .5 if self.session.hovering else .25
        if self.busy or now - self._last_capture_at < interval:
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
        self._update_hover(QCursor.pos())
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
            if self.freeze_capture:
                if self._frozen_screen is not None and self._frozen_screen != screen_key:
                    self.busy = False
                    return
                self._frozen_screen = screen_key
            region = self._capture_bounds(point, geometry, screen_key)
            self._capture_revision += 1
            request = CaptureRequest(self._capture_revision, screen.name(),
                                     (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                     (region.x(), region.y(), region.width(), region.height()), scale, generation,
                                     self.freeze_capture, full_snapshot=self.session.hovering)
            if sys.platform == "win32" and not self._fallback_capture and self._capture_excluded:
                self._queue_scan(generation, point, request, region)
                self._last_capture_at = monotonic()
                return
            if self.freeze_capture and self._frozen_pixels is not None:
                snapshot, captured_at = self._frozen_pixels
            else:
                pixmap = screen.grabWindow(0)
                if pixmap.isNull():
                    raise RuntimeError("Screen capture unavailable. Allow screen recording in system settings.")
                snapshot, captured_at = pixmap.toImage(), monotonic()
                if self.freeze_capture:
                    self._frozen_pixels = (snapshot, captured_at)
            scale_x, scale_y = snapshot.width() / geometry.width(), snapshot.height() / geometry.height()
            pixels = snapshot if request.full_snapshot else snapshot.copy(
                round((region.x() - geometry.x()) * scale_x), round((region.y() - geometry.y()) * scale_y),
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
                if self.session.accepts(generation, self.window.is_pinned):
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
        self._update_hover(QCursor.pos())
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
        self.hit_latest(point, monotonic())
        if not self.session.hovering and self._crop_retries < 2 and self._valid_frame(frame, point, monotonic()):
            from meikipop.ocr.boundaries import expanded_crop
            crop = expanded_crop(frame, (point.x(), point.y()))
            if crop is not None:
                self._crop_retries += 1
                self.capture_region = QRect(*crop)
                self._request_capture(point)

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
        self._update_hover(QCursor.pos())
        frame = None
        if not self.session.accepts(generation, self.window.is_pinned):
            mark("discard", generation, reason="obsolete_hit")
            return
        # AppKit can leave Qt's active window pointing at the hidden Search
        # popup after another application takes focus.
        if (QApplication.activeWindow() is self.window and not self.window._peek
                and (sys.platform != "darwin" or self.window.isVisible())):
            mark("discard", generation, reason="active_search")
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
        extras = {key: getattr(result, key) for key in ("analyses", "suggestions", "message")
                  if getattr(result, key, None)} if result is not None else {}
        if result is None or not (result.entries or result.kanji or extras.get("analyses") or extras.get("suggestions")):
            self._hide_preview()
            return
        if self.window.show_entries(result.entries, text=result.text, source=result.source,
                                    peek=True, kanji=result.kanji, **extras):
            mark("hit_delivery", frame.request.revision if frame is not None else generation,
                 popup_revision=getattr(self.window, "revision", 0))
            self.window.set_context(*hit.sentence)
            self.window._result_screenshot = frame.snapshot if frame is not None else None
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
