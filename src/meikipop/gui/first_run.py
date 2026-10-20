"""One-time resource suggestions for a newly added language profile."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                            QLabel, QPushButton, QProgressBar, QVBoxLayout)


def needs_setup(settings):
    from meikipop.language.profiles import configured_profiles
    return not configured_profiles(settings)


def complete_first_setup(settings):
    import sys
    if sys.platform != "win32" or settings.contains("start_with_windows"):
        return
    from meikipop.utils.startup import is_startup_enabled, set_startup_enabled
    try:
        if not is_startup_enabled():
            set_startup_enabled(True)
    except OSError:
        import logging
        logging.getLogger(__name__).exception("Could not enable Windows startup")
        return
    settings.setValue("start_with_windows", True)
    settings.sync()


class FirstLanguage(QDialog):
    def __init__(self, settings, imported=()):
        super().__init__()
        from meikipop.gui.quick_lookup import language_name
        from meikipop.language.profiles import configured_profiles
        from meikipop.language.support import profile_languages
        self.settings = settings
        self.setWindowTitle("Meikipop Setup")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        self.language = QComboBox()
        self.language.addItem("Choose a language…", None)
        for code in sorted(profile_languages(imported, configured_profiles(settings)),
                           key=lambda code: language_name(code).casefold()):
            self.language.addItem(language_name(code), code)
        form = QFormLayout()
        form.addRow("Lookup language", self.language)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.continue_button = QPushButton("Continue")
        self.continue_button.setEnabled(False)
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self.accept)
        buttons.addWidget(self.continue_button)
        layout.addLayout(buttons)
        self.language.currentIndexChanged.connect(lambda: self.continue_button.setEnabled(self.language.currentData() is not None))

    def accept(self):
        code = self.language.currentData()
        if code is None:
            return
        from meikipop.language.profiles import default_partner
        self.settings.setValue("profile", code)
        if not self.settings.contains(f"profiles/{code}/target"):
            self.settings.setValue(f"profiles/{code}/target", default_partner(code))
        self.settings.sync()
        super().accept()


class LanguageSuggestion(QDialog):
    def __init__(self, window, language=None):
        super().__init__(window)
        self.window = window
        self.language = language or window.preferred_foreign
        self.operation = None
        self.completed_tasks = []
        from meikipop.gui.quick_lookup import language_name
        from meikipop.gui.language_setup import language_plan
        self.setWindowTitle(language_name(self.language))
        self.resize(480, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose what to download."))
        self.choices = []
        for task in language_plan(self.language):
            check = QCheckBox(task.label)
            check.setChecked(True)
            layout.addWidget(check)
            self.choices.append((task, check))
        form = QFormLayout()
        layout.addLayout(form)
        self.translation = QComboBox()
        self.translation.addItem("Lightweight (1.9 GB)", "lightweight")
        self.translation.addItem("Quality (8 GB)", "quality")
        self.translation.setToolTip("Downloaded models are shared by all languages")
        from meikipop.gui.resources import translation_ready
        from meikipop.dictionary.translation import load_profile_settings
        try:
            preferred = load_profile_settings(window.settings, self.language).profile
        except ValueError:
            preferred = "lightweight"
        installed = [name for name in ("lightweight", "quality") if translation_ready(name)]
        selected = preferred if preferred in installed else next(iter(installed), "lightweight")
        if window.settings.contains(f"profiles/{self.language}/translation"):
            selected = preferred
        self.translation.setCurrentIndex(self.translation.findData(selected))
        self.translation.currentIndexChanged.connect(self.refresh_choices)
        form.addRow("Translation model", self.translation)
        form.setRowVisible(self.translation, any(task.kind == "translation" for task, check in self.choices))
        self.translation.setEnabled(any(task.kind == "translation" for task, check in self.choices))
        for task, check in self.choices:
            if task.kind == "translation":
                check.toggled.connect(self.translation.setEnabled)
        self.bar = QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.later = QPushButton("Later")
        self.later.clicked.connect(self.reject)
        buttons.addWidget(self.later)
        self.install = QPushButton("Install")
        self.install.setDefault(True)
        self.install.clicked.connect(self.accept)
        buttons.addWidget(self.install)
        layout.addLayout(buttons)
        self.refresh_choices()

    def selected_tasks(self):
        from dataclasses import replace
        from meikipop.gui.resources import translation_ready
        tasks = [replace(task, value=self.translation.currentData()) if task.kind == "translation" else task
                 for task, check in self.choices if check.isChecked()]
        return [task for task in tasks if task not in self.completed_tasks
                and not (task.kind == "translation" and translation_ready(task.value))]

    def refresh_choices(self):
        from dataclasses import replace
        from meikipop.gui.resources import translation_ready
        for task, check in self.choices:
            selected = replace(task, value=self.translation.currentData()) if task.kind == "translation" else task
            installed = selected in self.completed_tasks or (task.kind == "translation" and translation_ready(selected.value))
            check.setText(task.label + (" ✓" if installed else ""))
            check.setEnabled(self.operation is None and not installed)

    def use_translation(self, profile):
        from dataclasses import replace
        from meikipop.dictionary.translation import load_profile_settings, save_profile_settings
        settings = load_profile_settings(self.window.settings, self.language)
        save_profile_settings(self.window.settings, self.language, replace(settings, provider="server", profile=profile))

    def accept(self):
        if self.operation is not None:
            return
        from meikipop.dictionary.library import default_library_path
        from meikipop.gui.language_setup import LanguageSetup
        from meikipop.gui.resources import translation_ready
        if any(task.kind == "translation" and check.isChecked() for task, check in self.choices):
            if translation_ready(self.translation.currentData()):
                self.use_translation(self.translation.currentData())
                self.window.refresh_library()
        tasks = self.selected_tasks()
        if not tasks:
            super().accept()
            return
        self.operation = LanguageSetup(tasks, self.window.directory or default_library_path())
        self.bar.setRange(0, len(tasks))
        self.bar.setValue(0)
        self.bar.show()
        self.install.setEnabled(False)
        self.translation.setEnabled(False)
        for task, check in self.choices:
            check.setEnabled(False)
        self.later.setText("Stop downloads")
        self.operation.stage.connect(self.download_stage)
        self.operation.progress.connect(self.status.setText)
        self.operation.finished.connect(self.download_finished)
        self.operation.thread.start()

    def download_stage(self, index, label):
        self.bar.setValue(index)
        self.status.setText(label)

    def download_finished(self, completed, errors):
        code = self.language
        for task, value in completed:
            if task.kind == "ocr":
                self.window.settings.setValue(f"profiles/{code}/ocr_provider", task.value)
                if value:
                    self.window.settings.setValue("screenai_directory", value)
            elif task.kind == "translation":
                self.use_translation(task.value)
        self.window.refresh_library()
        self.window.scan_settings_changed.emit()
        if self.window._setup is not None:
            self.window._setup.reload(preserve=True)
            self.window._setup.sync_profile(self.window.preferred_foreign)
        cancelled = self.operation.cancelled.is_set()
        self.operation = None
        self.completed_tasks.extend(task for task, _ in completed if task not in self.completed_tasks)
        self.bar.setValue(len(completed))
        self.install.setEnabled(True)
        self.install.setText("Retry" if errors else "Install")
        self.refresh_choices()
        self.translation.setEnabled(any(task.kind == "translation" and check.isChecked()
                                        for task, check in self.choices))
        self.later.setText("Later")
        self.status.setText("\n".join(errors) if errors else "Installed items were kept." if cancelled else "Ready.")
        if not errors and not cancelled:
            super().accept()

    def reject(self):
        if self.operation is not None:
            self.operation.cancelled.set()
        super().reject()


def offer_resources(window, code, *, force=False):
    key = f"profiles/{code}/resources_suggested"
    if not force and window.settings.value(key, False, bool):
        return None
    suggestions = getattr(window, "_resource_suggestions", None)
    if suggestions is None:
        window._resource_suggestions = suggestions = {}
    suggestion = LanguageSuggestion(window, code)
    suggestions[code] = suggestion
    suggestion.show()
    suggestion.raise_()
    from meikipop.utils.window_focus import activate_application
    activate_application()
    suggestion.activateWindow()
    window.settings.setValue(key, True)
    window.settings.sync()
    return suggestion
