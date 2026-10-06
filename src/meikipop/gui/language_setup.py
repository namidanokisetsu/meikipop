"""Install a language's supported resources without blocking Qt."""
from dataclasses import dataclass
from contextlib import closing
import threading
from time import monotonic

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class SetupTask:
    kind: str
    label: str
    value: object


def language_plan(language, translation="lightweight", platform=None):
    from meikipop.dictionary.catalog import recommendations
    from meikipop.language.support import STANZA_LANGUAGES, TRANSLATION_LANGUAGES, default_ocr_provider
    tasks = [SetupTask("dictionary", item.title, item) for item in recommendations(language)]
    provider = default_ocr_provider(language, platform)
    if provider != "vision":
        tasks.append(SetupTask("ocr", "Screen recognition", provider))
    if language != "ja" and language in STANZA_LANGUAGES:
        tasks.append(SetupTask("morphology", "Base-form model", language))
    if language in TRANSLATION_LANGUAGES:
        tasks.append(SetupTask("translation", "Local translation", translation))
    return tasks


def install_task(task, directory, progress, cancelled):
    if task.kind == "dictionary":
        from meikipop.dictionary.library import Library
        with closing(Library(directory)) as library:
            if any(meta["language"] == task.value.language and meta["title"].startswith(task.value.title)
                   for _, meta, _ in library.packs):
                return ""
        from meikipop.dictionary.import_job import background_import
        message, changed = background_import([], directory, task.value.language, task.value, progress, cancelled)
        if not changed:
            raise RuntimeError(message)
        return ""
    if task.kind == "ocr":
        from meikipop.scripts.setup_ocr import install
        return install(task.value, progress, cancelled)
    if task.kind == "morphology":
        from meikipop.language.stanza_analyzer import model_status
        if model_status(task.value) != "Installed":
            from meikipop.scripts.setup_morphology import install
            install(task.value, progress, cancelled)
        return ""
    from meikipop.scripts.translation_server import install_model
    install_model(profile=task.value, progress=progress, cancelled=cancelled)
    return ""


class LanguageSetup(QObject):
    progress = pyqtSignal(str)
    stage = pyqtSignal(int, str)
    finished = pyqtSignal(object, object)

    def __init__(self, tasks, directory):
        super().__init__()
        self.tasks, self.directory = tasks, directory
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name="language-setup")

    def run(self):
        completed, errors = [], []
        last_update = 0

        def progress(text):
            nonlocal last_update
            now = monotonic()
            if now - last_update >= 0.1:
                last_update = now
                self.progress.emit(text)

        for index, task in enumerate(self.tasks):
            if self.cancelled.is_set():
                break
            self.stage.emit(index, task.label)
            try:
                value = install_task(task, self.directory, progress, self.cancelled)
                completed.append((task, value))
            except InterruptedError:
                break
            except Exception as error:
                errors.append(f"{task.label}: {error}")
        self.finished.emit(completed, errors)
