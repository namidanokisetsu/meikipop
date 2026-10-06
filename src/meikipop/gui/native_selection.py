"""Windows UI Automation selection reads, confined to one background thread."""
from dataclasses import dataclass
import math
import threading

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class NativeSelection:
    status: str = "unsupported"
    text: str = ""
    rectangles: tuple = ()


def read_selection(automation, api, foreground):
    element = automation.GetFocusedElement()
    if not element:
        return NativeSelection()
    if element.CurrentIsPassword:
        return NativeSelection("blocked")
    root = automation.ElementFromHandle(foreground)
    ancestor = element
    for _ in range(32):
        if automation.CompareElements(ancestor, root):
            break
        ancestor = automation.RawViewWalker.GetParentElement(ancestor)
        if not ancestor:
            return NativeSelection("blocked")
    else:
        return NativeSelection("blocked")
    pattern = element.GetCurrentPattern(api.UIA_TextPatternId)
    if not pattern:
        return NativeSelection()
    pattern = pattern.QueryInterface(api.IUIAutomationTextPattern)
    ranges = pattern.GetSelection()
    if not ranges or not ranges.Length:
        return NativeSelection("empty")
    if ranges.Length > 16:
        return NativeSelection("blocked")
    texts, rectangles = [], []
    for index in range(ranges.Length):
        selected = ranges.GetElement(index)
        text = selected.GetText(2001)
        if text:
            texts.append(text)
        if sum(map(len, texts)) + len(texts) - 1 > 2000:
            return NativeSelection("blocked")
        bounds = selected.GetBoundingRectangles() or ()
        for offset in range(0, min(len(bounds), 256) - 3, 4):
            rect = tuple(bounds[offset:offset + 4])
            if all(math.isfinite(n) for n in rect) and rect[2] > 0 and rect[3] > 0:
                rectangles.append(rect)
    text = "\n".join(texts)
    return NativeSelection("selected" if text.strip() else "empty", text, tuple(rectangles))


class NativeSelectionReader(QObject):
    completed = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None

    def request(self, revision, foreground):
        if self.thread is not None and self.thread.is_alive():
            return False
        # Initialize comtypes on the GUI apartment before the MTA worker imports it.
        try:
            import comtypes
        except ImportError:
            return False

        def read():
            result = NativeSelection()
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            automation = None
            try:
                from comtypes.client import CreateObject, GetModule
                api = GetModule("UIAutomationCore.dll")
                automation = CreateObject(api.CUIAutomation, interface=api.IUIAutomation)
                result = read_selection(automation, api, foreground)
            except Exception:
                pass  # Unsupported or unresponsive providers use the copy fallback.
            finally:
                del automation
                comtypes.CoUninitialize()
            try:
                self.completed.emit(revision, result)
            except RuntimeError:
                pass

        self.thread = threading.Thread(target=read, name="SelectedText", daemon=True)
        self.thread.start()
        return True


def selection_bounds(rectangles):
    """Convert UIA physical rectangles using each monitor's actual geometry."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication
    from meikipop.utils.capture import windows_screen_geometry
    screens = QApplication.screens()
    screens.sort(key=lambda screen: not screen.geometry().contains(QCursor.pos()))
    for screen in screens:
        try:
            px, py, pw, ph = windows_screen_geometry(screen.name())
        except (OSError, RuntimeError, ValueError):
            continue
        geometry = screen.geometry()
        bounds = QRect()
        for x, y, width, height in rectangles:
            if not (px <= x + width / 2 < px + pw and py <= y + height / 2 < py + ph):
                continue
            rect = QRect(geometry.x() + round((x - px) * geometry.width() / pw),
                         geometry.y() + round((y - py) * geometry.height() / ph),
                         max(1, round(width * geometry.width() / pw)),
                         max(1, round(height * geometry.height() / ph)))
            bounds = bounds.united(rect)
        if not bounds.isNull():
            return bounds.intersected(screen.availableGeometry())
    return None
