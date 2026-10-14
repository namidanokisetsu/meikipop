"""Inline ruby for Qt's rich-text browser, which has no native ruby layout."""
from urllib.parse import quote, unquote
from itertools import count
from functools import lru_cache

from PyQt6.QtCore import QMimeData, QObject, QPointF, QSizeF, Qt, QUrl
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QTextCharFormat, QTextCursor,
                         QTextDocument, QTextFormat, QTextObjectInterface)

from meikipop.config.config import config
from meikipop.dictionary.pitch import PITCH_DATA, PITCH_OBJECT, PITCH_PREFIX
from meikipop.gui.popup_style import surface_colors
from meikipop.gui.turkish.browser import DictionaryBrowser


RUBY = QTextFormat.ObjectTypes.UserObject.value + 1
BASE = QTextFormat.Property.UserProperty.value + 1
READING = BASE + 1
KANJI = READING + 1
PREFIX = "meikipop-ruby:"
TAG_PREFIX = "meikipop-tag:"
_ruby_ids = count()


@lru_cache(maxsize=1024)
def _reading_text(encoded):
    text = unquote(encoded)
    if not ("<" in text or "&" in text or any(char.isspace() for char in text)):
        return text
    document = QTextDocument()
    document.setHtml(text)
    return document.toPlainText()


def ruby_html(base, reading, color=None, *, kanji=()):
    # Distinct anchors prevent Qt from merging adjacent identical readings.
    suffix = f'/{quote("".join(kanji), safe="")}' if kanji else ""
    return (f'<a href="{PREFIX}{quote(reading, safe="")}#{next(_ruby_ids)}{suffix}" '
            f'style="color:{color or config.color_foreground};text-decoration:none">{base}</a>')


class RubyObject(QObject, QTextObjectInterface):
    @staticmethod
    def metrics(document, fmt):
        font = fmt.toCharFormat().font()
        # QTextDocument inherits the family without setting QFont's resolve bit.
        # QPainter otherwise keeps its previous family, even for the base kanji.
        font.setFamilies(font.families() or document.defaultFont().families())
        # QPainter resolves unset size bits against its previous (reading) font.
        # Make the document's resolved size explicit, including heading scaling.
        if font.pixelSize() > 0:
            font.setPixelSize(font.pixelSize())
        else:
            font.setPointSizeF(font.pointSizeF())
        small = QFont(font)
        scale = getattr(config, "furigana_scale", 50) / 100
        if font.pixelSize() > 0:
            small.setPixelSize(max(6, round(font.pixelSize() * scale)))
        else:
            small.setPointSizeF(max(4, font.pointSizeF() * scale))
        return font, small, QFontMetricsF(font), QFontMetricsF(small)

    def intrinsicSize(self, document, pos, fmt):
        _, _, base, reading = self.metrics(document, fmt)
        return QSizeF(max(base.horizontalAdvance(fmt.property(BASE)),
                          reading.horizontalAdvance(fmt.property(READING))),
                      -base.tightBoundingRect(fmt.property(BASE)).top()
                      + reading.tightBoundingRect(fmt.property(READING)).height() + 2)

    def drawObject(self, painter, rect, document, pos, fmt):
        font, small, base, reading = self.metrics(document, fmt)
        painter.save()
        painter.setFont(small)
        muted = QColor(surface_colors(config.color_background, config.color_foreground)["muted"])
        gray = round(.299 * muted.red() + .587 * muted.green() + .114 * muted.blue())
        painter.setPen(QColor(gray, gray, gray))
        text = fmt.property(READING)
        painter.drawText(QPointF(rect.x() + (rect.width() - reading.horizontalAdvance(text)) / 2,
                                 rect.bottom() + base.tightBoundingRect(fmt.property(BASE)).top()
                                 - 2 - reading.tightBoundingRect(text).bottom()), text)
        painter.setFont(font)
        painter.setPen(fmt.foreground().color())
        text = fmt.property(BASE)
        painter.drawText(QPointF(rect.x() + (rect.width() - base.horizontalAdvance(text)) / 2,
                                 rect.bottom()), text)
        painter.restore()


class RubyBrowser(DictionaryBrowser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ruby_object = RubyObject(self)
        self._pitch_object = None
        self._pressed_kanji = ""
        self.document().documentLayout().registerHandler(RUBY, self._ruby_object)

    def setHtml(self, html):
        super().setHtml(html)
        document = self.document()
        runs, tags = [], []
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                href = fragment.charFormat().anchorHref()
                if href.startswith((TAG_PREFIX, "frequency:")):
                    tags.append((fragment.position(), fragment.length(), href))
                if href.startswith((PREFIX, PITCH_PREFIX)):
                    start, end = fragment.position(), fragment.position() + fragment.length()
                    if runs and runs[-1][1] == start and runs[-1][2] == href:
                        runs[-1] = (runs[-1][0], end, href)
                    else:
                        runs.append((start, end, href))
                iterator += 1
            block = block.next()
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        try:
            for start, length, href in tags:
                cursor.setPosition(start)
                cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat(cursor.charFormat())
                fmt.setAnchor(False)
                fmt.setAnchorHref("")
                fmt.setFontUnderline(False)
                fmt.setToolTip(unquote(href.partition(":")[2]))
                cursor.setCharFormat(fmt)
            for start, end, href in reversed(runs):
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                if href.startswith(PITCH_PREFIX):
                    from meikipop.dictionary.pitch import install_pitch_renderer, pitch_format, pitch_payload
                    payload = pitch_payload(href)
                    if payload is not None:
                        if self._pitch_object is None:
                            self._pitch_object = install_pitch_renderer(document, self)
                        cursor.insertText("\ufffc", pitch_format(cursor.charFormat(), payload))
                    continue
                fmt = QTextCharFormat(cursor.charFormat())
                fmt.setAnchor(False)
                fmt.setAnchorHref("")
                fmt.setFontUnderline(False)
                fmt.setObjectType(RUBY)
                fmt.setProperty(BASE, cursor.selectedText())
                fmt.setProperty(READING, _reading_text(href[len(PREFIX):].partition("#")[0]))
                fmt.setProperty(KANJI, unquote(href.partition("#")[2].partition("/")[2]))
                cursor.insertText("\ufffc", fmt)
        finally:
            cursor.endEditBlock()

    def _plain_selection(self, cursor):
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        text = cursor.selectedText()
        replacements = []
        block = self.document().findBlock(start)
        while block.isValid() and block.position() < end:
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                fmt = fragment.charFormat()
                if fmt.objectType() in (RUBY, PITCH_OBJECT):
                    for position in range(max(start, fragment.position()), min(end, fragment.position() + fragment.length())):
                        replacements.append((position - start, fmt.property(BASE)))
                iterator += 1
            block = block.next()
        # QTextCursor offsets count UTF-16 units, including astral kanji.
        encoded = text.encode("utf-16-le")
        for offset, base in reversed(replacements):
            encoded = encoded[:offset * 2] + base.encode("utf-16-le") + encoded[(offset + 1) * 2:]
        return encoded.decode("utf-16-le").translate({ord(char): "\n" for char in "\u2028\u2029\ufdd0\ufdd1"} | {0xa0: " "})

    def selected_text(self):
        return self._plain_selection(self.textCursor()).strip()

    def toPlainText(self):
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        return self._plain_selection(cursor)

    def createMimeDataFromSelection(self):
        if "\ufffc" not in self.textCursor().selectedText():
            return super().createMimeDataFromSelection()
        data = QMimeData()
        data.setText(self._plain_selection(self.textCursor()))
        return data

    def text_at(self, point):
        selected = self.textCursor()
        cursor = self.cursorForPosition(point)
        if selected.hasSelection() and selected.selectionStart() <= cursor.position() < selected.selectionEnd():
            return self.selected_text()
        # Exact hit-testing avoids mistaking whitespace beside ruby for a word.
        offset = QPointF(point.x() + self.horizontalScrollBar().value(),
                         point.y() + self.verticalScrollBar().value())
        position = self.document().documentLayout().hitTest(offset, Qt.HitTestAccuracy.ExactHit)
        if position >= 0:
            cursor.setPosition(position)
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            if cursor.charFormat().objectType() == PITCH_OBJECT:
                from meikipop.dictionary.pitch import pitch_payload
                payload = pitch_payload(PITCH_PREFIX + quote(cursor.charFormat().property(PITCH_DATA), safe=""))
                return payload["reading"] if payload else ""
            if cursor.charFormat().objectType() == RUBY:
                return cursor.charFormat().property(BASE)
        return super().text_at(point)

    def lookup_selection(self):
        cursor = self.textCursor()
        if (self.selection_lookup and cursor.selectionEnd() - cursor.selectionStart() == 1
                and cursor.charFormat().objectType() == PITCH_OBJECT):
            from meikipop.dictionary.pitch import pitch_payload
            payload = pitch_payload(PITCH_PREFIX + quote(cursor.charFormat().property(PITCH_DATA), safe=""))
            if payload:
                self.word_selected.emit(payload["reading"])
                return
        super().lookup_selection()

    def _ruby_kanji_at(self, point):
        offset = QPointF(point.x() + self.horizontalScrollBar().value(),
                         point.y() + self.verticalScrollBar().value())
        position = self.document().documentLayout().hitTest(offset, Qt.HitTestAccuracy.ExactHit)
        if position < 0:
            return ""
        cursor = QTextCursor(self.document())
        for start in (position, position - 1):
            if start < 0:
                continue
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            fmt = cursor.charFormat()
            if fmt.objectType() != RUBY or not fmt.property(KANJI):
                continue
            text = fmt.property(BASE)
            _, _, base, _ = self._ruby_object.metrics(self.document(), fmt)
            cursor.setPosition(start)
            block = cursor.block()
            line = block.layout().lineForTextPosition(start - block.position())
            baseline = (self.document().documentLayout().blockBoundingRect(block).top()
                        + line.y() + line.ascent() - self.verticalScrollBar().value())
            if not baseline + base.tightBoundingRect(text).top() <= point.y() <= baseline:
                continue
            width = self._ruby_object.intrinsicSize(self.document(), start, fmt).width()
            left = self.cursorRect(cursor).left() + (width - base.horizontalAdvance(text)) / 2
            for index, character in enumerate(text):
                right = left + base.horizontalAdvance(text[:index + 1])
                if left + base.horizontalAdvance(text[:index]) <= point.x() < right:
                    return character if character in fmt.property(KANJI) else ""
        return ""

    def anchorAt(self, point):
        character = self._ruby_kanji_at(point)
        return f'headkanji:{quote(character, safe="")}' if character else super().anchorAt(point)

    def mousePressEvent(self, event):
        self._pressed_kanji = self._ruby_kanji_at(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._ruby_kanji_at(event.position().toPoint()):
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        character = self._ruby_kanji_at(event.position().toPoint())
        clicked = (event.button() == Qt.MouseButton.LeftButton and character
                   and character == self._pressed_kanji and not self.textCursor().hasSelection())
        self._pressed_kanji = ""
        super().mouseReleaseEvent(event)
        if clicked:
            self.anchorClicked.emit(QUrl(f'headkanji:{quote(character, safe="")}'))
