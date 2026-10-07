"""Opt-in Anki settings and export using snapshots of the selected result."""
import json
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from meikipop.anki import (AnkiClient, FIELD_SOURCES, load_settings, media_value, note_values,
                           sentence_readings, suggest_fields)
from meikipop.gui.shortcut_edit import ShortcutEdit


class AnkiTask(QObject):
    finished = pyqtSignal(object)

    def __init__(self, operation, context, parent):
        super().__init__(parent)
        self.operation, self.context = operation, context
        self.thread = threading.Thread(target=self._run, name="anki-connect", daemon=True)

    def _run(self):
        try:
            value, error = self.operation(), ""
        except Exception as exception:
            value, error = None, str(exception)
        try:
            self.finished.emit((self.context, value, error))
        except RuntimeError:
            pass


class AnkiSettingsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings, self.profile = settings, "ja"
        self._loading, self._task, self._generation = True, None, 0
        self._refresh_pending = False
        self._field_controls, self._maps = {}, {}
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Enable Anki")
        layout.addWidget(self.enabled)
        form = QFormLayout()
        layout.addLayout(form)
        self.endpoint = QLineEdit()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Optional")
        self.deck, self.model = QComboBox(), QComboBox()
        self.tags = QLineEdit()
        for label, control in (("Address", self.endpoint), ("API key", self.api_key), ("Deck", self.deck),
                               ("Note type", self.model), ("Tags", self.tags)):
            form.addRow(label, control)
        self.reload = QPushButton("Reload decks and fields")
        self.reload.setToolTip("Open Anki with AnkiConnect installed")
        form.addRow(self.reload)
        self.auto_map = QPushButton("Match fields")
        self.auto_map.clicked.connect(self._match_fields)
        form.addRow(self.auto_map)
        self.mapping = QFormLayout()
        mapping_widget = QWidget()
        mapping_widget.setLayout(self.mapping)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(mapping_widget)
        layout.addWidget(scroll, 1)
        self.shortcut = ShortcutEdit("", "Ctrl+Shift+A")
        self.shortcut.setToolTip("Add to Anki while the popup has focus")
        form.addRow("Add shortcut", self.shortcut)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.enabled.toggled.connect(self._enabled_changed)
        self.deck.currentIndexChanged.connect(self._save)
        self.model.currentIndexChanged.connect(self._model_changed)
        for control in (self.endpoint, self.api_key):
            control.editingFinished.connect(self._connection_changed)
        self.tags.editingFinished.connect(self._save)
        self.shortcut.enabled.toggled.connect(self._save)
        self.shortcut.recorder.editingFinished.connect(self._save)
        self.reload.clicked.connect(self.refresh)

    def load(self, profile):
        self._loading = True
        self.profile = profile
        self._generation += 1
        options = load_settings(self.settings, profile)
        self.enabled.setChecked(options.enabled)
        self.endpoint.setText(options.endpoint)
        self.api_key.setText(options.api_key)
        self.tags.setText(" ".join(options.tags))
        for control, value in ((self.deck, options.deck), (self.model, options.model)):
            control.clear()
            if value:
                control.addItem(value)
        try:
            self._maps = json.loads(self.settings.value(self._prefix + "field_maps", "{}"))
            if not isinstance(self._maps, dict):
                self._maps = {}
        except (TypeError, ValueError):
            self._maps = {}
        self._maps = {model: mapping for model, mapping in self._maps.items() if isinstance(mapping, dict)}
        self._set_fields(list(options.fields), options.fields)
        shortcut = self.settings.value(self._prefix + "shortcut", "")
        self.shortcut.set_value(shortcut, self.settings.value(self._prefix + "shortcut_preset", "Ctrl+Shift+A"))
        self.status.clear()
        self._loading = False
        self._refresh_pending = False
        if options.enabled and self.isVisible():
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self.enabled.isChecked() and self._task is None:
            self.refresh()

    def _enabled_changed(self):
        self._save()
        if not self._loading and self.enabled.isChecked():
            self.refresh()

    def _connection_changed(self):
        self._save()
        if self.enabled.isChecked():
            self.refresh()

    @property
    def _prefix(self):
        return f"profiles/{self.profile}/anki/"

    def _set_fields(self, fields, mapping):
        while self.mapping.rowCount():
            self.mapping.removeRow(0)
        self._field_controls = {}
        suggestions = suggest_fields(fields)
        for index, name in enumerate(fields):
            control = QComboBox()
            for value, label in FIELD_SOURCES.items():
                control.addItem(label, value)
            control.setCurrentIndex(max(0, control.findData(mapping.get(name, suggestions[name]))))
            self.mapping.addRow(name, control)
            self._field_controls[name] = control
            control.currentIndexChanged.connect(self._save)

    def _match_fields(self):
        if self._task is not None:
            return
        self._loading = True
        self._set_fields(list(self._field_controls), {})
        self._loading = False
        self._save()

    def _save(self, *_):
        if self._loading:
            return
        fields = {name: control.currentData() for name, control in self._field_controls.items()}
        model = self.model.currentText()
        if model and fields:
            self._maps[model] = fields
        shortcut = self.shortcut.recorder.keySequence().toString()
        values = dict(enabled=self.enabled.isChecked(), endpoint=self.endpoint.text().strip(),
                      api_key=self.api_key.text(), deck=self.deck.currentText(), model=model,
                      tags=self.tags.text(), fields=json.dumps(fields, ensure_ascii=False),
                      field_maps=json.dumps(self._maps, ensure_ascii=False),
                      shortcut=shortcut if self.shortcut.enabled.isChecked() else "",
                      shortcut_preset=shortcut)
        for key, value in values.items():
            if key in ("endpoint", "api_key") and self._task is not None and self.settings.value(self._prefix + key, "") != value:
                self._generation += 1
            self.settings.setValue(self._prefix + key, value)
        self.changed.emit()

    def _model_changed(self):
        if self._loading:
            return
        self._loading = True
        mapping = self._maps.get(self.model.currentText(), {})
        self._set_fields(list(mapping), mapping)
        self._loading = False
        self._save()
        self._request_fields()

    def _start(self, kind, operation):
        if self._task is not None:
            return
        self.reload.setEnabled(False)
        self.model.setEnabled(False)
        self.status.setText("Connecting…")
        self._task = AnkiTask(operation, (self._generation, kind, self.model.currentText()), self)
        self._task.finished.connect(self._finished)
        self._task.thread.start()

    def refresh(self):
        self._save()
        if self._task is not None:
            self._refresh_pending = True
            return
        options = load_settings(self.settings, self.profile)
        self._start("catalog", lambda: AnkiClient(options).catalog())

    def _request_fields(self):
        options = load_settings(self.settings, self.profile)
        if options.model:
            self._start("fields", lambda: AnkiClient(options).names("modelFieldNames", modelName=options.model))

    def _finished(self, response):
        task, self._task = self._task, None
        task.deleteLater()
        self.reload.setEnabled(True)
        self.model.setEnabled(True)
        (generation, kind, model), value, error = response
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()
            return
        if generation != self._generation:
            self.status.clear()
            return
        if error:
            self.status.setText(error)
            return
        self._loading = True
        if kind == "catalog":
            for control, names in zip((self.deck, self.model), value):
                saved = control.currentText()
                control.clear()
                control.addItems(names)
                if saved in names:
                    control.setCurrentText(saved)
            self._set_fields([], {})
        else:
            mapping = self._maps.get(model, {})
            self._set_fields(value, mapping)
        self._loading = False
        self._save()
        self.status.setText("Connected." if kind == "fields" else
                            "No note types found." if not self.model.count() else "")
        if kind == "catalog":
            self._request_fields()


class AnkiExportDialog(QDialog):
    def __init__(self, entries, sentence, selection, options, parent=None, *,
                 translation="", screenshot=None, directory=None, audio_clip=None):
        super().__init__(parent)
        self.setWindowTitle("Add to Anki")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(480, 400)
        self.options, self._task, self._saved = options, None, False
        self.screenshot, self.directory, self.audio_clip = screenshot, directory, audio_clip
        self.groups = {}
        for entry in entries:
            self.groups.setdefault((entry.term, entry.reading, entry.source), []).append(entry)
        self.groups = list(self.groups.values())
        layout = QVBoxLayout(self)
        self.entry = QComboBox()
        for group in self.groups:
            word = group[0]
            reading = f" [{word.reading}]" if word.reading and word.reading != word.term else ""
            self.entry.addItem(f"{word.term}{reading} · {word.source}")
        layout.addWidget(self.entry)
        self.definition = QTextEdit()
        self.definition.setAccessibleName("Card definition")
        layout.addWidget(self.definition, 1)
        self.sentence = QTextEdit()
        self.sentence.setAcceptRichText(False)
        self.sentence.setAccessibleName("Card sentence")
        self.sentence.setPlaceholderText("Sentence")
        self.sentence.setMaximumHeight(80)
        self.sentence.setPlainText(sentence)
        layout.addWidget(self.sentence)
        self.translation = QTextEdit()
        self.translation.setAcceptRichText(False)
        self.translation.setAccessibleName("Sentence translation")
        self.translation.setPlaceholderText("Sentence translation")
        self.translation.setMaximumHeight(65)
        self.translation.setPlainText(translation)
        self.translation.setVisible("sentence_translation" in options.fields.values())
        layout.addWidget(self.translation)
        self.include_picture = QCheckBox("Include screenshot")
        self.include_picture.setChecked(screenshot is not None)
        self.include_picture.setEnabled(screenshot is not None)
        self.include_picture.setVisible("picture" in options.fields.values())
        layout.addWidget(self.include_picture)
        self.status = QLabel(f"{options.deck} · {options.model}")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.add = QPushButton("Add")
        self.add.clicked.connect(self.submit)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.add)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.entry.currentIndexChanged.connect(self._entry_changed)
        self._entry_changed()
        if selection:
            self.definition.setPlainText(selection)

    def _entry_changed(self):
        values = note_values(self.groups[self.entry.currentIndex()])
        self.definition.setHtml(values["glossary"])

    def submit(self):
        if self._task is not None or self._saved:
            return
        entries = tuple(self.groups[self.entry.currentIndex()])
        sentence, translation, definition = self.sentence.toPlainText(), self.translation.toPlainText(), self.definition.toHtml()
        screenshot = self.screenshot if self.include_picture.isChecked() else None
        def export():
            furigana = None
            if entries[0].language == "ja" and sentence and "sentence_furigana" in self.options.fields.values():
                from meikipop.dictionary.search import SearchEngine
                engine = SearchEngine(self.directory)
                try:
                    furigana = sentence_readings(sentence, entries, engine)
                finally:
                    engine.close()
            values = note_values(entries, sentence, translation=translation, furigana=furigana)
            values["glossary"] = definition
            media = {}
            if screenshot is not None and "picture" in self.options.fields.values():
                from io import BytesIO
                buffer = BytesIO()
                screenshot.image().save(buffer, format="PNG")
                media["picture"] = media_value(buffer.getvalue(), "png")
            clip = self.audio_clip
            if clip is not None and clip.key == (entries[0].term, entries[0].reading or ""):
                from pathlib import Path
                suffix = Path(clip.filename).suffix.lstrip(".").lower()
                if suffix in ("mp3", "ogg", "wav", "m4a", "flac", "opus"):
                    media["word_audio"] = media_value(clip.data, suffix)
            values["_media"] = media
            return AnkiClient(self.options).add(values)
        self._task = AnkiTask(export, None, self)
        self._task.finished.connect(self._finished)
        for widget in (self.add, self.entry, self.definition, self.sentence, self.translation, self.include_picture, self.close_button):
            widget.setEnabled(False)
        self.status.setText("Adding…")
        self._task.thread.start()

    def _finished(self, response):
        task, self._task = self._task, None
        task.deleteLater()
        _, note_id, error = response
        for widget in (self.entry, self.definition, self.sentence, self.translation, self.close_button):
            widget.setEnabled(True)
        self.include_picture.setEnabled(self.screenshot is not None)
        self.add.setEnabled(bool(error))
        self._saved = not error
        self.status.setText(error or "Added to Anki.")

    def reject(self):
        if self._task is None:
            super().reject()
