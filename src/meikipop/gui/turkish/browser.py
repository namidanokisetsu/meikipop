"""Dictionary-internal selection never needs to touch the system clipboard."""
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QTextBrowser


class DictionaryBrowser(QTextBrowser):
    word_selected = pyqtSignal(str)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and not self.anchorAt(event.position().toPoint()):
            text = self.textCursor().selectedText().strip()
            if text and len(text) <= 2000:
                self.word_selected.emit(text)
