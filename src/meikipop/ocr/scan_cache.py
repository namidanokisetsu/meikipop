"""Reuse recognition when only the pointer, rather than the image, changes."""
from meikipop.utils.timing import mark


class ScanCache:
    def __init__(self):
        self.key = None
        self.result = None
        self.revision = 0

    def scan(self, image, recognize):
        geometry = getattr(image, "shape", None)
        if geometry is None:
            geometry = image.size
        key = (recognize, geometry, getattr(image, "mode", None), image.tobytes())
        if key != self.key:
            mark("ocr_begin", self.revision + 1)
            result = recognize(image)
            # Do not retain failures; allow the next request to retry.
            if result is not None:
                self.key, self.result = key, result
                self.revision += 1
            return result
        mark("ocr_reused", self.revision)
        return self.result
