import ctypes
import logging
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from PIL import Image
from .chrome_screen_ai_pb2 import VisualAnnotation
from .component import find_component_directory, library_names

from meikipop.ocr.interface import OcrProvider, Paragraph, Word, BoundingBox
from meikipop.ocr.providers.postprocessing import group_lines_into_paragraphs, _merge_bounding_boxes

JAPANESE_REGEX = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f\U00020000-\U000323af]')

logger = logging.getLogger(__name__)


@contextmanager
def suppress_output():
    """Native logging may have no standard descriptors under pythonw.exe."""
    saved = []
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        for descriptor in (1, 2):
            try:
                backup = os.dup(descriptor)
                saved.append((descriptor, backup))
                os.dup2(devnull, descriptor)
            except OSError:
                pass
        yield
    finally:
        for descriptor, backup in saved:
            os.dup2(backup, descriptor)
            os.close(backup)
        os.close(devnull)


class ScreenAiOcr(OcrProvider):
    NAME = "Chrome Screen AI (local)"

    # Class-level variables to ensure the native DLL is only initialized ONCE per app lifetime
    _is_initialized = False
    _lib = None
    _SkBitmap = None
    _cb1 = None
    _cb2 = None
    _directory = None
    _lock = threading.RLock()

    def __init__(self, component_directory=None, language="ja"):
        self.language = language
        self.model_dir = find_component_directory(component_directory)
        self.dll_path = next(self.model_dir / name for name in library_names() if (self.model_dir / name).is_file())
        with self._lock:
            self._initialize_library()
        maximum = getattr(self.lib, 'GetMaxImageDimension', None)
        if maximum is not None:
            maximum.argtypes, maximum.restype = [], ctypes.c_uint32
        self.max_dimension = min(int(maximum()) or 2048, 4096) if maximum else 2048

    def _initialize_library(self):
        # If already initialized by a previous instance, reuse the loaded lib and exit
        if ScreenAiOcr._is_initialized:
            if self.model_dir != ScreenAiOcr._directory:
                raise RuntimeError("Restart Meikipop to load a different Chrome Screen AI component.")
            self.lib = ScreenAiOcr._lib
            self.SkBitmap = ScreenAiOcr._SkBitmap
            return

        class SkColorInfo(ctypes.Structure):
            _fields_ = [('fColorSpace', ctypes.c_void_p), ('fColorType', ctypes.c_int32),
                        ('fAlphaType', ctypes.c_int32)]

        class SkISize(ctypes.Structure):
            _fields_ = [('fWidth', ctypes.c_int32), ('fHeight', ctypes.c_int32)]

        class SkImageInfo(ctypes.Structure):
            _fields_ = [('fColorInfo', SkColorInfo), ('fDimensions', SkISize)]

        class SkPixmap(ctypes.Structure):
            _fields_ = [('fPixels', ctypes.c_void_p), ('fRowBytes', ctypes.c_size_t), ('fInfo', SkImageInfo)]

        class SkBitmap(ctypes.Structure):
            _fields_ = [('fPixelRef', ctypes.c_void_p), ('fPixmap', SkPixmap), ('fFlags', ctypes.c_uint32)]

        self.SkBitmap = SkBitmap
        # linux fails to load lib without RTLD_LAZY
        try:
            self.lib = ctypes.CDLL(str(self.dll_path), **({'mode': os.RTLD_LAZY} if hasattr(os, 'RTLD_LAZY') else {}))
        except OSError as error:
            raise RuntimeError("Chrome Screen AI cannot load. Choose the complete component for this OS and CPU architecture.") from error

        def read_model(raw_path):
            try:
                path = (self.model_dir / raw_path.decode('utf-8')).resolve()
                return path.read_bytes() if path.is_relative_to(self.model_dir) else b''
            except (OSError, ValueError, UnicodeError, AttributeError):
                return b''

        @ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_char_p)
        def get_file_content_size(p):
            return len(read_model(p))

        @ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p)
        def get_file_content(p, s, ptr):
            data = read_model(p)
            if data and ptr:
                ctypes.memmove(ptr, data, min(s, len(data)))

        # Store callbacks at the class level so Python's Garbage Collector doesn't delete them
        ScreenAiOcr._cb1 = get_file_content_size
        ScreenAiOcr._cb2 = get_file_content

        self.lib.SetFileContentFunctions.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.lib.SetFileContentFunctions.restype = None
        self.lib.InitOCRUsingCallback.argtypes = []
        self.lib.InitOCRUsingCallback.restype = ctypes.c_bool
        self.lib.SetOCRLightMode.argtypes = [ctypes.c_bool]
        self.lib.SetOCRLightMode.restype = None
        self.lib.PerformOCR.argtypes = [ctypes.POINTER(SkBitmap), ctypes.POINTER(ctypes.c_uint32)]
        self.lib.PerformOCR.restype = ctypes.c_void_p
        self.lib.FreeLibraryAllocatedCharArray.argtypes = [ctypes.c_void_p]
        self.lib.FreeLibraryAllocatedCharArray.restype = None

        # Suppress the initialization logs
        with suppress_output():
            self.lib.SetFileContentFunctions(ScreenAiOcr._cb1, ScreenAiOcr._cb2)
            self.lib.SetOCRLightMode(False)
            if not self.lib.InitOCRUsingCallback():
                raise RuntimeError("Chrome Screen AI initialization failed. Keep the component's model files beside its native library.")

        # Mark as globally initialized
        ScreenAiOcr._lib = self.lib
        ScreenAiOcr._SkBitmap = self.SkBitmap
        ScreenAiOcr._directory = self.model_dir
        ScreenAiOcr._is_initialized = True

    def _bitmap(self, image):
        """Back SkBitmap with a stable SkPixelRef, including on current macOS.

        ABI reference: Meikikai _screen_ai.py, commit 50efb401 (GPL-3.0),
        https://github.com/hectahertz/meikikai/tree/50efb401/src/meikikai/ocr/providers/chrome_screen_ai
        """
        class PixelRef(ctypes.Structure):
            _fields_ = [('vtable', ctypes.c_void_p), ('references', ctypes.c_int32),
                        ('padding', ctypes.c_byte * (ctypes.sizeof(ctypes.c_void_p) - 4)),
                        ('width', ctypes.c_int32), ('height', ctypes.c_int32),
                        ('pixels', ctypes.c_void_p), ('stride', ctypes.c_size_t), ('reserved', ctypes.c_byte * 64)]

        pixels = ctypes.create_string_buffer(image.tobytes('raw', 'BGRA'))
        vtable = (ctypes.c_void_p * 16)()
        reference = PixelRef(vtable=ctypes.addressof(vtable), references=1, width=image.width,
                             height=image.height, pixels=ctypes.addressof(pixels), stride=image.width * 4)
        bitmap = self.SkBitmap()
        bitmap.fPixelRef = ctypes.addressof(reference)
        bitmap.fPixmap.fPixels = ctypes.addressof(pixels)
        bitmap.fPixmap.fRowBytes = image.width * 4
        bitmap.fPixmap.fInfo.fColorInfo.fColorType = 6  # Skia kBGRA_8888.
        bitmap.fPixmap.fInfo.fColorInfo.fAlphaType = 1  # Opaque RGB capture.
        bitmap.fPixmap.fInfo.fDimensions.fWidth = image.width
        bitmap.fPixmap.fInfo.fDimensions.fHeight = image.height
        bitmap._backing = (pixels, reference, vtable)
        return bitmap

    def scan(self, image: Image.Image) -> Optional[List[Paragraph]]:
        try:
            if image.width <= 0 or image.height <= 0:
                return []
            img_rgba = image.convert('RGB').convert('RGBA')
            img_rgba.thumbnail((self.max_dimension, self.max_dimension), Image.Resampling.LANCZOS)
            width, height = img_rgba.size
            bitmap = self._bitmap(img_rgba)
            output_length = ctypes.c_uint32(0)
            with self._lock, suppress_output():
                result_ptr = self.lib.PerformOCR(ctypes.byref(bitmap), ctypes.byref(output_length))
                if not result_ptr:
                    return []
                try:
                    if output_length.value > 32_000_000:
                        raise RuntimeError("Invalid Chrome Screen AI response size")
                    proto_bytes = ctypes.string_at(result_ptr, output_length.value)
                finally:
                    self.lib.FreeLibraryAllocatedCharArray(result_ptr)

            response = VisualAnnotation()
            response.ParseFromString(proto_bytes)

            return self._transform(response, width, height)

        except Exception as e:
            logger.error(f"{self.NAME} error: {e}", exc_info=True)
            raise RuntimeError(f"Chrome Screen AI recognition failed: {e}") from e

    def _transform(self, response: VisualAnnotation, img_w: int, img_h: int) -> List[Paragraph]:
        def box(rect):
            if rect.width <= 0 or rect.height <= 0:
                return None
            return BoundingBox((rect.x + rect.width / 2) / img_w, (rect.y + rect.height / 2) / img_h,
                               rect.width / img_w, rect.height / img_h)

        raw_lines = []
        for line_box in response.lines:
            words_in_line = []
            for word_box in line_box.words:
                symbols = [s for s in word_box.symbols if s.utf8_string]
                separator = ' ' if word_box.has_space_after else ''
                if symbols and all(box(s.bounding_box) for s in symbols):
                    words_in_line.extend(Word(s.utf8_string, separator if i == len(symbols)-1 else '', box(s.bounding_box))
                                         for i, s in enumerate(symbols))
                elif word_box.utf8_string and box(word_box.bounding_box):
                    words_in_line.append(Word(word_box.utf8_string, separator, box(word_box.bounding_box)))
            full_text = line_box.utf8_string or ''.join(w.text + w.separator for w in words_in_line).rstrip()
            if not full_text or self.language == "ja" and not JAPANESE_REGEX.search(full_text):
                continue
            line_bbox = box(line_box.bounding_box) or _merge_bounding_boxes([w.box for w in words_in_line])
            if not line_bbox.width or not line_bbox.height:
                continue
            if not words_in_line:
                words_in_line = [Word(full_text, '', line_bbox)]
            is_vertical = line_box.direction == 3 or (line_box.direction == 0 and
                            line_bbox.height * img_h > line_bbox.width * img_w * 1.5)
            raw_lines.append(Paragraph(full_text, words_in_line, line_bbox, is_vertical))
        if self.language != "ja":
            from meikipop.ocr.context import fragment_paragraphs
            lines = [(line.full_text, [(word.text, (
                (word.box.center_x - word.box.width / 2) * img_w,
                (word.box.center_y - word.box.height / 2) * img_h,
                (word.box.center_x + word.box.width / 2) * img_w,
                (word.box.center_y + word.box.height / 2) * img_h)) for word in line.words]) for line in raw_lines]
            return fragment_paragraphs(lines, img_w, img_h, self.language)
        return group_lines_into_paragraphs(raw_lines)
