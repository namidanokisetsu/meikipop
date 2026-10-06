"""First-launch setup using the same library and model controls as Settings."""
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QLabel, QPushButton,
                            QVBoxLayout, QWizard, QWizardPage)

from meikipop.gui.shortcut_edit import ShortcutEdit


def needs_setup(settings):
    # Existing installations keep their preferences and are not forced through setup.
    return settings.value("setup/pending", False, bool) or (
        not settings.value("setup/completed", False, bool) and not settings.allKeys())


class SetupWizard(QWizard):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Welcome to Meikipop")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(620, 440)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Start Meikipop")
        from meikipop.gui.quick_lookup import LANGUAGE_NAMES, shortcut_preset
        language = self.add_page("Your language", "Choose a language to get started. You can add more later.")
        self.language = QComboBox()
        for code, name in LANGUAGE_NAMES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(window.preferred_foreign)))
        language.layout().addWidget(self.language)

        dictionaries = self.add_page("Add dictionaries", "Install a recommended dictionary or import your own Yomitan ZIPs.")
        self.add_button(dictionaries, "Choose dictionaries", 0)
        models = self.add_page("Optional models", "Download local translation and base-form models when you need them.")
        self.add_button(models, "Translation models", 1)
        self.add_button(models, "Base-form models", 0)
        self.add_button(models, "Screen recognition", 3)
        note = QLabel("Downloads are optional. You can return to these controls in Settings.")
        note.setWordWrap(True)
        models.layout().addWidget(note)

        shortcuts = self.add_page("Make it yours", "Choose how to open dictionary search.")
        form = QFormLayout()
        self.shortcut = ShortcutEdit(window.settings.value("hotkey", ""), shortcut_preset())
        form.addRow("Search shortcut", self.shortcut)
        shortcuts.layout().addLayout(form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        shortcuts.layout().addWidget(self.error)
        self.add_page("Ready", "Open Meikipop from your apps or its tray icon. Settings keeps your dictionaries, models and shortcuts in one place.")

    def add_page(self, title, subtitle):
        page = QWizardPage()
        page.setTitle(title)
        page.setSubTitle(subtitle)
        QVBoxLayout(page)
        self.addPage(page)
        return page

    def add_button(self, page, title, tab):
        button = QPushButton(title)
        button.clicked.connect(lambda: self.open_settings(tab))
        page.layout().addWidget(button)

    def select_language(self):
        code = self.language.currentData()
        from meikipop.language.profiles import default_partner
        if not self.window.settings.contains(f"profiles/{code}/target"):
            self.window.settings.setValue(f"profiles/{code}/target", default_partner(code))
        self.window.update_languages(())
        self.window.set_mode(code)

    def open_settings(self, tab):
        self.select_language()
        self.window.open_settings()
        dialog = self.window._setup
        dialog.tabs.setCurrentIndex(tab)
        # The existing settings dialog owns cancellation and download progress.
        dialog.exec()

    def validateCurrentPage(self):
        if self.currentId() == 3:
            try:
                from meikipop.gui.text_shortcuts import validate_shortcuts
                validate_shortcuts([self.shortcut.text()])
            except ValueError as error:
                self.error.setText(str(error))
                return False
        return True

    def accept(self):
        try:
            self.window.apply_shortcut(self.shortcut.text())
        except (ValueError, OSError, RuntimeError) as error:
            self.back()
            self.error.setText(str(error))
            return
        self.select_language()
        self.window.settings.setValue("setup/completed", True)
        self.window.settings.remove("setup/pending")
        self.window.settings.sync()
        super().accept()
        self.window.open_search()


def show_setup(window):
    wizard = SetupWizard(window)
    wizard.exec()
