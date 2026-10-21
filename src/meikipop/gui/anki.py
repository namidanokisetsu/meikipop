"""Opt-in Anki settings and export using snapshots of the selected result."""
import json
import re
import threading
from html import escape
from urllib.parse import unquote

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLineEdit,
    QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from meikipop.anki import (AnkiClient, DUPLICATE_ACTIONS, DUPLICATE_SCOPES, FIELD_SOURCES, load_settings, media_value, note_values,
                           sentence_readings, suggest_fields)
from meikipop.gui.shortcut_edit import ShortcutEdit
from meikipop.gui.quick_lookup import _GlossConverter
from meikipop.scripts.import_yomitan_dict_html import StructuredContentConverter
from meikipop.utils.timing import mark


class _AnkiGlossConverter(_GlossConverter):
    def _ruby_to_html(self, content):
        parts = []
        for child in content if isinstance(content, list) else [content]:
            tag = child.get("tag") if isinstance(child, dict) else None
            if tag == "rt":
                parts.append(f'<rt>{self._node_to_html(child.get("content"))}</rt>')
            elif tag != "rp":
                parts.append(self._node_to_html(child))
        return '<ruby>' + ''.join(parts) + '</ruby>'

    def __init__(self):
        super().__init__(expanded=True)
        self.tag_descriptions = {}

    def _node_to_html(self, node):
        if isinstance(node, list):
            return super()._node_to_html(node)
        if self._is_tag(node):
            return self._tags_to_html((node,))
        if isinstance(node, dict) and node.get("tag") in ("ul", "ol", "li", "div"):
            node = dict(node)
            style = dict(node.get("style", {}))
            if node["tag"] in ("ul", "ol"):
                style.update(marginTop="0", marginBottom="0", marginLeft="0", paddingLeft="1.2em")
            else:
                for key in ("marginLeft", "paddingLeft", "textIndent"):
                    style.pop(key, None)
            node["style"] = style
        # Cards retain full definitions; only the popup's semantic tags are shared.
        return StructuredContentConverter._node_to_html(self, node)

    def _tags_to_html(self, nodes):
        html = super()._tags_to_html(nodes)
        if not html:
            return ""
        document = QTextDocument()
        document.setHtml(html)
        label = document.toPlainText().strip()
        href = document.begin().begin().fragment().charFormat().anchorHref()
        descriptions = self.tag_descriptions.setdefault(label, [])
        for description in unquote(href.partition(":")[2]).split(" · "):
            if not re.fullmatch(r"JMdict Sense #\d+", description, re.IGNORECASE) and description not in descriptions:
                descriptions.append(description)
        title = escape(" · ".join(descriptions), quote=True)
        return f'<span title="{title}">{escape(label)}</span> '


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
        self._duplicate_deck_names, self._known_decks = set(), []
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Enable Anki")
        layout.addWidget(self.enabled)
        self.options = QWidget()
        layout.addWidget(self.options, 1)
        layout.addStretch()
        options_layout = QVBoxLayout(self.options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        options_layout.addLayout(form)
        self.endpoint = QLineEdit()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Optional")
        self.deck, self.model = QComboBox(), QComboBox()
        self.tags = QLineEdit()
        for label, control in (("Deck", self.deck), ("Note type", self.model), ("Tags", self.tags)):
            form.addRow(label, control)
        from meikipop.gui.settings_section import SettingsSection, StatusLabel
        connection = QWidget()
        connection_form = QFormLayout(connection)
        connection_form.addRow("Address", self.endpoint)
        connection_form.addRow("API key", self.api_key)
        options_layout.addWidget(SettingsSection("Connection", connection))
        duplicates = QWidget()
        self.duplicate_form = QFormLayout(duplicates)
        self.duplicate_action, self.duplicate_scope = QComboBox(), QComboBox()
        for control, choices in ((self.duplicate_action, DUPLICATE_ACTIONS), (self.duplicate_scope, DUPLICATE_SCOPES)):
            for value, label in choices.items():
                control.addItem(label, value)
        self.duplicate_scope.setToolTip("Deck tree includes the top-level deck and all its subdecks")
        self.duplicate_decks = QPushButton("Choose…")
        self.duplicate_decks.setToolTip("The destination deck is always included")
        self.duplicate_decks.setMenu(QMenu(self.duplicate_decks))
        self.check_all_models = QCheckBox("All note types")
        self.duplicate_form.addRow("Action", self.duplicate_action)
        self.duplicate_form.addRow("Check in", self.duplicate_scope)
        self.duplicate_form.addRow("Also check", self.duplicate_decks)
        self.duplicate_form.addRow(self.check_all_models)
        options_layout.addWidget(SettingsSection("Duplicates", duplicates))
        self.reload = QPushButton("Refresh")
        self.reload.setToolTip("Open Anki with AnkiConnect installed")
        self.auto_map = QPushButton("Match fields")
        self.auto_map.clicked.connect(self._match_fields)
        actions = QHBoxLayout()
        actions.addWidget(self.reload)
        actions.addWidget(self.auto_map)
        actions.addStretch()
        form.addRow(actions)
        self.mapping = QFormLayout()
        mapping_widget = QWidget()
        mapping_widget.setLayout(self.mapping)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(mapping_widget)
        options_layout.addWidget(scroll, 1)
        self.shortcut = ShortcutEdit("Shift+A", "Shift+A")
        self.shortcut.setToolTip("Add to Anki while reading the popup")
        self.shortcut_form = form
        form.addRow("Add shortcut", self.shortcut)
        self.status = StatusLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        options_layout.addWidget(self.status)
        self.options.hide()
        self.enabled.toggled.connect(self.options.setVisible)
        self.enabled.toggled.connect(self._enabled_changed)
        self.deck.currentIndexChanged.connect(self._deck_changed)
        self.model.currentIndexChanged.connect(self._model_changed)
        self.duplicate_action.currentIndexChanged.connect(self._duplicates_changed)
        self.duplicate_scope.currentIndexChanged.connect(self._duplicates_changed)
        self.check_all_models.toggled.connect(self._save)
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
        self.options.setVisible(options.enabled)
        self.endpoint.setText(options.endpoint)
        self.api_key.setText(options.api_key)
        self.tags.setText(" ".join(options.tags))
        self.duplicate_action.setCurrentIndex(max(0, self.duplicate_action.findData(options.duplicate_action)))
        self.duplicate_scope.setCurrentIndex(max(0, self.duplicate_scope.findData(options.duplicate_scope)))
        self.check_all_models.setChecked(options.check_all_models)
        self._duplicate_deck_names = set(options.duplicate_decks)
        self._known_decks = [options.deck] if options.deck else []
        for control, value in ((self.deck, options.deck), (self.model, options.model)):
            control.clear()
            if value:
                control.addItem(value)
        self._update_duplicate_menu()
        self._duplicates_changed()
        try:
            self._maps = json.loads(self.settings.value(self._prefix + "field_maps", "{}"))
            if not isinstance(self._maps, dict):
                self._maps = {}
        except (TypeError, ValueError):
            self._maps = {}
        self._maps = {model: mapping for model, mapping in self._maps.items() if isinstance(mapping, dict)}
        self._set_fields(list(options.fields), options.fields)
        shortcut = self.settings.value(self._prefix + "shortcut", "Shift+A")
        self.shortcut.set_value(shortcut, self.settings.value(self._prefix + "shortcut_preset", "Shift+A"))
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
                      duplicate_action=self.duplicate_action.currentData(),
                      duplicate_scope=self.duplicate_scope.currentData(),
                      duplicate_decks=json.dumps(sorted(self._duplicate_deck_names), ensure_ascii=False),
                      check_all_models=self.check_all_models.isChecked(),
                      shortcut=shortcut if self.shortcut.enabled.isChecked() else "",
                      shortcut_preset=shortcut)
        if self.shortcut_form.indexOf(self.shortcut) < 0:
            # The Shortcuts tab owns validation after taking this control.
            values.pop("shortcut")
            values.pop("shortcut_preset")
        for key, value in values.items():
            if key in ("endpoint", "api_key") and self._task is not None and self.settings.value(self._prefix + key, "") != value:
                self._generation += 1
            self.settings.setValue(self._prefix + key, value)
        self.changed.emit()

    def _duplicates_changed(self, *_):
        checking = self.duplicate_action.currentData() == "prevent"
        self.duplicate_scope.setEnabled(checking)
        self.check_all_models.setEnabled(checking)
        self.duplicate_decks.setEnabled(checking)
        self.duplicate_form.setRowVisible(self.duplicate_decks, self.duplicate_scope.currentData() == "decks")
        self._save()

    def _deck_changed(self, *_):
        if not self._loading:
            self._update_duplicate_menu()
            self._save()

    def _update_duplicate_menu(self):
        menu = self.duplicate_decks.menu()
        menu.clear()
        destination = self.deck.currentText()
        for deck in dict.fromkeys((*self._known_decks, destination, *sorted(self._duplicate_deck_names))):
            if not deck:
                continue
            action = menu.addAction(deck)
            action.setCheckable(True)
            action.setChecked(deck == destination or deck in self._duplicate_deck_names)
            action.setEnabled(deck != destination)
            action.toggled.connect(lambda checked, name=deck: self._duplicate_deck_changed(name, checked))
        count = len(self._duplicate_deck_names - {destination})
        self.duplicate_decks.setText(f"{count} selected" if count else "Choose…")

    def _duplicate_deck_changed(self, deck, checked):
        if checked:
            self._duplicate_deck_names.add(deck)
        else:
            self._duplicate_deck_names.discard(deck)
        count = len(self._duplicate_deck_names - {self.deck.currentText()})
        self.duplicate_decks.setText(f"{count} selected" if count else "Choose…")
        self._save()

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
            self._known_decks = value[0]
            for control, names in zip((self.deck, self.model), value):
                saved = control.currentText()
                control.clear()
                control.addItems(names)
                if saved in names:
                    control.setCurrentText(saved)
            self._update_duplicate_menu()
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


def export_note(entries, sentence, selection, options, *, translation="", screenshot=None,
                directory=None, audio_clip=None, kanji=()):
    """Prepare and save a captured lookup on an AnkiTask worker."""
    mark("anki_check_begin")
    client = AnkiClient(options)
    client.check(escape(entries[0].term))
    mark("anki_prepare_begin")
    mapped = set(options.fields.values())
    furigana = None
    if entries[0].language == "ja" and sentence and "sentence_furigana" in mapped:
        from meikipop.dictionary.library import Library
        library = Library(directory)
        try:
            furigana = sentence_readings(sentence, entries, library)
        finally:
            library.close()
    converter = _AnkiGlossConverter() if mapped.intersection(("glossary", "glossary-first")) else None
    values = note_values(entries, sentence, selection, translation, furigana, converter=converter, sources=mapped)
    values["kanji-details"] = ""
    if "kanji-details" in mapped and entries[0].language == "ja":
        from meikipop.gui.kanji_panel import render_kanji_export
        values["kanji-details"] = render_kanji_export(kanji, entries[0].term)
    media = {}
    if screenshot is not None and "picture" in mapped:
        from io import BytesIO
        buffer = BytesIO()
        screenshot.image().save(buffer, format="PNG", compress_level=1)
        media["picture"] = media_value(buffer.getvalue(), "png")
    if ("word_audio" in mapped and audio_clip is not None
            and audio_clip.key == (entries[0].term, entries[0].reading or "")):
        from pathlib import Path
        suffix = Path(audio_clip.filename).suffix.lstrip(".").lower()
        if suffix in ("mp3", "ogg", "wav", "m4a", "flac", "opus"):
            media["word_audio"] = media_value(audio_clip.data, suffix)
    values["_media"] = media
    mark("anki_commit_begin")
    note_id = client.add(values)
    mark("anki_saved")
    return note_id
