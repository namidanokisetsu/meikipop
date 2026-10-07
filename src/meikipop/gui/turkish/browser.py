"""Dictionary-internal selection never needs to touch the system clipboard."""
from PyQt6.QtCore import pyqtSignal, Qt, QPointF
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextBrowser


class DictionaryBrowser(QTextBrowser):
    word_selected = pyqtSignal(str)

    def __init__(self, *args, selection_lookup=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.selection_lookup = selection_lookup
        self.selecting = False
        self._selection_emitted = False

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        if self.selected_text():
            menu.addSeparator()
            menu.addAction("Look up", self.lookup_selection)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def mousePressEvent(self, event):
        self._selection_emitted = False
        self.selecting = event.button() == Qt.MouseButton.LeftButton
        super().mousePressEvent(event)

    def selected_text(self):
        return self.textCursor().selectedText().replace("\u2029", "\n").strip()

    def text_at(self, point):
        document_point = QPointF(point.x() + self.horizontalScrollBar().value(),
                                 point.y() + self.verticalScrollBar().value())
        if self.document().documentLayout().hitTest(document_point, Qt.HitTestAccuracy.ExactHit) < 0:
            return ""
        selected = self.selected_text()
        cursor = self.cursorForPosition(point)
        selection = self.textCursor()
        if selected and selection.selectionStart() <= cursor.position() < selection.selectionEnd():
            return selected
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        text = cursor.selectedText().strip()
        return text if any(c.isalpha() for c in text) else ""

    def lookup_selection(self):
        text = self.selected_text()
        if text and len(text) <= 2000:
            self.word_selected.emit(text)

    def mouseDoubleClickEvent(self, event):
        self.selecting = event.button() == Qt.MouseButton.LeftButton
        super().mouseDoubleClickEvent(event)
        if self.selection_lookup and self.selecting and not self.anchorAt(event.position().toPoint()):
            self._selection_emitted = True
            self.lookup_selection()

    def mouseReleaseEvent(self, event):
        # A link handler can scroll or replace the document during Qt's release.
        anchor = self.anchorAt(event.position().toPoint())
        self.selecting = False
        super().mouseReleaseEvent(event)
        if (self.selection_lookup and not self._selection_emitted and event.button() == Qt.MouseButton.LeftButton
                and not anchor):
            self.lookup_selection()
        self._selection_emitted = False
