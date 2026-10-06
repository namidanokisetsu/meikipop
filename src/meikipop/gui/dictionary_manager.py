"""Explicit, offline dictionary and translation setup."""
import json
from pathlib import Path
import sys
import threading
import zipfile

from PyQt6.QtCore import QObject, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QLineEdit, QListWidgetItem, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from meikipop.dictionary.library import Library, default_library_path, import_yomitan, save_preferences
from meikipop.dictionary.translation import TranslationSettings, load_settings, load_profile_settings, save_profile_settings
from meikipop.gui.quick_lookup import LANGUAGE_NAMES, language_name, shortcut_preset, audio_autoplay_mode
from meikipop.gui.shortcut_edit import ShortcutEdit


class SetupOperation(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str, bool)

    def __init__(self, paths, directory, language=None, profile=None):
        super().__init__()
        self.paths = paths
        self.directory = directory
        self.language = language
        self.profile = profile
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._run, name="dictionary-setup", daemon=True)

    def start(self):
        self.thread.start()

    def _emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _run(self):
        if self.profile:
            try:
                from meikipop.scripts.translation_server import install_model
                install_model(profile=self.profile, progress=lambda value: self._emit(self.progress, value),
                              cancelled=self.cancelled)
                self._emit(self.finished, "Model installed. Translate when ready.", True)
            except InterruptedError:
                self._emit(self.finished, "Download cancelled.", False)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        imported = 0
        errors = []
        for path in self.paths:
            if self.cancelled.is_set():
                break
            try:
                self._emit(self.progress, f"Importing {Path(path).name}…")
                with zipfile.ZipFile(path) as archive:
                    with archive.open("index.json") as stream:
                        metadata = json.loads(stream.read(1024 * 1024))
                language = metadata.get("sourceLanguage") or self.language
                if not language:
                    raise ValueError("No source language in this archive. Choose its language and import again.")
                import_yomitan(path, self.directory, language=language,
                               progress=lambda value: self._emit(self.progress, value),
                               cancelled=self.cancelled.is_set)
                imported += 1
            except InterruptedError:
                break
            except Exception as error:
                errors.append(f"{Path(path).name}: {error}")
        status = f"Imported {imported}."
        if self.cancelled.is_set():
            status += " Cancelled. Completed imports were kept."
        if errors:
            status += "\n" + "\n".join(errors)
        self._emit(self.finished, status, bool(imported))


class SetupDialog(QDialog):
    dictionaries_changed = pyqtSignal()

    def __init__(self, directory, settings, apply_shortcut, parent=None):
        super().__init__(parent)
        self.directory = Path(directory or default_library_path())
        self.settings = settings
        self._apply_shortcut = apply_shortcut
        self.operation = None
        self._close_pending = False
        self.setWindowTitle("Meikipop Settings")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        self.profile = QComboBox()
        for code in ("ja", "tr"):
            self.profile.addItem(language_name(code), code)
        self.profile.setCurrentIndex(max(0, self.profile.findData(settings.value("profile", settings.value("source", "ja")))))
        profile_row.addWidget(self.profile, 1)
        layout.addLayout(profile_row)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        dictionaries = QWidget()
        dictionary_layout = QVBoxLayout(dictionaries)
        self.packs = QListWidget()
        self.packs.setAccessibleName("Installed dictionaries, in priority order")
        self.packs.setToolTip("Checked dictionaries are enabled. Higher dictionaries appear first.")
        dictionary_layout.addWidget(self.packs, 1)
        actions = QHBoxLayout()
        self.import_button = QPushButton("Import ZIPs…")
        self.import_button.clicked.connect(self.choose_dictionaries)
        actions.addWidget(self.import_button)
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.setAccessibleName("Language for dictionaries without language metadata")
        self.language.addItem("Automatic", None)
        for code, name in LANGUAGE_NAMES.items():
            self.language.addItem(name, code)
        self.language.setToolTip("Archive language is used when available. Otherwise choose a language or type its code.")
        self.language.hide()
        self.up = QPushButton("↑")
        self.up.setToolTip("Higher priority")
        self.up.clicked.connect(lambda: self.move_pack(-1))
        actions.addWidget(self.up)
        self.down = QPushButton("↓")
        self.down.setToolTip("Lower priority")
        self.down.clicked.connect(lambda: self.move_pack(1))
        actions.addWidget(self.down)
        self.apply = QPushButton("Apply")
        self.apply.clicked.connect(self.save_dictionaries)
        self.apply.hide()
        dictionary_layout.addLayout(actions)
        self.morphology = QCheckBox("Lemma fallback")
        self.morphology.setToolTip("Try installed Stanza models when dictionary forms do not match")
        self.morphology.toggled.connect(self.save_morphology)
        dictionary_layout.addWidget(self.morphology)
        tabs.addTab(dictionaries, "Dictionaries")

        translation = QWidget()
        translation_layout = QVBoxLayout(translation)
        translation_form = QFormLayout()
        self.translation_partner = QComboBox()
        for code, name in LANGUAGE_NAMES.items():
            self.translation_partner.addItem(name, code)
        translation_form.addRow("Translate both ways with", self.translation_partner)
        self.translation_mode = QComboBox()
        self.translation_mode.addItem("Quality · Hy-MT2-7B Q8_0 (8 GB)", "quality")
        self.translation_mode.addItem("Lightweight · Hy-MT2-1.8B Q8_0 (2 GB)", "lightweight")
        self.translation_mode.addItem("Custom local server", "custom")
        translation_form.addRow("Model", self.translation_mode)
        self.translation_endpoint = QLineEdit()
        self.translation_endpoint.setAccessibleName("Local translation server address")
        translation_form.addRow("Address", self.translation_endpoint)
        self.translation_model = QLineEdit()
        self.translation_model.setAccessibleName("Local translation server model name")
        translation_form.addRow("Server model", self.translation_model)
        self.translation_autostart = QCheckBox("Start installed model when translating")
        translation_form.addRow(self.translation_autostart)
        translation_layout.addLayout(translation_form)
        note = QLabel("Downloads only when requested. Text stays on this computer.\n"
                      "The selected model is used without automatic fallback.")
        note.setWordWrap(True)
        note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        translation_layout.addWidget(note)
        self.model_button = QPushButton("Download selected model")
        self.model_button.clicked.connect(self.choose_model)
        translation_layout.addWidget(self.model_button)
        self.translation_apply = QPushButton("Apply")
        self.translation_apply.clicked.connect(self.save_translation)
        translation_layout.addWidget(self.translation_apply)
        translation_layout.addStretch()
        tabs.addTab(translation, "Translation model")
        translation_error = ""
        try:
            translation_settings = load_profile_settings(settings, self.profile.currentData())
        except ValueError as error:
            translation_settings = TranslationSettings()
            translation_error = str(error)
        self.translation_mode.setCurrentIndex(self.translation_mode.findData(
            translation_settings.profile if translation_settings.provider == "server" else "custom"))
        self.translation_endpoint.setText(translation_settings.endpoint)
        self.translation_model.setText(translation_settings.model)
        self.translation_autostart.setChecked(translation_settings.auto_start)
        self.translation_mode.currentIndexChanged.connect(self.update_translation_controls)
        self.update_translation_controls()

        shortcuts = QWidget()
        shortcut_layout = QFormLayout(shortcuts)
        self.scan_key = QComboBox()
        for label, value in (("None", ""), ("Shift", "shift"), ("Ctrl", "ctrl"), ("Alt", "alt"),
                             ("Ctrl + Shift", "ctrl+shift"), ("Ctrl + Alt", "ctrl+alt"), ("Alt + Shift", "alt+shift")):
            self.scan_key.addItem(label, value)
        self.scan_mouse = QComboBox()
        for label, value in (("None", ""), ("Middle mouse", "middle"), ("Mouse 4", "mouse4"), ("Mouse 5", "mouse5")):
            self.scan_mouse.addItem(label, value)
        shortcut_layout.addRow("Screen lookup key", self.scan_key)
        shortcut_layout.addRow("Screen lookup mouse", self.scan_mouse)
        self.pin_shortcut = ShortcutEdit("c", "C")
        self.pin_shortcut.setToolTip("Pin the preview while holding the screen lookup shortcut")
        shortcut_layout.addRow("Pin preview", self.pin_shortcut)
        default_search = "<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d"
        self.shortcut = ShortcutEdit(settings.value("hotkey", default_search),
                                     settings.value("hotkey_preset", shortcut_preset()))
        shortcut_layout.addRow("Look up text", self.shortcut)
        self.selected_text = QCheckBox("Look up selected text automatically")
        shortcut_layout.addRow(self.selected_text)
        self.selected_text.toggled.connect(self.save_text_triggers)
        save_shortcut = QPushButton("Apply")
        save_shortcut.clicked.connect(self.save_shortcut)
        shortcut_layout.addRow(save_shortcut)
        tabs.addTab(shortcuts, "Shortcuts")

        scanning = QWidget()
        scan_layout = QFormLayout(scanning)
        self.scan_layout = scan_layout
        self.auto_scan = QCheckBox("Scan automatically on hover")
        self.auto_scan.setChecked(settings.value("auto_scan", False, bool))
        self.auto_scan.setToolTip("Off: hold the scan key. On: pause over text to scan.")
        scan_layout.addRow(self.auto_scan)
        self.compact_preview = QCheckBox("Compact preview")
        self.compact_preview.setChecked(settings.value("compact_preview", True, bool))
        self.compact_preview.setToolTip("Pin to expand. Turn off to show full definitions immediately.")
        scan_layout.addRow(self.compact_preview)
        self.pin_gesture = QComboBox()
        for label, code in (("Scan key + left click", "left"), ("Scan key + middle click", "middle"),
                            ("Popup click only", "popup")):
            self.pin_gesture.addItem(label, code)
        self.pin_gesture.setCurrentIndex(max(0, self.pin_gesture.findData(settings.value("pin_gesture", "left"))))
        self.pin_gesture.setToolTip("Pin the current preview without moving the pointer to it.")
        scan_layout.addRow("Pin result", self.pin_gesture)
        self.ja_ocr_provider = QComboBox()
        self.ja_ocr_provider.addItem("MeikiOCR (CPU)", "meikiocr")
        self.ja_ocr_provider.addItem("PaddleOCR (multilingual)", "paddle")
        self.ja_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "darwin":
            self.ja_ocr_provider.addItem("Apple Vision", "vision")
        default_provider = "vision" if sys.platform == "darwin" else "meikiocr"
        self.ja_ocr_provider.setCurrentIndex(max(0, self.ja_ocr_provider.findData(settings.value("ja_ocr_provider", default_provider))))
        scan_layout.addRow("OCR model", self.ja_ocr_provider)
        self.tr_ocr_provider = QComboBox()
        self.tr_ocr_provider.addItem("PaddleOCR (local)", "paddle")
        self.tr_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "darwin":
            self.tr_ocr_provider.addItem("Apple Vision", "vision")
        tr_default = "vision" if sys.platform == "darwin" else "paddle"
        self.tr_ocr_provider.setCurrentIndex(max(0, self.tr_ocr_provider.findData(settings.value("tr_ocr_provider", tr_default))))
        scan_layout.addRow("OCR model", self.tr_ocr_provider)
        self.other_ocr_provider = QComboBox()
        self.other_ocr_provider.addItem("PaddleOCR (multilingual)", "paddle")
        self.other_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "darwin":
            self.other_ocr_provider.addItem("Apple Vision", "vision")
        scan_layout.addRow("OCR model", self.other_ocr_provider)
        self.screenai_controls = QWidget()
        component_layout = QVBoxLayout(self.screenai_controls)
        component_layout.setContentsMargins(0, 0, 0, 0)
        folder_row = QHBoxLayout()
        self.screenai_directory = QLineEdit(settings.value("screenai_directory", ""))
        self.screenai_directory.setPlaceholderText("Find installed component automatically")
        self.screenai_directory.setToolTip("Extract the complete Google component, then choose its folder. Restart after replacing a loaded component.")
        folder_row.addWidget(self.screenai_directory, 1)
        choose_component = QPushButton("Browse…")
        choose_component.clicked.connect(self.choose_screenai)
        folder_row.addWidget(choose_component)
        component_layout.addLayout(folder_row)
        from meikipop.ocr.providers.screenai.component import component_url
        component_link = QLabel(f'<a href="{component_url()}">Get the Google component for this computer</a>')
        component_link.setOpenExternalLinks(True)
        component_layout.addWidget(component_link)
        scan_layout.addRow(self.screenai_controls)
        def show_component_controls():
            provider = self.current_ocr_control()
            self.screenai_controls.setVisible(provider.currentData() == "screenai")
        self.show_component_controls = show_component_controls
        self.ja_ocr_provider.currentIndexChanged.connect(show_component_controls)
        self.tr_ocr_provider.currentIndexChanged.connect(show_component_controls)
        self.other_ocr_provider.currentIndexChanged.connect(show_component_controls)
        show_component_controls()
        if sys.platform != "win32":
            click_note = QLabel("Clicks outside the popup also reach the underlying app.")
            click_note.setWordWrap(True)
            scan_layout.addRow(click_note)
        save_scan = QPushButton("Apply")
        save_scan.clicked.connect(self.save_scan_settings)
        scan_layout.addRow(save_scan)
        tabs.addTab(scanning, "Screen lookup")

        from meikipop.gui.profile_appearance import ProfileAppearance
        self.appearance = ProfileAppearance(settings, self.profile.currentData, self.apply_appearance)
        tabs.addTab(self.appearance, "Appearance")
        audio = QWidget()
        audio_form = QFormLayout(audio)
        self.audio_autoplay = QComboBox()
        for label, mode in (("Off", "off"), ("On lookup", "lookup"), ("When pinned", "pin")):
            self.audio_autoplay.addItem(label, mode)
        audio_form.addRow("Autoplay", self.audio_autoplay)
        self.audio_volume = QSpinBox()
        self.audio_volume.setRange(0, 100)
        audio_form.addRow("Volume", self.audio_volume)
        self.audio_database = QLineEdit()
        self.audio_database.setPlaceholderText("System voice when no database is selected")
        audio_form.addRow("Japanese audio database", self.audio_database)
        audio_browse = QPushButton("Choose android.db…")
        audio_browse.clicked.connect(self.choose_audio)
        audio_form.addRow(audio_browse)
        self.audio_sources = QLineEdit()
        audio_form.addRow("Preferred sources", self.audio_sources)
        self.audio_form = audio_form
        self.audio_browse = audio_browse
        audio_apply = QPushButton("Apply")
        audio_apply.clicked.connect(self.save_audio)
        audio_form.addRow(audio_apply)
        tabs.addTab(audio, "Audio")
        self.audio_autoplay.currentIndexChanged.connect(self.save_autoplay)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        footer.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        footer.addWidget(self.cancel_button)
        done = QPushButton("Close")
        done.clicked.connect(self.reject)
        footer.addWidget(done)
        layout.addLayout(footer)
        self.reload()
        self.packs.itemChanged.connect(lambda _: self.save_dictionaries())
        self.profile.currentIndexChanged.connect(self.profile_changed)
        self.profile_changed()
        if translation_error:
            self.status.setText(translation_error)

    def reload(self, preserve=False):
        prior = {self.packs.item(i).data(Qt.ItemDataRole.UserRole): self.packs.item(i).checkState()
                 for i in range(self.packs.count())} if preserve else {}
        order = list(prior)
        library = Library(self.directory)
        try:
            blocker = QSignalBlocker(self.packs)
            self.packs.clear()
            packs = sorted(library.packs, key=lambda pack:
                           order.index(pack[0].name) if pack[0].name in order else len(order))
            for path, metadata, _ in packs:
                if self.profile.findData(metadata["language"]) < 0:
                    self.profile.addItem(language_name(metadata["language"]), metadata["language"])
                item = QListWidgetItem(f'{metadata["title"]}  ·  {language_name(metadata["language"])}'
                                       f'  ·  {int(metadata.get("entries", 0)):,}')
                item.setData(Qt.ItemDataRole.UserRole, path.name)
                item.setData(Qt.ItemDataRole.UserRole + 1, metadata["language"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(prior.get(path.name, Qt.CheckState.Checked if metadata["enabled"]
                                            else Qt.CheckState.Unchecked))
                self.packs.addItem(item)
                item.setHidden(metadata["language"] != self.profile.currentData())
            if library.errors:
                self.status.setText("\n".join(library.errors))
        finally:
            del blocker
            library.close()

    def move_pack(self, offset):
        row = self.packs.currentRow()
        visible = [i for i in range(self.packs.count()) if not self.packs.item(i).isHidden()]
        position = visible.index(row) + offset if row in visible else -1
        target = visible[position] if 0 <= position < len(visible) else -1
        if row >= 0 and 0 <= target < self.packs.count():
            item = self.packs.takeItem(row)
            self.packs.insertItem(target, item)
            self.packs.setCurrentRow(target)
            self.save_dictionaries()

    def save_dictionaries(self):
        items = [self.packs.item(index) for index in range(self.packs.count())]
        try:
            save_preferences(self.directory,
                             [item.data(Qt.ItemDataRole.UserRole) for item in items
                              if item.checkState() != Qt.CheckState.Checked],
                             [item.data(Qt.ItemDataRole.UserRole) for item in items])
            self.dictionaries_changed.emit()
            self.status.clear()
        except OSError as error:
            self.status.setText(str(error))

    def save_text_triggers(self):
        prefix = f"profiles/{self.profile.currentData()}/"
        self.settings.setValue(prefix + "selected_text", self.selected_text.isChecked())
        if self.parent() is not None:
            self.parent().scan_settings_changed.emit()

    def save_shortcut(self):
        try:
            from meikipop.gui.text_shortcuts import validate_shortcuts
            validate_shortcuts((self.shortcut.text(),))
            from meikipop.gui.turkish.desktop_input import validate_pin_shortcut
            validate_pin_shortcut(self.pin_shortcut.text())
            self._apply_shortcut(self.shortcut.text(), self.shortcut.recorder.keySequence().toString())
            bindings = ",".join(value for value in (self.scan_key.currentData(), self.scan_mouse.currentData()) if value)
            self.settings.setValue(f"profiles/{self.profile.currentData()}/scan_bindings", bindings)
            self.settings.setValue(f"profiles/{self.profile.currentData()}/pin_shortcut", self.pin_shortcut.text())
            self.settings.setValue(f"profiles/{self.profile.currentData()}/pin_shortcut_preset", self.pin_shortcut.recorder.keySequence().toString())
            self.settings.setValue(f"profiles/{self.profile.currentData()}/selected_text", self.selected_text.isChecked())
            if self.parent() is not None:
                self.parent().set_mode(self.profile.currentData())
                self.parent().scan_settings_changed.emit()
            self.status.setText("Saved.")
        except (ValueError, OSError, RuntimeError) as error:
            self.status.setText(str(error))

    def save_scan_settings(self):
        component_directory = self.screenai_directory.text().strip()
        provider = self.current_ocr_control()
        if provider.currentData() == "screenai":
            from meikipop.ocr.providers.screenai.component import find_component_directory
            try:
                find_component_directory(component_directory or None)
            except RuntimeError as error:
                self.status.setText(str(error))
                return
        prefix = f"profiles/{self.profile.currentData()}/"
        self.settings.setValue(prefix + "auto_scan", self.auto_scan.isChecked())
        self.settings.setValue(prefix + "compact_preview", self.compact_preview.isChecked())
        self.settings.setValue(prefix + "pin_gesture", self.pin_gesture.currentData())
        self.settings.setValue(prefix + "ocr_provider", provider.currentData())
        self.settings.setValue("ja_ocr_provider", self.ja_ocr_provider.currentData())
        self.settings.setValue("tr_ocr_provider", self.tr_ocr_provider.currentData())
        self.settings.setValue("screenai_directory", component_directory)
        window = self.parent()
        if window is not None:
            window.set_mode(self.profile.currentData())
            window._render()
            window.scan_settings_changed.emit()
        self.status.setText("Saved.")

    def profile_changed(self):
        from meikipop.config.config import config
        code = self.profile.currentData()
        self.status.clear()
        with QSignalBlocker(self.morphology):
            self.morphology.setChecked(self.settings.value(f"profiles/{code}/morphology", False, bool))
        self.morphology.setVisible(code != "ja")
        bindings = self.settings.value(f"profiles/{code}/scan_bindings", "shift").split(",")
        self.pin_shortcut.set_value(self.settings.value(f"profiles/{code}/pin_shortcut", "c"),
                                    self.settings.value(f"profiles/{code}/pin_shortcut_preset", "C"))
        with QSignalBlocker(self.selected_text):
            self.selected_text.setChecked(self.settings.value(f"profiles/{code}/selected_text", False, type=bool))
        self.scan_key.setCurrentIndex(max(0, next((self.scan_key.findData(b) for b in bindings if self.scan_key.findData(b) >= 0), 0)))
        self.scan_mouse.setCurrentIndex(max(0, next((self.scan_mouse.findData(b) for b in bindings if self.scan_mouse.findData(b) >= 0), 0)))
        for index in range(self.packs.count()):
            self.packs.item(index).setHidden(self.packs.item(index).data(Qt.ItemDataRole.UserRole + 1) != code)
        self.scan_layout.setRowVisible(self.ja_ocr_provider, code == "ja")
        self.scan_layout.setRowVisible(self.tr_ocr_provider, code == "tr")
        self.scan_layout.setRowVisible(self.other_ocr_provider, code not in ("ja", "tr"))
        provider = self.current_ocr_control()
        default = ("vision" if sys.platform == "darwin" else "meikiocr" if code == "ja" else "paddle")
        provider.setCurrentIndex(max(0, provider.findData(self.settings.value(f"profiles/{code}/ocr_provider", self.settings.value(f"{code}_ocr_provider", default)))))
        try:
            translation = load_profile_settings(self.settings, code)
        except ValueError as error:
            translation = TranslationSettings()
            self.status.setText(str(error))
        self.translation_partner.setCurrentIndex(max(0, self.translation_partner.findData(self.settings.value(f"profiles/{code}/target", "en"))))
        self.translation_mode.setCurrentIndex(self.translation_mode.findData(translation.profile if translation.provider == "server" else "custom"))
        self.translation_endpoint.setText(translation.endpoint)
        self.translation_model.setText(translation.model)
        self.translation_autostart.setChecked(translation.auto_start)
        self.appearance.reload()
        self.show_component_controls()
        self.auto_scan.setChecked(self.settings.value(f"profiles/{code}/auto_scan", self.settings.value("auto_scan", False, type=bool), type=bool))
        self.compact_preview.setChecked(self.settings.value(f"profiles/{code}/compact_preview", self.settings.value("compact_preview", True, type=bool), type=bool))
        self.pin_gesture.setCurrentIndex(max(0, self.pin_gesture.findData(self.settings.value(f"profiles/{code}/pin_gesture", self.settings.value("pin_gesture", "left")))))
        with QSignalBlocker(self.audio_autoplay):
            self.audio_autoplay.setCurrentIndex(max(0, self.audio_autoplay.findData(audio_autoplay_mode(self.settings, code))))
        self.audio_volume.setValue(self.settings.value(f"profiles/{code}/audio_volume", config.audio_volume, type=int))
        self.audio_database.setText(self.settings.value("profiles/ja/audio_database", config.audio_database_path))
        self.audio_sources.setText(self.settings.value("profiles/ja/audio_sources", config.audio_preferred_sources))
        for control in (self.audio_database, self.audio_browse, self.audio_sources):
            self.audio_form.setRowVisible(control, code == "ja")
        self.language.setCurrentIndex(max(0, self.language.findData(code)))
        if self.parent() is not None:
            self.parent().set_mode(code)

    def current_ocr_control(self):
        return {"ja": self.ja_ocr_provider, "tr": self.tr_ocr_provider}.get(self.profile.currentData(), self.other_ocr_provider)

    def save_morphology(self, enabled):
        code = self.profile.currentData()
        self.settings.setValue(f"profiles/{code}/morphology", enabled)
        self.dictionaries_changed.emit()
        if self.parent() is not None:
            self.parent().scan_settings_changed.emit()
        self.status.clear()
        if enabled:
            from meikipop.language.stanza_analyzer import default_model_dir
            if not (default_model_dir(code) / "resources.json").is_file():
                self.status.setText(f"Install models: python -m meikipop.scripts.setup_morphology {code}")

    def sync_profile(self, code):
        with QSignalBlocker(self.profile):
            if self.profile.findData(code) < 0:
                self.profile.addItem(language_name(code), code)
            self.profile.setCurrentIndex(self.profile.findData(code))
        self.profile_changed()

    def apply_appearance(self):
        window = self.parent()
        if window is not None:
            window.set_mode(self.profile.currentData())
            window.reload_appearance()
        self.status.setText("Saved.")

    def choose_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pronunciation database", self.audio_database.text(), "SQLite (*.db)")
        if path:
            self.audio_database.setText(path)

    def save_audio(self):
        code = self.profile.currentData()
        self.save_autoplay()
        self.settings.setValue(f"profiles/{code}/audio_volume", self.audio_volume.value())
        if code == "ja":
            self.settings.setValue("profiles/ja/audio_database", self.audio_database.text().strip())
            self.settings.setValue("profiles/ja/audio_sources", self.audio_sources.text())
        self.status.setText("Saved.")

    def save_autoplay(self):
        self.settings.setValue(f"profiles/{self.profile.currentData()}/audio_autoplay_mode", self.audio_autoplay.currentData())

    def choose_screenai(self):
        directory = QFileDialog.getExistingDirectory(self, "Chrome Screen AI component", self.screenai_directory.text())
        if directory:
            self.screenai_directory.setText(directory)

    def choose_dictionaries(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import dictionaries", "", "Yomitan dictionaries (*.zip)")
        if not paths:
            return
        language = self.language.currentData()
        if self.language.currentIndex() < 0 or self.language.currentText() != self.language.itemText(self.language.currentIndex()):
            language = self.language.currentText().strip().lower() or None
        self.begin_operation(paths, language=language)

    def update_translation_controls(self):
        custom = self.translation_mode.currentData() == "custom"
        self.translation_endpoint.setEnabled(custom)
        self.translation_model.setEnabled(custom)
        self.translation_autostart.setEnabled(not custom)
        self.model_button.setEnabled(not custom)

    def save_translation(self):
        mode = self.translation_mode.currentData()
        try:
            code = self.profile.currentData()
            if self.translation_partner.currentData() == code:
                raise ValueError("Choose two different languages for the translation pair.")
            save_profile_settings(self.settings, code, TranslationSettings(
                provider="custom" if mode == "custom" else "server",
                profile=mode if mode != "custom" else "quality",
                endpoint=self.translation_endpoint.text(), model=self.translation_model.text(),
                auto_start=self.translation_autostart.isChecked()))
            self.settings.setValue(f"profiles/{code}/target", self.translation_partner.currentData())
            if self.parent() is not None:
                self.parent().set_mode(code)
                self.parent().foreign.setCurrentIndex(self.parent().foreign.findData(self.translation_partner.currentData()))
            self.dictionaries_changed.emit()
            self.status.setText("Saved.")
            return True
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return False

    def choose_model(self):
        if self.translation_mode.currentData() != "custom" and self.save_translation():
            self.begin_operation([], profile=self.translation_mode.currentData())

    def begin_operation(self, paths, language=None, profile=None):
        if self.operation is not None:
            return
        self.operation = SetupOperation(paths, self.directory, language, profile)
        self.operation.progress.connect(self.status.setText)
        self.operation.finished.connect(self._finished)
        self.cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)
        for control in (self.import_button, self.model_button, self.packs, self.up, self.down, self.apply, self.language,
                        self.translation_mode, self.translation_apply, self.translation_endpoint,
                        self.translation_model, self.translation_autostart):
            control.setEnabled(False)
        self.operation.start()

    def cancel_operation(self):
        if self.operation is not None:
            self.operation.cancelled.set()
            self.status.setText("Finishing the current step…")
            self.cancel_button.setEnabled(False)

    def _finished(self, status, changed):
        self.operation = None
        self.cancel_button.setVisible(False)
        for control in (self.import_button, self.model_button, self.packs, self.up, self.down, self.apply, self.language,
                        self.translation_mode, self.translation_apply):
            control.setEnabled(True)
        self.update_translation_controls()
        self.reload(preserve=True)
        self.status.setText(status)
        if changed:
            self.dictionaries_changed.emit()
        if self._close_pending:
            self._close_pending = False
            super().reject()

    def reject(self):
        if self.operation is not None:
            self._close_pending = True
            self.cancel_operation()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.operation is not None:
            self._close_pending = True
            self.cancel_operation()
            event.ignore()
        else:
            super().closeEvent(event)
