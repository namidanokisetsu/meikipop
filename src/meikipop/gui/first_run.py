"""One-page first-launch setup with individually optional downloads."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                            QLabel, QPushButton, QProgressBar, QVBoxLayout, QWidget)

from meikipop.gui.shortcut_edit import ShortcutEdit


def needs_setup(settings):
    return settings.value("setup/pending", False, bool) or (
        not settings.value("setup/completed", False, bool) and not settings.allKeys())


class SetupWizard(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.operation = None
        self.downloads_done = False
        self.download_language = ""
        self.setWindowTitle("Welcome to Meikipop")
        self.resize(540, 460)
        from meikipop.gui.quick_lookup import LANGUAGE_NAMES, shortcut_preset
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.language = QComboBox()
        for code, name in LANGUAGE_NAMES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(window.preferred_foreign)))
        form.addRow("Language", self.language)
        layout.addWidget(QLabel("Choose what to install. Everything is optional."))
        self.resources = QWidget()
        self.resource_layout = QVBoxLayout(self.resources)
        self.resource_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.resources)
        self.choices = []
        self.translation = QComboBox()
        self.translation.addItem("Lightweight (1.9 GB)", "lightweight")
        self.translation.addItem("Quality (8 GB)", "quality")
        form.addRow("Translation model", self.translation)
        self.shortcut = ShortcutEdit(window.settings.value("hotkey", ""), shortcut_preset())
        form.addRow("Search shortcut", self.shortcut)
        self.bar = QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        buttons.addWidget(self.settings_button)
        buttons.addStretch()
        self.skip = QPushButton("Stop downloads")
        self.skip.clicked.connect(self.skip_downloads)
        self.skip.hide()
        buttons.addWidget(self.skip)
        self.start = QPushButton("Start Meikipop")
        self.start.clicked.connect(self.accept)
        self.start.setDefault(True)
        buttons.addWidget(self.start)
        layout.addLayout(buttons)
        self.language.currentIndexChanged.connect(self.update_plan)
        self.translation.currentIndexChanged.connect(self._selection_changed)
        self.update_plan()

    def _selection_changed(self):
        self.downloads_done = False
        self.translation.setEnabled(any(task.kind == "translation" and check.isChecked()
                                        for task, check in self.choices))

    def update_plan(self):
        from meikipop.gui.language_setup import language_plan
        while self.resource_layout.count():
            self.resource_layout.takeAt(0).widget().deleteLater()
        self.choices = []
        for task in language_plan(self.language.currentData(), self.translation.currentData()):
            check = QCheckBox(task.label)
            check.setChecked(task.kind != "translation")
            check.toggled.connect(self._selection_changed)
            self.resource_layout.addWidget(check)
            self.choices.append((task, check))
        self._selection_changed()

    def selected_tasks(self):
        from dataclasses import replace
        return [replace(task, value=self.translation.currentData()) if task.kind == "translation" else task
                for task, check in self.choices if check.isChecked()]

    def begin_downloads(self):
        if self.operation is not None or self.downloads_done:
            return
        from meikipop.dictionary.library import default_library_path
        from meikipop.gui.language_setup import LanguageSetup
        tasks = self.selected_tasks()
        if not tasks:
            self.downloads_done = True
            return
        self.select_language()
        self.download_language = self.language.currentData()
        self.operation = LanguageSetup(tasks, self.window.directory or default_library_path())
        self.window._language_setup = self.operation
        self.bar.setRange(0, len(tasks))
        self.bar.setValue(0)
        self.bar.show()
        self.skip.show()
        self.skip.setEnabled(True)
        for control in (self.start, self.language, self.resources, self.translation, self.shortcut, self.settings_button):
            control.setEnabled(False)
        self.operation.stage.connect(self.download_stage)
        self.operation.progress.connect(self.error.setText)
        self.operation.finished.connect(self.download_finished)
        self.operation.thread.start()

    def download_stage(self, index, label):
        self.bar.setValue(index)
        self.error.setText(label)

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
        self.skip.hide()
        self.bar.setValue(self.bar.maximum())
        for control in (self.start, self.language, self.resources, self.shortcut, self.settings_button):
            control.setEnabled(True)
        self.translation.setEnabled(any(task.kind == "translation" and check.isChecked()
                                        for task, check in self.choices))
        self.error.setText("\n".join(errors) if errors else "Installed items were kept." if cancelled else "Ready.")
        if not errors and not cancelled and self.isVisible():
            self.accept()

    def skip_downloads(self):
        if self.operation is not None:
            self.operation.cancelled.set()
            self.error.setText("Stopping downloads...")
            self.skip.setEnabled(False)

    def reject(self):
        self.skip_downloads()
        super().reject()

    def select_language(self):
        code = self.language.currentData()
        from meikipop.language.profiles import default_partner
        if not self.window.settings.contains(f"profiles/{code}/target"):
            self.window.settings.setValue(f"profiles/{code}/target", default_partner(code))
        self.window.update_languages(())
        self.window.set_mode(code)

    def open_settings(self):
        self.select_language()
        self.window.open_settings()

    def accept(self):
        if self.operation is not None:
            return
        try:
            self.window.apply_shortcut(self.shortcut.text())
        except (ValueError, OSError, RuntimeError) as error:
            self.error.setText(str(error))
            return
        if not self.downloads_done:
            self.begin_downloads()
            if self.operation is not None:
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
