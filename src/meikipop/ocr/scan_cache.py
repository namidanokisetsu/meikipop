"""Reuse recognition when only the pointer, rather than the image, changes."""


class ScanCache:
    def __init__(self):
        self.key = None
        self.result = None

    def scan(self, image, recognize):
        geometry = getattr(image, "shape", None)
        if geometry is None:
            geometry = image.size
        key = (recognize, geometry, getattr(image, "mode", None), image.tobytes())
        if key != self.key:
            result = recognize(image)
            # Do not retain failures; allow the next request to retry.
            if result is not None:
                self.key, self.result = key, result
            return result
        return self.result
