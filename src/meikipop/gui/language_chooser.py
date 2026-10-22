"""Language search accepts native names, English names and language codes."""
from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


def language_search_text(code, label):
    english = QLocale.languageToString(QLocale(code).language())
    return f"{code} {label} {english}".casefold()


class LanguageChooser(QDialog):
    def __init__(self, parent, languages, selected=None, title="Language"):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Language or code")
        layout.addWidget(self.search)
        self.languages = QListWidget()
        for code, label in sorted(languages.items(), key=lambda item: item[1].casefold()):
            item = QListWidgetItem(f"{label} ({code})", self.languages)
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setData(Qt.ItemDataRole.UserRole + 1, language_search_text(code, label))
            if code == selected:
                self.languages.setCurrentItem(item)
        layout.addWidget(self.languages)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.languages.itemDoubleClicked.connect(self.accept)
        self.search.textChanged.connect(self.filter)

    def filter(self, text):
        first = None
        for index in range(self.languages.count()):
            item = self.languages.item(index)
            item.setHidden(text.strip().casefold() not in item.data(Qt.ItemDataRole.UserRole + 1))
            if not item.isHidden() and first is None:
                first = item
        self.languages.setCurrentItem(first)

    def selected_code(self):
        item = self.languages.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None and not item.isHidden() else None


def choose_language(parent, languages, selected=None, title="Language"):
    dialog = LanguageChooser(parent, languages, selected, title)
    return dialog.selected_code() if dialog.exec() == QDialog.DialogCode.Accepted else None
