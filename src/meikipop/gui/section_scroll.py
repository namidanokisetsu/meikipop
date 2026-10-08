"""Optional animated section navigation with a persistent lexical heading."""
from bisect import bisect_left, bisect_right

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QSignalBlocker, QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QRegion, QTextCursor, QTextFormat
from PyQt6.QtWidgets import QApplication, QProgressBar

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
        self._boundaries = []
        self._heading = None
        self._target = None
        self._boundary_latched = False
        self._gesture_idle = QTimer(self)
        self._gesture_idle.setSingleShot(True)
        self._gesture_idle.setInterval(180)
        self._gesture_idle.timeout.connect(self._reset_gesture)
        from meikipop.utils.window_focus import reduce_motion_enabled
        self.animation_enabled = not reduce_motion_enabled()
        self.animation = QPropertyAnimation(browser.verticalScrollBar(), b"value", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._animation_finished)
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
        browser.verticalScrollBar().rangeChanged.connect(self._schedule_refresh)
        self._scrollbar_policy = browser.verticalScrollBarPolicy()

    @pyqtSlot()
    def _reset_gesture(self):
        self._boundary_latched = False

    @pyqtSlot(int, int)
    def _schedule_refresh(self, *_):
        self._refresh.start(0)

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

    def _animation_finished(self):
        self._target = None

    def _document_changed(self):
        self.cancel()
        self.header.hide()
        self._boundary_latched = False
        self.browser.viewport().clearMask()
        self._positions = None
        self._heading = None
        self._headings = []
        self._boundaries = []
        self._refresh.start(0)

    def _index(self):
        if self._positions is not None:
            return
        positions = set()
        self._headings = []
        self._boundaries = []
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
            if block.position() in self._headings or "scroll-section-kanji" in names:
                boundary = block
                previous = block.previous()
                if previous.isValid() and previous.blockFormat().hasProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth):
                    boundary = previous
                self._boundaries.append((boundary.position(), block.position() if block.position() in self._headings else None))
            block = block.next()
        self._positions = sorted(positions)

    def _top(self, position):
        cursor = QTextCursor(self.browser.document())
        cursor.setPosition(position)
        return self.browser.cursorRect(cursor).top() + self.browser.verticalScrollBar().value()

    def section_tops(self):
        self._index()
        return [0, *(max(0, self._top(position)) for position in self._positions[1:])]

    def boundaries(self):
        self._index()
        document = self.browser.document()
        layout = document.documentLayout()
        # The sentence/translation above the first headword belongs to its page.
        return [(0 if index == 0 else max(0, round(layout.blockBoundingRect(document.findBlock(position)).top())), heading)
                for index, (position, heading) in enumerate(self._boundaries)]

    def section_starts(self):
        tops = self.section_tops()
        heading = self.header.height() if self._headings and not self.preview else 0
        major = {heading if heading is not None else position: top
                 for (position, heading), (top, _) in zip(self._boundaries, self.boundaries())}
        return [0, *(major.get(position, max(0, top - heading))
                     for position, top in zip(self._positions[1:], tops[1:]))]

    def _align_section_end(self):
        document = self.browser.document()
        frame = document.rootFrame()
        fmt = frame.frameFormat()
        margin = document.documentMargin()
        boundaries = self.boundaries()
        if self.enabled and not self.preview and boundaries:
            # A short last section still needs enough scroll range to reach the top.
            content_height = document.size().height() - fmt.bottomMargin()
            margin = max(margin, boundaries[-1][0] + self.browser.viewport().height() - content_height)
        if abs(fmt.bottomMargin() - margin) > .5:
            fmt.setBottomMargin(margin)
            with QSignalBlocker(document):
                frame.setFrameFormat(fmt)

    def _update_clip(self):
        viewport = self.browser.viewport()
        if not self.enabled or self.preview:
            viewport.clearMask()
            return
        scroll = self.browser.verticalScrollBar().value()
        following = [top for top, _ in self.boundaries() if top > scroll and top > self.browser.document().documentMargin()]
        height = min(viewport.height(), following[0] - scroll) if following else viewport.height()
        viewport.setMask(QRegion(0, 0, viewport.width(), max(1, height)))

    def _refresh_header(self):
        self._index()
        self._align_section_end()
        self._update_clip()
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
        boundaries = sorted({0, maximum, *(min(maximum, top) for top in self.section_starts())})
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
        self._update_clip()
        if not self.enabled or self.preview or not self._headings:
            self.header.hide()
            return
        scroll = self.browser.verticalScrollBar().value()
        boundaries = self.boundaries()
        index = max(0, bisect_right([top for top, _ in boundaries], scroll) - 1)
        _, position = boundaries[index]
        if position is None:
            self.header.hide()
            return
        offset = min(0, boundaries[index + 1][0] - scroll - self.header.height()) if index + 1 < len(boundaries) else 0
        self.header.move(0, offset)
        self.header.setVisible(self._top(position) < scroll)
        if self._heading == position:
            return
        self._heading = position
        block = self.browser.document().findBlock(position)
        cursor = QTextCursor(block)
        # BlockUnderCursor includes the preceding paragraph's separator/format.
        cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        document = self.header.document()
        document.clear()
        document.setDefaultFont(self.browser.document().defaultFont())
        document.setDefaultStyleSheet(self.browser.document().defaultStyleSheet())
        target = QTextCursor(document)
        target.insertFragment(cursor.selection())
        # Ruby char formats and the registered object renderer are preserved.
        fmt = target.blockFormat()
        fmt.clearProperty(QTextFormat.Property.BlockTrailingHorizontalRulerWidth)
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
        tops = self.section_starts()
        stops = {0, bar.maximum()}
        for start, end in zip(tops, [*tops[1:], bar.maximum() + height]):
            stops.add(min(start, bar.maximum()))
            if end - start > height:
                last_page = min(end - height, bar.maximum())
                stops.update(range(start + step, last_page, step))
                stops.add(last_page)
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
        self.animation.setDuration(180)
        self.animation.setStartValue(bar.value())
        self.animation.setEndValue(target)
        self.animation.start()

    def advance(self, direction):
        if self._target is not None:
            return
        value = self.browser.verticalScrollBar().value()
        stops = self.stops()
        if direction > 0:
            self._move(stops[min(bisect_right(stops, value), len(stops) - 1)])
        else:
            self._move(stops[max(0, bisect_left(stops, value) - 1)])

    def scroll_by(self, movement, animate=False):
        self._index()
        bar = self.browser.verticalScrollBar()
        value = self._target if animate and self._target is not None else bar.value()
        boundaries = sorted({0, *(min(bar.maximum(), top) for top, _ in self.boundaries()[1:])})
        target = value + movement
        crossed = False
        if movement > 0:
            index = bisect_right(boundaries, value)
            if index < len(boundaries):
                boundary = boundaries[index]
                tail = max(value, boundary - self.browser.viewport().height())
                target = boundary if tail == value else min(target, tail)
                crossed = target in (tail, boundary) and target != value
            else:
                target = min(target, bar.maximum())
        elif movement < 0:
            boundary = boundaries[max(0, bisect_left(boundaries, value) - 1)]
            if value in boundaries:
                target = max(boundary, value - self.browser.viewport().height())
                crossed = target != value
            else:
                target = max(target, boundary)
        if animate:
            self._move(round(target))
        else:
            self.cancel()
            bar.setValue(round(target))
        return crossed

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
                direction = -1 if key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp) else 1
                if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    self.scroll_by(direction * self.browser.verticalScrollBar().singleStep(), animate=True)
                else:
                    self.advance(direction)
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
        if phase in (Qt.ScrollPhase.ScrollBegin, Qt.ScrollPhase.ScrollEnd):
            self._boundary_latched = False
        if not self._boundary_latched:
            if not pixel.isNull() or phase != Qt.ScrollPhase.NoScrollPhase:
                self._boundary_latched = self.scroll_by(-pixel.y() if not pixel.isNull() else -angle.y() / 3)
            else:
                movement = -angle.y() / 120 * QApplication.wheelScrollLines() * self.browser.verticalScrollBar().singleStep()
                self._boundary_latched = self.scroll_by(movement, animate=True)
        if phase == Qt.ScrollPhase.NoScrollPhase:
            self._gesture_idle.start()
        event.accept()
        return True
