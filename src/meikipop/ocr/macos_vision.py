"""Offline macOS Vision OCR with the shared popup's normalized geometry."""
from __future__ import annotations

from io import BytesIO
import re
import sys

from PIL import Image

from meikipop.ocr.interface import BoundingBox, Paragraph, Word


def _language_id(language: str, supported) -> str:
    requested = language.replace("_", "-").lower()
    available = {str(code).lower(): str(code) for code in supported}
    if requested in available:
        return available[requested]
    matches = [code for key, code in available.items() if key.split("-")[0] == requested.split("-")[0]]
    if matches:
        return matches[0]
    raise RuntimeError(
        f"This macOS version does not support {language!r} screen recognition. "
        "Use typed or selected text lookup, or update macOS."
    )


def _normalized_box(rect) -> BoundingBox:
    # CGRect values bridge as nested tuples; Vision's origin is bottom-left.
    (x, y), (width, height) = rect
    left, right = max(0.0, float(x)), min(1.0, float(x + width))
    top, bottom = max(0.0, 1.0 - float(y + height)), min(1.0, 1.0 - float(y))
    return BoundingBox((left + right) / 2, (top + bottom) / 2, max(0.0, right - left), max(0.0, bottom - top))


def _paragraph(observation, language: str, image_size) -> Paragraph | None:
    candidates = observation.topCandidates_(1)
    if not candidates:
        return None
    candidate = candidates[0]
    original = str(candidate.string())
    text = original.strip()
    if not text:
        return None
    leading = len(original) - len(original.lstrip())
    line_box = _normalized_box(observation.boundingBox())
    if line_box.width <= 0 or line_box.height <= 0:
        return None
    # NSString ranges count UTF-16 code units, not Python Unicode codepoints.
    utf16 = [0]
    for character in original:
        utf16.append(utf16[-1] + (2 if ord(character) > 0xFFFF else 1))
    per_character = language.split("-")[0].lower() in {"ja", "zh"}
    spans = list(re.finditer(r"\S" if per_character else r"\S+", text))
    words = []
    for index, span in enumerate(spans):
        start, end = leading + span.start(), leading + span.end()
        rectangle, error = candidate.boundingBoxForRange_error_((utf16[start], utf16[end] - utf16[start]), None)
        if error is not None or rectangle is None:
            # Keep complete context and correct offsets when Vision only has
            # a line box; never silently drop a word whose box is unavailable.
            words = [Word(text, "", line_box)]
            break
        box = _normalized_box(rectangle.boundingBox())
        next_start = spans[index + 1].start() if index + 1 < len(spans) else len(text)
        separator = text[span.end():next_start]
        # The accurate recognizer can return a whole word's box for character
        # ranges. Merge identical adjacent boxes for character interpolation.
        if per_character and words and words[-1].box == box and not words[-1].separator:
            previous = words.pop()
            words.append(Word(previous.text + span.group(), separator, box))
        else:
            words.append(Word(span.group(), separator, box))
    width, height = image_size
    vertical = line_box.height * height > line_box.width * width * 1.5
    return Paragraph(text, words, line_box, vertical)


def recognize(image: Image.Image, language: str = "ja") -> list[Paragraph]:
    """Recognize a PIL image using installed Apple language support only.

    Apple documents the language query and range boxes at:
    https://developer.apple.com/documentation/vision/vnrecognizetextrequest
    https://developer.apple.com/documentation/vision/vnrecognizedtext
    """
    if sys.platform != "darwin":
        raise RuntimeError("Apple Vision screen recognition is available on macOS only.")
    if not isinstance(image, Image.Image) or min(image.size) < 1:
        raise ValueError("Screen recognition needs a nonempty image.")
    if not isinstance(language, str) or not language.strip():
        raise ValueError("Choose a language for screen recognition.")
    try:
        import objc
        import Vision
        from Foundation import NSData
    except ImportError as error:
        raise RuntimeError("Apple Vision is unavailable. Reinstall Meikipop with its macOS dependencies.") from error

    with objc.autorelease_pool():
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        supported, error = request.supportedRecognitionLanguagesAndReturnError_(None)
        if error is not None or supported is None:
            raise RuntimeError("macOS could not list its installed recognition languages.")
        selected = _language_id(language, supported)
        request.setRecognitionLanguages_([selected])
        request.setUsesLanguageCorrection_(True)
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        raw = buffer.getvalue()
        data = NSData.dataWithBytes_length_(raw, len(raw))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
        succeeded, error = handler.performRequests_error_([request], None)
        if not succeeded or error is not None:
            detail = str(error.localizedDescription()) if hasattr(error, "localizedDescription") else str(error or "unknown error")
            raise RuntimeError(f"macOS screen recognition failed: {detail}")
        paragraphs = []
        for observation in request.results() or ():
            paragraph = _paragraph(observation, selected, image.size)
            if paragraph is not None:
                paragraphs.append(paragraph)
        return paragraphs
