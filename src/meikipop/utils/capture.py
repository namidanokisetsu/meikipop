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
        image = self.image().crop((a, b, a + w, b + h))
        physical = (self.physical_crop[0] + a, self.physical_crop[1] + b, w, h) if self.physical_crop else ()
        return PixelFrame(request, image.size, image.tobytes(), self.captured_at, physical_crop=physical)


def windows_screen_geometry(name):
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
    if name not in rectangles:
        raise RuntimeError("Display changed. Try scanning again.")
    return rectangles[name]


class RegionCapture:
    """Create, use and close the existing MSS backend on its owning worker."""
    def __init__(self):
        import mss
        self.backend = mss.mss()

    def capture(self, request):
        crop = request.physical_crop(windows_screen_geometry(request.screen))
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
