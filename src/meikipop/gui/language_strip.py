"""Compact translation language tabs with an explicit chooser for other languages."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QWidget


class LanguageStrip(QWidget):
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, languages, parent=None):
        super().__init__(parent)
        self.languages = {"auto": "Automatic", **languages}
        self.available = set(self.languages)
        self.support_tooltip = ""
        self.codes = list(self.languages)
        self.selected = "auto"
        self.pair = ("ja", "en")
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.idClicked.connect(self.setCurrentIndex)
        self.refresh()

    def currentData(self):
        return self.selected

    def findData(self, code):
        return self.codes.index(code) if code in self.codes else -1

    def addItem(self, label, code):
        if code not in self.codes:
            self.codes.append(code)
        self.languages[code] = label

    def set_languages(self, languages, *, selected=None, preserved=(), tooltip=""):
        selected = self.selected if selected is None else selected
        previous = self.languages
        self.languages = {"auto": "Automatic", **languages}
        self.available = set(self.languages)
        self.support_tooltip = tooltip
        for code in dict.fromkeys((*preserved, *self.pair, selected)):
            self.languages.setdefault(code, previous.get(code, code))
        self.codes = list(self.languages)
        self.selected = selected
        self.refresh()

    def setCurrentIndex(self, index):
        if 0 <= index < len(self.codes) and self.selected != self.codes[index]:
            self.selected = self.codes[index]
            self.refresh()
            self.currentIndexChanged.emit(index)

    def set_pair(self, first, second):
        self.pair = (first, second)
        self.refresh()

    def refresh(self):
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                self.group.removeButton(item.widget())
                item.widget().deleteLater()
        for code in dict.fromkeys(("auto", *self.pair, self.selected)):
            self.addItem(self.languages.get(code, code), code)
            button = QToolButton()
            button.setText(self.languages[code])
            button.setCheckable(True)
            button.setChecked(code == self.selected)
            button.setEnabled(code in self.available)
            button.setToolTip(self.support_tooltip if code in self.available
                              else "The selected model does not support this language")
            self.group.addButton(button, self.findData(code))
            self.row.addWidget(button)
        more = QToolButton()
        more.setText("More…")
        more.clicked.connect(self.choose)
        self.row.addWidget(more)
        self.row.addStretch()

    def choose(self):
        from meikipop.gui.language_chooser import choose_language
        code = choose_language(self, {code: self.languages[code] for code in self.codes if code in self.available}, self.selected)
        if code is not None:
            self.setCurrentIndex(self.findData(code))
