"""Optional wheel navigation through rendered dictionary sections."""
from bisect import bisect_left, bisect_right

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt
from PyQt6.QtGui import QTextCursor


SECTION_PREFIX = "scroll-section-"


class SectionScroller(QObject):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.enabled = False
        self._positions = None
        self._wheel_delta = 0
        self._gesture_delta = 0
        self._gesture_advanced = False
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(220)
        self._idle.timeout.connect(self._reset_gesture)
        browser.viewport().installEventFilter(self)
        browser.document().contentsChanged.connect(self._document_changed)

    def set_enabled(self, enabled):
        if self.enabled != bool(enabled):
            self.enabled = bool(enabled)
            self._reset_gesture()

    def _reset_gesture(self):
        self._idle.stop()
        self._wheel_delta = self._gesture_delta = 0
        self._gesture_advanced = False

    def _document_changed(self):
        self._positions = None
        self._reset_gesture()

    def section_tops(self):
        document = self.browser.document()
        if self._positions is None:
            positions = set()
            block = document.begin()
            while block.isValid():
                if any(name.startswith(SECTION_PREFIX) for name in block.charFormat().anchorNames()):
                    positions.add(block.position())
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if any(name.startswith(SECTION_PREFIX) for name in fragment.charFormat().anchorNames()):
                        positions.add(fragment.position())
                    iterator += 1
                block = block.next()
            self._positions = sorted(positions)
        bar = self.browser.verticalScrollBar()
        tops = []
        cursor = QTextCursor(document)
        for position in self._positions:
            cursor.setPosition(position)
            tops.append(max(0, self.browser.cursorRect(cursor).top() + bar.value()))
        # Context and metadata belong to the first section.
        return [0, *tops[1:]]

    def stops(self):
        bar = self.browser.verticalScrollBar()
        height = max(1, self.browser.viewport().height())
        overlap = min(height // 3, max(24, self.browser.fontMetrics().lineSpacing() * 2))
        step = max(1, height - overlap)
        tops = self.section_tops()
        stops = {0, bar.maximum()}
        for start, end in zip(tops, [*tops[1:], bar.maximum() + height]):
            stops.add(min(start, bar.maximum()))
            if end - start > height:
                stops.update(range(start + step, min(end, bar.maximum()), step))
        return sorted(stops)

    def advance(self, direction):
        bar = self.browser.verticalScrollBar()
        stops = self.stops()
        if direction > 0:
            index = bisect_right(stops, bar.value())
            target = stops[min(index, len(stops) - 1)]
        else:
            index = bisect_left(stops, bar.value()) - 1
            target = stops[max(0, index)]
        bar.setValue(target)

    def eventFilter(self, watched, event):
        if (event.type() != QEvent.Type.Wheel or not self.enabled
                or event.modifiers() != Qt.KeyboardModifier.NoModifier
                or self.browser.selecting):
            return False
        pixel, angle, phase = event.pixelDelta(), event.angleDelta(), event.phase()
        delta = pixel if not pixel.isNull() else angle
        if abs(delta.x()) > abs(delta.y()):
            return False
        if phase in (Qt.ScrollPhase.ScrollBegin, Qt.ScrollPhase.ScrollEnd):
            self._reset_gesture()
        if phase == Qt.ScrollPhase.ScrollEnd:
            event.accept()
            return True
        if phase != Qt.ScrollPhase.NoScrollPhase:
            self._idle.stop()
        else:
            self._idle.start()
        if phase != Qt.ScrollPhase.ScrollMomentum:
            if not pixel.isNull() or phase != Qt.ScrollPhase.NoScrollPhase:
                self._gesture_delta += delta.y()
                threshold = 40 if not pixel.isNull() else 120
                if not self._gesture_advanced and abs(self._gesture_delta) >= threshold:
                    self.advance(1 if self._gesture_delta < 0 else -1)
                    self._gesture_advanced = True
            else:
                self._wheel_delta += angle.y()
                while abs(self._wheel_delta) >= 120:
                    direction = 1 if self._wheel_delta < 0 else -1
                    self.advance(direction)
                    self._wheel_delta += direction * 120
        event.accept()
        return True
