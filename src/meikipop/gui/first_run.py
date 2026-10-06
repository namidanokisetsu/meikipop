"""First-launch setup using the same library and model controls as Settings."""
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLabel, QPushButton,
                            QProgressBar, QVBoxLayout, QWizard, QWizardPage)

from meikipop.gui.shortcut_edit import ShortcutEdit


def needs_setup(settings):
    # Existing installations keep their preferences and are not forced through setup.
    return settings.value("setup/pending", False, bool) or (
        not settings.value("setup/completed", False, bool) and not settings.allKeys())


class SetupWizard(QWizard):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.operation = None
        self.downloads_done = False
        self.download_language = ""
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
        self.translation = QComboBox()
        self.translation.addItem("Lightweight translation (1.9 GB)", "lightweight")
        self.translation.addItem("Quality translation (8 GB)", "quality")
        language.layout().addWidget(self.translation)
        self.manual = QCheckBox("Skip downloads and set up manually")
        language.layout().addWidget(self.manual)
        self.plan_summary = QLabel()
        self.plan_summary.setWordWrap(True)
        language.layout().addWidget(self.plan_summary)
        self.language.currentIndexChanged.connect(self.update_plan)
        self.update_plan()

        self.download_page = DownloadPage(self)
        self.addPage(self.download_page)
        models = self.add_page("Manual setup", "Add your own dictionaries or change models whenever you like.")
        self.add_button(models, "Choose dictionaries", 0)
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

    def update_plan(self):
        if self.operation is None:
            self.downloads_done = False
        from meikipop.gui.language_setup import language_plan
        from meikipop.language.support import TRANSLATION_LANGUAGES
        code = self.language.currentData()
        self.translation.setEnabled(code in TRANSLATION_LANGUAGES)
        self.plan_summary.setText("Next installs: " + ", ".join(task.label for task in language_plan(code)) + ".")

    def nextId(self):
        if self.currentId() == 0 and self.manual.isChecked():
            return 2
        return super().nextId()

    def begin_downloads(self):
        if self.operation is not None or self.downloads_done:
            return
        from meikipop.dictionary.library import default_library_path
        from meikipop.gui.language_setup import LanguageSetup, language_plan
        self.select_language()
        self.download_language = self.language.currentData()
        tasks = language_plan(self.download_language, self.translation.currentData())
        self.operation = LanguageSetup(tasks, self.window.directory or default_library_path())
        self.download_page.skip.setEnabled(True)
        self.window._language_setup = self.operation
        self.download_page.bar.setRange(0, len(tasks))
        self.operation.stage.connect(self.download_stage)
        self.operation.progress.connect(self.download_page.status.setText)
        self.operation.finished.connect(self.download_finished)
        self.button(QWizard.WizardButton.BackButton).setEnabled(False)
        self.operation.thread.start()

    def download_stage(self, index, label):
        self.download_page.bar.setValue(index)
        self.download_page.status.setText(label)

    def download_finished(self, completed, errors):
        from dataclasses import replace
        from meikipop.dictionary.translation import load_profile_settings, save_profile_settings
        code = self.download_language
        for task, value in completed:
            if task.kind == "morphology":
                self.window.settings.setValue(f"profiles/{code}/morphology", True)
            elif task.kind == "ocr":
                self.window.settings.setValue(f"profiles/{code}/ocr_provider", task.value)
                if value:
                    self.window.settings.setValue("screenai_directory", value)
            elif task.kind == "translation":
                settings = load_profile_settings(self.window.settings, code)
                save_profile_settings(self.window.settings, code, replace(settings, provider="server", profile=task.value))
        self.window.refresh_library()
        self.window.scan_settings_changed.emit()
        if self.window._setup is not None:
            self.window._setup.reload()
            self.window._setup.sync_profile(code)
        self.downloads_done = True
        cancelled = self.operation.cancelled.is_set()
        self.operation = None
        self.download_page.bar.setValue(self.download_page.bar.maximum())
        self.download_page.status.setText("\n".join(errors) if errors else (
            "Downloads skipped. Installed items were kept." if cancelled else "Your language is ready."))
        self.download_page.skip.setEnabled(False)
        self.button(QWizard.WizardButton.BackButton).setEnabled(True)
        self.download_page.completeChanged.emit()
        if cancelled and self.isVisible():
            self.next()

    def skip_downloads(self):
        if self.operation is not None:
            self.operation.cancelled.set()
            self.download_page.status.setText("Stopping downloads…")
            self.download_page.skip.setEnabled(False)

    def reject(self):
        self.skip_downloads()
        super().reject()

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
    wizard = getattr(window, "_setup_wizard", None)
    if wizard is None or not wizard.isVisible() and wizard.operation is None:
        wizard = SetupWizard(window)
        window._setup_wizard = wizard
    wizard.show()
    wizard.raise_()
    from meikipop.utils.window_focus import activate_application
    activate_application()
    wizard.activateWindow()


class DownloadPage(QWizardPage):
    def __init__(self, wizard):
        super().__init__()
        self.owner = wizard
        self.setTitle("Installing your language")
        self.setSubTitle("You can skip downloads and use manual setup.")
        layout = QVBoxLayout(self)
        self.bar = QProgressBar()
        self.status = QLabel("Preparing…")
        self.status.setWordWrap(True)
        self.skip = QPushButton("Skip remaining downloads")
        self.skip.clicked.connect(wizard.skip_downloads)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(self.skip)

    def initializePage(self):
        QTimer.singleShot(0, self.owner.begin_downloads)

    def isComplete(self):
        return self.owner.downloads_done
