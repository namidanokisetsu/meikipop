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

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        if self.selected_text():
            menu.addSeparator()
            menu.addAction("Look up", self.lookup_selection)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def mousePressEvent(self, event):
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

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.selecting = False
        if self.selection_lookup and event.button() == Qt.MouseButton.LeftButton and not self.anchorAt(event.position().toPoint()):
            self.lookup_selection()
