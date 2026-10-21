"""Temporarily exclude the popup without hiding it on supported Windows builds."""
import sys
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class CaptureRequest:
    revision: int
    screen: str
    geometry: tuple
    crop: tuple
    scale: float
    generation: int
    frozen: bool = False
    full_snapshot: bool = False

    def physical_crop(self, physical_geometry):
        x, y, width, height = self.crop
        gx, gy, gw, gh = self.geometry
        px, py, pw, ph = physical_geometry
        sx, sy = pw / gw, ph / gh
        return (px + round((x - gx) * sx), py + round((y - gy) * sy),
                round(width * sx), round(height * sy))


@dataclass(frozen=True)
class PixelFrame:
    request: CaptureRequest
    size: tuple
    pixels: bytes
    captured_at: float
    mode: str = "RGB"
    stride: int = 0
    physical_crop: tuple = ()

    def image(self):
        from PIL import Image
        return Image.frombytes("RGB", self.size, self.pixels, "raw", self.mode, self.stride)

    def cropped(self, request):
        x, y, width, height = request.crop
        left, top, sw, sh = self.request.crop
        sx, sy = self.size[0] / sw, self.size[1] / sh
        a, b = round((x - left) * sx), round((y - top) * sy)
        w, h = round(width * sx), round(height * sy)
        physical = (self.physical_crop[0] + a, self.physical_crop[1] + b, w, h) if self.physical_crop else ()
        channels = {"RGB": 3, "BGR": 3, "RGBX": 4, "BGRX": 4}.get(self.mode)
        stride = self.stride or self.size[0] * (channels or 0)
        if (channels and stride >= self.size[0] * channels and len(self.pixels) >= stride * self.size[1]
                and 0 <= a < a + w <= self.size[0] and 0 <= b < b + h <= self.size[1]):
            # Retain the full frozen frame; decode only the selected rows downstream.
            rows = memoryview(self.pixels)
            pixels = b"".join(rows[offset:offset + w * channels]
                              for offset in range(b * stride + a * channels,
                                                  (b + h) * stride + a * channels, stride))
            return PixelFrame(request, (w, h), pixels, self.captured_at, self.mode, physical_crop=physical)
        image = self.image().crop((a, b, a + w, b + h))
        return PixelFrame(request, image.size, image.tobytes(), self.captured_at, physical_crop=physical)


def _screen_geometry(name, rectangles, geometry=None, scale=1):
    if name in rectangles:
        return rectangles[name]
    if geometry is not None:
        x, y, width, height = geometry
        # Qt can expose the monitor's friendly name instead of its GDI ID.
        # Windows screen origins stay native; Qt scales only their size.
        expected = (x, y, round(width * scale), round(height * scale))
        matches = [rect for rect in rectangles.values()
                   if rect[:2] == expected[:2] and
                   all(abs(value - target) <= 1 for value, target in zip(rect[2:], expected[2:]))]
        if len(matches) == 1:
            return matches[0]
    raise RuntimeError("Display changed. Try scanning again.")


def windows_screen_geometry(name, geometry=None, scale=1):
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD), ("device", wintypes.WCHAR * 32)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    rectangles = {}
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    @callback_type
    def found(handle, dc, rect, data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            box = info.monitor
            rectangles[info.device] = (box.left, box.top, box.right - box.left, box.bottom - box.top)
        return True

    user32.EnumDisplayMonitors(None, None, found, 0)
    return _screen_geometry(name, rectangles, geometry, scale)


class RegionCapture:
    """Create, use and close the existing MSS backend on its owning worker."""
    def __init__(self):
        import mss
        self.backend = mss.mss()

    def capture(self, request):
        crop = request.physical_crop(windows_screen_geometry(request.screen, request.geometry, request.scale))
        left, top, width, height = crop
        screenshot = self.backend.grab(dict(left=left, top=top, width=width, height=height))
        return PixelFrame(request, (width, height), bytes(screenshot.bgra), monotonic(), "BGRX", 0, crop)

    def close(self):
        self.backend.close()


def exclude_from_capture(window, enabled):
    if sys.platform != "win32" or sys.getwindowsversion().build < 19041:
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    changed = bool(user32.SetWindowDisplayAffinity(int(window.winId()), 0x11 if enabled else 0))
    if changed:
        ctypes.WinDLL("dwmapi").DwmFlush()
    return changed
