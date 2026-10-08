"""Optional animated section navigation with a persistent lexical heading."""
from bisect import bisect_left, bisect_right

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QTextCursor
from PyQt6.QtWidgets import QProgressBar

from meikipop.gui.ruby import RubyBrowser


SECTION_PREFIX = "scroll-section-"


class ReadingProgress(QProgressBar):
    def __init__(self, parent):
        super().__init__(parent)
        self.setRange(0, 1000)
        self.setValue(0)
        self.setOrientation(Qt.Orientation.Vertical)
        self.setTextVisible(False)
        self.setAccessibleName("Reading progress")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):
        from meikipop.config.config import config
        from meikipop.gui.popup_style import surface_colors
        colors = surface_colors(config.color_background, config.color_foreground)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(colors["border"]))
        painter.fillRect(0, 0, self.width(), round(self.height() * self.value() / 1000),
                         QColor(config.color_highlight_word))


class SectionScroller(QObject):
    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.enabled = False
        self.preview = False
        self._positions = None
        self._headings = []
        self._heading = None
        self._wheel_delta = 0
        self._gesture_delta = 0
        self._gesture_start = None
        self._target = None
        from meikipop.utils.window_focus import reduce_motion_enabled
        self.animation_enabled = not reduce_motion_enabled()
        self.animation = QPropertyAnimation(browser.verticalScrollBar(), b"value", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._animation_finished)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(120)
        self._idle.timeout.connect(self._settle)
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.timeout.connect(self._refresh_header)
        self.header = RubyBrowser(browser.viewport(), selection_lookup=False)
        self.header.setAccessibleName("Current headword")
        self.header.setFrameShape(self.header.Shape.NoFrame)
        self.header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.header.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.header.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header.hide()
        self.progress = ReadingProgress(browser)
        self._viewport_margins = browser.viewportMargins()
        self.header.viewport().installEventFilter(self)
        browser.installEventFilter(self)
        browser.viewport().installEventFilter(self)
        browser.document().contentsChanged.connect(self._document_changed)
        browser.verticalScrollBar().valueChanged.connect(self._update_header)
        browser.verticalScrollBar().valueChanged.connect(self._update_progress)
        browser.verticalScrollBar().rangeChanged.connect(lambda *_: self._refresh.start(0))
        self._scrollbar_policy = browser.verticalScrollBarPolicy()

    def set_enabled(self, enabled):
        if self.enabled != bool(enabled):
            self.enabled = bool(enabled)
            self.cancel()
            self.browser.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff if enabled else self._scrollbar_policy)
            margins = self._viewport_margins
            self.browser.setViewportMargins(margins.left(), margins.top(),
                                            margins.right() + (7 if enabled else 0), margins.bottom())
            self._refresh_header()

    def set_preview(self, preview):
        if self.preview != preview:
            self.preview = preview
            self._refresh_header()

    def cancel(self):
        self.animation.stop()
        self._target = None
        self._idle.stop()
        self._wheel_delta = self._gesture_delta = 0
        self._gesture_start = None

    def _animation_finished(self):
        self._target = None

    def _document_changed(self):
        self.cancel()
        self._positions = None
        self._heading = None
        self._headings = []
        self._refresh.start(0)

    def _index(self):
        if self._positions is not None:
            return
        positions = set()
        self._headings = []
        block = self.browser.document().begin()
        while block.isValid():
            names = set(block.charFormat().anchorNames())
            if any(name.startswith(SECTION_PREFIX) for name in names):
                positions.add(block.position())
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                names.update(fragment.charFormat().anchorNames())
                if any(name.startswith(SECTION_PREFIX) for name in fragment.charFormat().anchorNames()):
                    positions.add(fragment.position())
                iterator += 1
            if any(name.startswith("scroll-headword-") for name in names):
                self._headings.append(block.position())
            block = block.next()
        self._positions = sorted(positions)

    def _top(self, position):
        cursor = QTextCursor(self.browser.document())
        cursor.setPosition(position)
        return self.browser.cursorRect(cursor).top() + self.browser.verticalScrollBar().value()

    def section_tops(self):
        self._index()
        return [0, *(max(0, self._top(position)) for position in self._positions[1:])]

    def _refresh_header(self):
        self._index()
        self._update_progress()
        visible = self.enabled and not self.preview and bool(self._headings)
        if not visible:
            self.header.hide()
            return
        # Keep the original heading's typography, including Japanese ruby.
        document = self.browser.document()
        from meikipop.config.config import config
        self.header.setStyleSheet(f"QTextBrowser {{background:{config.color_background};border:0;}}")
        height = min(100, max(32, max(round(document.documentLayout().blockBoundingRect(
            document.findBlock(position)).height()) for position in self._headings) + 8))
        self.header.setGeometry(0, 0, self.browser.viewport().width(), height)
        self._heading = None
        self._update_header()
        self._update_progress()

    def progress_fraction(self):
        bar = self.browser.verticalScrollBar()
        maximum = bar.maximum()
        if not maximum:
            return 0.0
        heading = self.header.height() if self._headings and not self.preview else 0
        boundaries = sorted({0, maximum, *(min(maximum, max(0, top - heading))
                                         for top in self.section_tops())})
        value = bar.value()
        if value >= maximum:
            return 1.0
        index = max(0, bisect_right(boundaries, value) - 1)
        start, end = boundaries[index:index + 2]
        return (index + (value - start) / (end - start)) / (len(boundaries) - 1)

    def _update_progress(self):
        visible = self.enabled and self.browser.verticalScrollBar().maximum() > 0
        self.progress.setVisible(visible)
        if visible:
            viewport = self.browser.viewport().geometry()
            self.progress.setGeometry(viewport.right() + 3, viewport.top() + 4,
                                      2, max(1, viewport.height() - 8))
            self.progress.setValue(round(1000 * self.progress_fraction()))
            self.progress.raise_()
            self.progress.update()

    def _update_header(self):
        if not self.enabled or self.preview or not self._headings:
            return
        scroll = self.browser.verticalScrollBar().value()
        tops = [self._top(pos) for pos in self._headings]
        index = max(0, bisect_right(tops, scroll) - 1)
        position = self._headings[index]
        offset = min(0, tops[index + 1] - scroll - self.header.height()) if index + 1 < len(tops) else 0
        self.header.move(0, offset)
        self.header.setVisible(tops[index] < scroll)
        if self._heading == position:
            return
        self._heading = position
        cursor = QTextCursor(self.browser.document().findBlock(position))
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        document = self.header.document()
        document.clear()
        document.setDefaultFont(self.browser.document().defaultFont())
        document.setDefaultStyleSheet(self.browser.document().defaultStyleSheet())
        target = QTextCursor(document)
        target.insertFragment(cursor.selection())
        # Ruby char formats and the registered object renderer are preserved.
        fmt = target.blockFormat()
        fmt.setTopMargin(0)
        fmt.setBottomMargin(0)
        target.setBlockFormat(fmt)
        self.header.verticalScrollBar().setValue(0)

    def stops(self):
        bar = self.browser.verticalScrollBar()
        heading_height = self.header.height() if self._headings and not self.preview else 0
        height = max(1, self.browser.viewport().height() - heading_height)
        overlap = min(height // 3, max(24, self.browser.fontMetrics().lineSpacing() * 2))
        step = max(1, height - overlap)
        tops = [max(0, top - heading_height) for top in self.section_tops()]
        stops = {0, bar.maximum()}
        for start, end in zip(tops, [*tops[1:], bar.maximum() + height]):
            stops.add(min(start, bar.maximum()))
            if end - start > height:
                stops.update(range(start + step, min(end, bar.maximum()), step))
        return sorted(stops)

    def _move(self, target):
        bar = self.browser.verticalScrollBar()
        target = max(0, min(target, bar.maximum()))
        self.animation.stop()
        self._target = target
        distance = abs(target - bar.value())
        if not distance:
            self._target = None
            return
        if not self.animation_enabled:
            bar.setValue(target)
            self._target = None
            return
        self.animation.setDuration(min(280, 140 + distance // 4))
        self.animation.setStartValue(bar.value())
        self.animation.setEndValue(target)
        self.animation.start()

    def advance(self, direction, page=False):
        bar = self.browser.verticalScrollBar()
        value = self._target if self._target is not None else bar.value()
        stops = self.stops()
        if page:
            self._move(value + direction * max(1, self.browser.viewport().height() - 24))
        elif direction > 0:
            self._move(stops[min(bisect_right(stops, value), len(stops) - 1)])
        else:
            self._move(stops[max(0, bisect_left(stops, value) - 1)])

    def _settle(self):
        if self._gesture_start is None:
            return
        value = self.browser.verticalScrollBar().value()
        stops = self.stops()
        target = min(stops, key=lambda stop: abs(stop - value))
        # A deliberate short flick still advances; long gestures retain momentum.
        if abs(self._gesture_delta) >= 40:
            if self._gesture_delta < 0 and target <= self._gesture_start:
                target = stops[min(bisect_right(stops, self._gesture_start), len(stops) - 1)]
            elif self._gesture_delta > 0 and target >= self._gesture_start:
                target = stops[max(0, bisect_left(stops, self._gesture_start) - 1)]
        self._gesture_start = None
        self._gesture_delta = 0
        self._move(target)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.browser and kind in (QEvent.Type.Hide, QEvent.Type.Resize):
            self.cancel()
            if kind == QEvent.Type.Resize:
                self._refresh.start(0)
        if not self.enabled:
            return False
        if kind == QEvent.Type.KeyPress and watched is self.browser:
            if event.modifiers() != Qt.KeyboardModifier.NoModifier:
                return False
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
                self._idle.stop()
                self._gesture_start = None
                self.advance(-1 if key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp) else 1,
                             page=key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown))
            elif key in (Qt.Key.Key_Home, Qt.Key.Key_End):
                self.cancel()
                self._move(0 if key == Qt.Key.Key_Home else self.browser.verticalScrollBar().maximum())
            else:
                return False
            event.accept()
            return True
        if kind != QEvent.Type.Wheel or event.modifiers() != Qt.KeyboardModifier.NoModifier or self.browser.selecting:
            return False
        pixel, angle, phase = event.pixelDelta(), event.angleDelta(), event.phase()
        delta = pixel if not pixel.isNull() else angle
        if abs(delta.x()) > abs(delta.y()):
            return False
        if not pixel.isNull() or phase != Qt.ScrollPhase.NoScrollPhase:
            if phase == Qt.ScrollPhase.ScrollBegin or self._gesture_start is None:
                self.cancel()
                self._gesture_start = self.browser.verticalScrollBar().value()
            movement = pixel.y() if not pixel.isNull() else angle.y() / 3
            self._gesture_delta += movement
            bar = self.browser.verticalScrollBar()
            bar.setValue(round(bar.value() - movement))
            # Native trackpad momentum is already decelerated; do not synthesize it twice.
            self._idle.start()
        else:
            self._wheel_delta += angle.y()
            while abs(self._wheel_delta) >= 120:
                direction = 1 if self._wheel_delta < 0 else -1
                self.advance(direction)
                self._wheel_delta += direction * 120
        event.accept()
        return True
