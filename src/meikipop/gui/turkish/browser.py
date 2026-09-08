"""Dictionary-internal selection never needs to touch the system clipboard."""
from PyQt6.QtCore import pyqtSignal, Qt, QPointF
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextBrowser


class DictionaryBrowser(QTextBrowser):
    word_selected = pyqtSignal(str)

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
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and not self.anchorAt(event.position().toPoint()):
            self.lookup_selection()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and not self.anchorAt(event.position().toPoint()):
            self.lookup_selection()
