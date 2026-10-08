"""Explicit, offline dictionary and translation setup."""
from pathlib import Path
import sys
import threading

from PyQt6.QtCore import QObject, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QInputDialog, QLineEdit, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from meikipop.dictionary.library import Library, default_library_path, language_code, save_preferences
from meikipop.dictionary.translation import TranslationSettings, load_settings, load_profile_settings, save_profile_settings
from meikipop.gui.quick_lookup import LANGUAGE_NAMES, language_name, shortcut_preset, audio_autoplay_mode
from meikipop.gui.shortcut_edit import ShortcutEdit
from meikipop.gui.settings_section import SettingsSection, StatusLabel
from meikipop.language.profiles import configured_profiles, default_partner


class SetupOperation(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str, bool)
    refresh = pyqtSignal()

    def __init__(self, paths, directory, language=None, profile=None, recommended=None, remove=None, morphology=None, ocr=None):
        super().__init__()
        self.paths = paths
        self.directory = directory
        self.language = language
        self.profile = profile
        self.recommended = recommended
        self.remove = remove
        self.morphology = morphology
        self.ocr = ocr
        self.installed_component = ""
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
        if isinstance(self.recommended, tuple):
            from meikipop.dictionary.import_job import background_import
            changed, errors = False, []
            for dictionary in self.recommended:
                if self.cancelled.is_set():
                    break
                try:
                    status, installed = background_import([], self.directory, dictionary.language, dictionary,
                                                         lambda text: self._emit(self.progress, text), self.cancelled)
                    changed |= installed
                    if not installed:
                        errors.append(f"{dictionary.title}: {status}")
                except Exception as error:
                    errors.append(f"{dictionary.title}: {error}")
            status = "Download cancelled." if self.cancelled.is_set() else "Dictionaries installed."
            self._emit(self.finished, "\n".join(errors) or status, changed)
            return
        if self.paths or self.recommended:
            try:
                from meikipop.dictionary.import_job import background_import
                result = background_import(self.paths, self.directory, self.language, self.recommended,
                                           lambda text: self._emit(self.progress, text), self.cancelled)
                self._emit(self.finished, *result)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.ocr:
            try:
                from meikipop.scripts.setup_ocr import install
                self.installed_component = install(self.ocr, lambda text: self._emit(self.progress, text), self.cancelled)
                self._emit(self.finished, "OCR ready. Scan with your selected shortcut.", True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.morphology:
            try:
                from meikipop.scripts.setup_morphology import install
                install(self.morphology, lambda text: self._emit(self.progress, text), self.cancelled)
                self._emit(self.finished, "Base-form model installed.", True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.remove:
            try:
                from meikipop.dictionary.library import remove_dictionary
                remove_dictionary(self.directory, self.remove, lambda: self._emit(self.refresh), self.cancelled)
                status = "Dictionary removed."
                self._emit(self.finished, status, True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
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
        self._emit(self.finished, "No dictionaries selected.", False)


class SetupDialog(QDialog):
    dictionaries_changed = pyqtSignal()

    def __init__(self, directory, settings, apply_shortcut, parent=None):
        super().__init__(parent)
        self.directory = Path(directory or default_library_path())
        self.settings = settings
        self._apply_shortcut = apply_shortcut
        self.operation = None
        self._close_pending = False
        self._loading = True
        self.setWindowTitle("Meikipop Settings")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        self.profile = QComboBox()
        for code in configured_profiles(settings):
            self.profile.addItem(language_name(code), code)
        self.profile.setCurrentIndex(max(0, self.profile.findData(settings.value("profile", ""))))
        profile_row.addWidget(QLabel("Language"))
        profile_row.addWidget(self.profile, 1)
        self.add_profile_button = QPushButton("Add language…")
        self.add_profile_button.clicked.connect(self.choose_profile)
        profile_row.addWidget(self.add_profile_button)
        layout.addLayout(profile_row)
        tabs = QTabWidget()
        self.tabs = tabs
        layout.addWidget(tabs, 1)
        dictionaries = QWidget()
        dictionary_layout = QVBoxLayout(dictionaries)
        self.packs = QListWidget()
        self.packs.setAccessibleName("Installed dictionaries, in priority order")
        self.packs.setToolTip("Checked dictionaries are enabled. Higher dictionaries appear first.")
        dictionary_layout.addWidget(self.packs, 1)
        self.dictionary_display = QComboBox()
        self.dictionary_display.setAccessibleName("Default dictionary display")
        for label, value in (("Expanded", "expanded"), ("Preview", "preview"), ("Collapsed", "collapsed")):
            self.dictionary_display.addItem(label, value)
        self.dictionary_display.setToolTip("Initial display for this dictionary; pinning keeps this choice")
        self.dictionary_display.currentIndexChanged.connect(self.save_dictionary_display)
        self.packs.currentItemChanged.connect(self.update_dictionary_display)
        dictionary_layout.addWidget(self.dictionary_display)
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
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_dictionary)
        actions.addWidget(self.remove_button)
        actions.addStretch()
        dictionary_layout.insertLayout(0, actions)
        self.combine_frequencies = QCheckBox("Combine frequency rankings")
        self.combine_frequencies.setToolTip("Harmonic mean across enabled rank dictionaries; best matching rank per dictionary")
        self.combine_frequencies.toggled.connect(self.save_frequency_display)
        dictionary_layout.addWidget(self.combine_frequencies)
        dictionary_layout.addStretch()
        translation = QWidget()
        translation_layout = QVBoxLayout(translation)
        translation_form = QFormLayout()
        self.translation_advanced_widget = QWidget()
        advanced_form = self.translation_advanced_form = QFormLayout(self.translation_advanced_widget)
        self.translation_pair_label = QLabel()
        self.translation_partner = QComboBox()
        for code, name in LANGUAGE_NAMES.items():
            self.translation_partner.addItem(name, code)
        translation_form.addRow(self.translation_pair_label, self.translation_partner)
        from meikipop.gui.language_strip import LanguageStrip
        self.translation_source = LanguageStrip(LANGUAGE_NAMES)
        self.translation_target = LanguageStrip(LANGUAGE_NAMES)
        for label, control in (("From", self.translation_source), ("To", self.translation_target)):
            advanced_form.addRow(label, control)
        self.translation_mode = QComboBox()
        self.translation_mode.addItem("Quality (8 GB)", "quality")
        self.translation_mode.addItem("Lightweight (1.9 GB)", "lightweight")
        self.translation_mode.addItem("Custom local server", "custom")
        translation_form.addRow("Model", self.translation_mode)
        self.translation_endpoint = QLineEdit()
        self.translation_endpoint.setAccessibleName("Local translation server address")
        advanced_form.addRow("Address", self.translation_endpoint)
        self.translation_model = QLineEdit()
        self.translation_model.setAccessibleName("Local translation server model name")
        advanced_form.addRow("Server model", self.translation_model)
        self.translation_stream = QCheckBox("Stream translation")
        advanced_form.addRow(self.translation_stream)
        self.translation_warm = QCheckBox("Keep model warm")
        self.translation_warm.setToolTip("Retains model memory after use. Changes apply on the next translation.")
        advanced_form.addRow(self.translation_warm)
        self.translation_routing = {}
        for key, label in (("auto_translate_miss", "Translate partial dictionary matches"),):
            control = QCheckBox(label)
            self.translation_routing[key] = control
            advanced_form.addRow(control)
            control.toggled.connect(lambda _: self.autosave(self.save_translation_routing))
        translation_layout.addLayout(translation_form)
        self.translation_advanced = QCheckBox("Advanced")
        self.translation_advanced.toggled.connect(self.translation_advanced_widget.setVisible)
        translation_layout.addWidget(self.translation_advanced)
        translation_layout.addWidget(self.translation_advanced_widget)
        self.translation_advanced_widget.hide()
        translation_layout.addStretch()
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
        self.translation_stream.setChecked(translation_settings.stream)
        self.translation_warm.setChecked(translation_settings.keep_warm)
        self.translation_mode.currentIndexChanged.connect(self.update_translation_controls)
        self.update_translation_controls()

        shortcuts = QWidget()
        shortcut_layout = QFormLayout(shortcuts)
        self.scan_key = QComboBox()
        for label, value in (("None", ""), ("Shift", "shift"), ("Ctrl", "ctrl"), ("Alt", "alt"),
                             ("Ctrl + Shift", "ctrl+shift"), ("Ctrl + Alt", "ctrl+alt"), ("Alt + Shift", "alt+shift")):
            self.scan_key.addItem(label, value)
        if sys.platform == "darwin":
            self.scan_key.addItem("Command", "cmd")
            self.scan_key.addItem("Command + Shift", "cmd+shift")
        self.scan_mouse = QComboBox()
        for label, value in (("None", ""), ("Middle mouse", "middle"), ("Mouse 4", "mouse4"), ("Mouse 5", "mouse5")):
            self.scan_mouse.addItem(label, value)
        shortcut_layout.addRow("Screen lookup key", self.scan_key)
        shortcut_layout.addRow("Screen lookup mouse", self.scan_mouse)
        self.pin_shortcut = ShortcutEdit("c", "C")
        self.pin_shortcut.setMaximumWidth(190)
        self.pin_shortcut.enabled.setText("Key")
        self.pin_shortcut.enabled.setToolTip("Enable keyboard pinning")
        self.pin_shortcut.setToolTip("Pin the preview while holding the screen lookup shortcut")
        default_search = "<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d"
        self.shortcut = ShortcutEdit(settings.value("hotkey", default_search),
                                     settings.value("hotkey_preset", shortcut_preset()))
        self.shortcut.setToolTip("Look up selected or copied text. Shared by all languages.")
        shortcut_layout.addRow("Text lookup", self.shortcut)
        self.selected_text = QCheckBox("Look up selected text automatically")
        shortcut_layout.addRow(self.selected_text)
        self.selected_text.toggled.connect(self.save_text_triggers)
        self.selection_lookup = QCheckBox("Look up selection inside results")
        shortcut_layout.addRow(self.selection_lookup)
        self.selection_lookup.toggled.connect(lambda _: self.autosave(self.save_selection_policy))

        scanning = QWidget()
        scan_layout = QFormLayout(scanning)
        self.scan_layout = scan_layout
        self.freeze_while_held = QCheckBox("Freeze capture while holding the lookup key")
        self.freeze_while_held.setToolTip("One screenshot per hold. Release to refresh; the video keeps playing.")
        scan_layout.addRow(self.freeze_while_held)
        self.freeze_while_held.toggled.connect(lambda _: self.autosave(self.save_scan_settings))
        self.pin_gesture = QComboBox()
        for label, code in (("Left click", "left"), ("Middle click", "middle"),
                            ("Popup click only", "popup")):
            self.pin_gesture.addItem(label, code)
        self.pin_gesture.setCurrentIndex(max(0, self.pin_gesture.findData(settings.value("pin_gesture", "left"))))
        self.pin_gesture.setToolTip("Mouse button to pin while holding a screen lookup shortcut")
        pin_controls = QWidget()
        pin_layout = QHBoxLayout(pin_controls)
        pin_layout.setContentsMargins(0, 0, 0, 0)
        pin_layout.addWidget(self.pin_shortcut)
        pin_layout.addWidget(self.pin_gesture)
        shortcut_layout.insertRow(2, "Pin while holding lookup", pin_controls)
        self.ja_ocr_provider = QComboBox()
        self.ja_ocr_provider.addItem("MeikiOCR (CPU)", "meikiocr")
        self.ja_ocr_provider.addItem("PaddleOCR (multilingual)", "paddle")
        self.ja_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "darwin":
            self.ja_ocr_provider.addItem("Apple Vision", "vision")
        default_provider = "vision" if sys.platform == "darwin" else "meikiocr"
        self.ja_ocr_provider.setCurrentIndex(max(0, self.ja_ocr_provider.findData(settings.value("profiles/ja/ocr_provider", default_provider))))
        scan_layout.addRow("OCR model", self.ja_ocr_provider)
        self.tr_ocr_provider = QComboBox()
        self.tr_ocr_provider.addItem("PaddleOCR (local)", "paddle")
        self.tr_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "darwin":
            self.tr_ocr_provider.addItem("Apple Vision", "vision")
        tr_default = "vision" if sys.platform == "darwin" else "paddle"
        self.tr_ocr_provider.setCurrentIndex(max(0, self.tr_ocr_provider.findData(settings.value("profiles/tr/ocr_provider", tr_default))))
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
        from meikipop.gui.profile_appearance import ProfileAppearance
        self.appearance = ProfileAppearance(settings, self.profile.currentData, self.apply_appearance)
        audio = QWidget()
        audio_layout = QVBoxLayout(audio)
        audio_form = QFormLayout()
        audio_layout.addLayout(audio_form)
        audio_details = QWidget()
        audio_detail_form = QFormLayout(audio_details)
        self.audio_autoplay = QComboBox()
        for label, mode in (("Off", "off"), ("On lookup", "lookup"), ("When pinned", "pin")):
            self.audio_autoplay.addItem(label, mode)
        audio_form.addRow("Autoplay", self.audio_autoplay)
        self.audio_volume = QSpinBox()
        self.audio_volume.setRange(0, 100)
        audio_form.addRow("Volume", self.audio_volume)
        self.audio_database = QLineEdit()
        self.audio_database.setPlaceholderText("Local Audio Server android.db")
        audio_browse = QPushButton("Browse…")
        audio_browse.clicked.connect(self.choose_audio)
        self.audio_database_row = QWidget()
        database_layout = QHBoxLayout(self.audio_database_row)
        database_layout.setContentsMargins(0, 0, 0, 0)
        database_layout.addWidget(self.audio_database, 1)
        database_layout.addWidget(audio_browse)
        self.audio_remove = QPushButton("Remove")
        self.audio_remove.setToolTip("Disconnect this database without deleting its file")
        self.audio_remove.clicked.connect(self.remove_audio_database)
        database_layout.addWidget(self.audio_remove)
        audio_detail_form.addRow("Local database", self.audio_database_row)
        from meikipop.gui.audio_sources import AudioSources
        self.audio_sources = AudioSources()
        self.audio_sources.changed.connect(lambda: self.autosave(self.save_audio))
        audio_detail_form.addRow("Source priority", self.audio_sources)
        audio_layout.addWidget(SettingsSection("Sources", audio_details))
        audio_layout.addStretch()
        self.audio_form = audio_detail_form
        self.audio_browse = audio_browse
        self.audio_tab = audio
        self.audio_autoplay.currentIndexChanged.connect(self.save_autoplay)
        from meikipop.gui.anki import AnkiSettingsPanel
        self.anki = AnkiSettingsPanel(settings)
        if hasattr(parent, "update_anki"):
            self.anki.changed.connect(parent.update_anki)

        self.status = StatusLabel()
        self.audio_sources.failed.connect(self.status.setText)
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
        self._loading = False
        for control in (self.translation_partner, self.translation_source, self.translation_target, self.translation_mode):
            control.currentIndexChanged.connect(lambda _: self.autosave(self.save_translation))
        for control in (self.translation_endpoint, self.translation_model):
            control.editingFinished.connect(lambda: self.autosave(self.save_translation))
        self.translation_stream.toggled.connect(lambda _: self.autosave(self.save_translation))
        self.translation_warm.toggled.connect(lambda _: self.autosave(lambda: self.save_translation(cancel=False)))
        for control in (self.scan_key, self.scan_mouse):
            control.currentIndexChanged.connect(lambda _: self.autosave(self.save_shortcut))
        for control in (self.shortcut, self.pin_shortcut):
            control.recorder.editingFinished.connect(lambda: self.autosave(self.save_shortcut))
            control.enabled.toggled.connect(lambda _: self.autosave(self.save_shortcut))
        for control in (self.pin_gesture, self.ja_ocr_provider, self.tr_ocr_provider, self.other_ocr_provider):
            control.currentIndexChanged.connect(lambda _: self.autosave(self.save_scan_settings))
        self.screenai_directory.editingFinished.connect(lambda: self.autosave(self.save_scan_settings))
        self.audio_volume.valueChanged.connect(lambda _: self.autosave(self.save_audio))
        self.audio_database.editingFinished.connect(lambda: self.autosave(self.save_audio))
        from meikipop.gui.resources import ResourcesPanel
        self.resources = ResourcesPanel(self)
        dictionary_layout.insertWidget(0, self.resources.dictionary_section)
        scan_layout.addRow(self.resources.ocr_section)
        translation_layout.insertWidget(1, self.resources.translation_section)

        # Keep one destination per task, with downloads beside the feature they enable.
        def add_page(widget, title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(widget)
            tabs.addTab(scroll, title)
            return scroll

        lookup = QWidget()
        lookup_layout = QVBoxLayout(lookup)
        lookup_layout.addWidget(shortcuts)
        self.screen_section = SettingsSection("Screen recognition", scanning)
        self.screen_section.toggle.setChecked(not self.resources.ocr_section.isHidden())
        lookup_layout.addWidget(self.screen_section)
        lookup_layout.addStretch()
        self.lookup_tab = add_page(lookup, "Lookup")
        add_page(dictionaries, "Dictionaries")
        add_page(self.appearance, "Appearance")
        self.audio_tab = add_page(audio, "Audio")
        self.translation_tab = add_page(translation, "Translation")
        self.anki_tab = add_page(self.anki, "Anki")
        tabs.setCurrentWidget(self.lookup_tab)
        tabs.currentChanged.connect(lambda: self.resources.refresh())
        if translation_error:
            self.status.setText(translation_error)

    def autosave(self, callback):
        if not self._loading and self.profile.currentData():
            callback()

    def show_audio(self):
        self.tabs.setCurrentWidget(self.audio_tab)

    def show_anki(self):
        self.tabs.setCurrentWidget(self.anki_tab)

    def reload(self, preserve=False):
        selected = self.packs.currentItem().data(Qt.ItemDataRole.UserRole) if self.packs.currentItem() else None
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
                item = QListWidgetItem(metadata["title"])
                item.setToolTip(f'{int(metadata.get("entries", 0)):,} entries')
                item.setData(Qt.ItemDataRole.UserRole, path.name)
                item.setData(Qt.ItemDataRole.UserRole + 1, metadata["language"])
                item.setData(Qt.ItemDataRole.UserRole + 2, metadata["title"])
                item.setData(Qt.ItemDataRole.UserRole + 3, int(metadata.get("entries", 0)) > 0)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(prior.get(path.name, Qt.CheckState.Checked if metadata["enabled"]
                                            else Qt.CheckState.Unchecked))
                self.packs.addItem(item)
                if path.name == selected:
                    self.packs.setCurrentItem(item)
                item.setHidden(metadata["language"] != self.profile.currentData())
            if library.errors:
                self.status.setText("\n".join(library.errors))
        finally:
            del blocker
            library.close()
        self.update_dictionary_display()

    def update_dictionary_display(self, *_):
        item = self.packs.currentItem()
        valid = (item is not None and item.data(Qt.ItemDataRole.UserRole + 1) == self.profile.currentData()
                 and item.data(Qt.ItemDataRole.UserRole + 3))
        self.dictionary_display.setEnabled(bool(valid))
        self.dictionary_display.setVisible(bool(valid))
        mode = "preview"
        if valid:
            source = item.data(Qt.ItemDataRole.UserRole + 2)
            for candidate in ("expanded", "collapsed"):
                sources = self.settings.value(f"profiles/{self.profile.currentData()}/{candidate}_dictionaries", [], type=list)
                if source in sources:
                    mode = candidate
        with QSignalBlocker(self.dictionary_display):
            self.dictionary_display.setCurrentIndex(self.dictionary_display.findData(mode))

    def save_dictionary_display(self, *_):
        item = self.packs.currentItem()
        if self._loading or item is None or not self.dictionary_display.isEnabled():
            return
        source = item.data(Qt.ItemDataRole.UserRole + 2)
        mode = self.dictionary_display.currentData()
        profile = self.profile.currentData()
        for candidate in ("expanded", "collapsed"):
            key = f"profiles/{profile}/{candidate}_dictionaries"
            sources = set(self.settings.value(key, [], type=list))
            sources.discard(source)
            if mode == candidate:
                sources.add(source)
            self.settings.setValue(key, sorted(sources))
        parent = self.parent()
        if parent is not None and parent.preferred_foreign == profile:
            parent.set_dictionary_display(source, mode)

    def choose_profile(self):
        from meikipop.language.support import support_summary
        choices = {f"{name} ({code}) · {support_summary(code)}": code for code, name in LANGUAGE_NAMES.items()
                   if self.profile.findData(code) < 0}
        name, accepted = QInputDialog.getItem(self, "Add language", "Language or code", sorted(choices), editable=True)
        if accepted:
            try:
                names = {label.casefold(): code for code, label in LANGUAGE_NAMES.items()}
                code = choices.get(name, names.get(name.strip().casefold(), name.strip().lower()))
                self.add_profile(language_code(code))
            except ValueError as error:
                self.status.setText(str(error))

    def add_profile(self, code):
        from meikipop.language.support import AVAILABLE_LANGUAGES
        if code not in AVAILABLE_LANGUAGES and self.profile.findData(code) < 0:
            raise ValueError("Import a dictionary for this language first.")
        added = self.profile.findData(code) < 0
        prefix = f"profiles/{code}/"
        if not self.settings.contains(prefix + "target"):
            self.settings.setValue(prefix + "target", default_partner(code))
        if not self.settings.contains(prefix + "scan_bindings"):
            bindings = self.settings.value(f"profiles/{self.profile.currentData()}/scan_bindings", "shift")
            self.settings.setValue(prefix + "scan_bindings", bindings)
        if self.parent() is not None:
            self.parent().update_languages(())
        self.sync_profile(code)
        if added and self.parent() is not None:
            from meikipop.gui.first_run import offer_resources
            offer_resources(self.parent(), code)

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

    def remove_dictionary(self):
        item = self.packs.currentItem()
        if item is None or item.isHidden():
            return
        title = item.text()
        if QMessageBox.question(self, "Remove dictionary", f"Remove {title}?") == QMessageBox.StandardButton.Yes:
            self.begin_operation([], remove=item.data(Qt.ItemDataRole.UserRole))

    def save_dictionaries(self):
        items = [self.packs.item(index) for index in range(self.packs.count())]
        try:
            save_preferences(self.directory,
                             [item.data(Qt.ItemDataRole.UserRole) for item in items
                              if item.checkState() != Qt.CheckState.Checked],
                             [item.data(Qt.ItemDataRole.UserRole) for item in items])
            self.dictionaries_changed.emit()
            self.resources.refresh()
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
            warning = self._apply_shortcut(self.shortcut.text(), self.shortcut.recorder.keySequence().toString())
            bindings = ",".join(value for value in (self.scan_key.currentData(), self.scan_mouse.currentData()) if value)
            self.settings.setValue(f"profiles/{self.profile.currentData()}/scan_bindings", bindings)
            self.settings.setValue(f"profiles/{self.profile.currentData()}/pin_shortcut", self.pin_shortcut.text())
            self.settings.setValue(f"profiles/{self.profile.currentData()}/pin_shortcut_preset", self.pin_shortcut.recorder.keySequence().toString())
            self.settings.setValue(f"profiles/{self.profile.currentData()}/selected_text", self.selected_text.isChecked())
            if self.parent() is not None:
                self.parent().set_mode(self.profile.currentData())
                self.parent().scan_settings_changed.emit()
            self.status.setText(warning if isinstance(warning, str) and warning else "")
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
        self.settings.setValue(prefix + "pin_gesture", self.pin_gesture.currentData())
        self.settings.setValue(prefix + "freeze_while_held", self.freeze_while_held.isChecked())
        self.settings.setValue(prefix + "ocr_provider", provider.currentData())
        self.settings.setValue("screenai_directory", component_directory)
        window = self.parent()
        if window is not None:
            window.set_mode(self.profile.currentData())
            window._render()
            window.scan_settings_changed.emit()
        self.status.clear()
        if hasattr(self, "resources"):
            self.resources.refresh()

    def profile_changed(self):
        from meikipop.config.config import config
        previous_loading, self._loading = self._loading, True
        code = self.profile.currentData()
        if code is None:
            self._loading = previous_loading
            return
        self.anki.load(code)
        with QSignalBlocker(self.freeze_while_held):
            self.freeze_while_held.setChecked(self.settings.value(f"profiles/{code}/freeze_while_held", True, bool))
        with QSignalBlocker(self.selection_lookup):
            self.selection_lookup.setChecked(self.settings.value(f"profiles/{code}/selection_lookup", False, bool))
        for key, control in self.translation_routing.items():
            with QSignalBlocker(control):
                control.setChecked(self.settings.value(f"profiles/{code}/{key}", False, bool))
        self.status.clear()
        with QSignalBlocker(self.combine_frequencies):
            self.combine_frequencies.setChecked(self.settings.value(f"profiles/{code}/combine_frequencies", True, bool))
        bindings = self.settings.value(f"profiles/{code}/scan_bindings", "shift").split(",")
        self.pin_shortcut.set_value(self.settings.value(f"profiles/{code}/pin_shortcut", "c"),
                                    self.settings.value(f"profiles/{code}/pin_shortcut_preset", "C"))
        with QSignalBlocker(self.selected_text):
            self.selected_text.setChecked(self.settings.value(f"profiles/{code}/selected_text", False, type=bool))
        self.scan_key.setCurrentIndex(max(0, next((self.scan_key.findData(b) for b in bindings if self.scan_key.findData(b) >= 0), 0)))
        self.scan_mouse.setCurrentIndex(max(0, next((self.scan_mouse.findData(b) for b in bindings if self.scan_mouse.findData(b) >= 0), 0)))
        for index in range(self.packs.count()):
            self.packs.item(index).setHidden(self.packs.item(index).data(Qt.ItemDataRole.UserRole + 1) != code)
        self.update_dictionary_display()
        self.scan_layout.setRowVisible(self.ja_ocr_provider, code == "ja")
        self.scan_layout.setRowVisible(self.tr_ocr_provider, code == "tr")
        self.scan_layout.setRowVisible(self.other_ocr_provider, code not in ("ja", "tr"))
        provider = self.current_ocr_control()
        from meikipop.language.support import PADDLE_LANGUAGES, default_ocr_provider
        paddle = provider.model().item(provider.findData("paddle"))
        bundled_mac = sys.platform == "darwin" and getattr(sys, "frozen", False)
        paddle.setEnabled(code in PADDLE_LANGUAGES and not bundled_mac)
        if bundled_mac and provider.findData("meikiocr") >= 0:
            provider.model().item(provider.findData("meikiocr")).setEnabled(False)
        paddle.setToolTip("" if code in PADDLE_LANGUAGES else "The installed Paddle model does not support this language")
        default = default_ocr_provider(code)
        provider.setCurrentIndex(max(0, provider.findData(self.settings.value(f"profiles/{code}/ocr_provider", default))))
        try:
            translation = load_profile_settings(self.settings, code)
        except ValueError as error:
            translation = TranslationSettings()
            self.status.setText(str(error))
        partner = self.settings.value(f"profiles/{code}/target", default_partner(code))
        if self.translation_partner.findData(partner) < 0:
            self.translation_partner.addItem(language_name(partner), partner)
        self.translation_partner.setCurrentIndex(self.translation_partner.findData(partner))
        for key, control in (("source", self.translation_source), ("target", self.translation_target)):
            control.set_pair(code, self.translation_partner.currentData())
            selected = self.settings.value(f"profiles/{code}/translation_{key}", "auto")
            if control.findData(selected) < 0:
                control.addItem(language_name(selected), selected)
            control.setCurrentIndex(control.findData(selected))
        self.translation_mode.setCurrentIndex(self.translation_mode.findData(translation.profile if translation.provider == "server" else "custom"))
        self.translation_endpoint.setText(translation.endpoint)
        self.translation_model.setText(translation.model)
        self.translation_pair_label.setText(language_name(code) + " \u2194")
        self.translation_advanced.setChecked(translation.provider == "custom" or any(
            self.settings.value(f"profiles/{code}/translation_{key}", "auto") != "auto" for key in ("source", "target")))
        self.translation_stream.setChecked(translation.stream)
        self.translation_warm.setChecked(translation.keep_warm)
        self.appearance.reload()
        self.show_component_controls()
        self.pin_gesture.setCurrentIndex(max(0, self.pin_gesture.findData(self.settings.value(f"profiles/{code}/pin_gesture", "left"))))
        with QSignalBlocker(self.audio_autoplay):
            self.audio_autoplay.setCurrentIndex(max(0, self.audio_autoplay.findData(audio_autoplay_mode(self.settings, code))))
        self.audio_volume.setValue(self.settings.value(f"profiles/{code}/audio_volume", config.audio_volume, type=int))
        from meikipop.audio.sources import database_path, source_order
        self.audio_database.setText(database_path(self.settings, code))
        self.audio_remove.setVisible(bool(self.audio_database.text()))
        self.audio_sources.load(source_order(self.settings, code), self.audio_database.text())
        self.language.setCurrentIndex(max(0, self.language.findData(code)))
        self._loading = previous_loading
        if self.parent() is not None:
            self.parent().set_mode(code)
        if hasattr(self, "resources"):
            self.resources.refresh()

    def current_ocr_control(self):
        return {"ja": self.ja_ocr_provider, "tr": self.tr_ocr_provider}.get(self.profile.currentData(), self.other_ocr_provider)

    def save_selection_policy(self):
        self.settings.setValue(f"profiles/{self.profile.currentData()}/selection_lookup", self.selection_lookup.isChecked())
        if self.parent() is not None:
            self.parent().browser.selection_lookup = self.selection_lookup.isChecked()

    def save_translation_routing(self):
        for key, control in self.translation_routing.items():
            self.settings.setValue(f"profiles/{self.profile.currentData()}/{key}", control.isChecked())
        if self.parent() is not None:
            self.parent()._edited()

    def save_frequency_display(self, enabled):
        self.settings.setValue(f"profiles/{self.profile.currentData()}/combine_frequencies", enabled)
        if self.parent() is not None:
            self.parent()._render()

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
        self.status.clear()

    def choose_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pronunciation database", self.audio_database.text(), "SQLite (*.db)")
        if path:
            self.audio_database.setText(path)
            self.autosave(self.save_audio)

    def save_audio(self):
        code = self.profile.currentData()
        self.save_autoplay()
        self.settings.setValue(f"profiles/{code}/audio_volume", self.audio_volume.value())
        self.settings.setValue(f"profiles/{code}/audio_database", self.audio_database.text().strip())
        path = self.audio_database.text().strip()
        if path != self.audio_sources.path:
            self.audio_sources.load(self.audio_sources.order(), path, prefer_local=True)
        self.settings.setValue(f"profiles/{code}/audio_priority", self.audio_sources.order())
        self.audio_remove.setVisible(bool(path))
        self.status.clear()

    def remove_audio_database(self):
        self.audio_database.clear()
        self.autosave(self.save_audio)

    def save_autoplay(self):
        self.settings.setValue(f"profiles/{self.profile.currentData()}/audio_autoplay_mode", self.audio_autoplay.currentData())

    def choose_screenai(self):
        directory = QFileDialog.getExistingDirectory(self, "Chrome Screen AI component", self.screenai_directory.text())
        if directory:
            self.screenai_directory.setText(directory)
            self.autosave(self.save_scan_settings)

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
        self.translation_advanced_form.setRowVisible(self.translation_endpoint, custom)
        self.translation_advanced_form.setRowVisible(self.translation_model, custom)
        if custom:
            self.translation_advanced.setChecked(True)
        self.translation_advanced_form.setRowVisible(self.translation_warm, not custom)
        if hasattr(self, "resources"):
            self.resources.refresh()

    def save_translation(self, *, cancel=True):
        mode = self.translation_mode.currentData()
        try:
            code = self.profile.currentData()
            if self.translation_partner.currentData() == code:
                raise ValueError("Choose two different languages for the translation pair.")
            if self.translation_source.currentData() == self.translation_target.currentData() != "auto":
                raise ValueError("Choose different source and target languages.")
            save_profile_settings(self.settings, code, TranslationSettings(
                provider="custom" if mode == "custom" else "server",
                profile=mode if mode != "custom" else "quality",
                endpoint=self.translation_endpoint.text(), model=self.translation_model.text(),
                auto_start=True, stream=self.translation_stream.isChecked(),
                keep_warm=self.translation_warm.isChecked()))
            self.settings.setValue(f"profiles/{code}/target", self.translation_partner.currentData())
            for key, control in (("source", self.translation_source), ("target", self.translation_target)):
                self.settings.setValue(f"profiles/{code}/translation_{key}", control.currentData())
                with QSignalBlocker(control):
                    control.set_pair(code, self.translation_partner.currentData())
            if self.parent() is not None:
                window = self.parent()
                with QSignalBlocker(window.source), QSignalBlocker(window.foreign):
                    window.set_mode(code)
                    window.foreign.setCurrentIndex(window.foreign.findData(self.translation_partner.currentData()))
                if cancel:
                    window._edited()
            self.status.clear()
            return True
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return False

    def begin_operation(self, paths, language=None, profile=None, recommended=None, remove=None, morphology=None, ocr=None):
        if self.operation is not None:
            return
        self.operation = SetupOperation(paths, self.directory, language, profile, recommended, remove, morphology, ocr)
        self.operation.refresh.connect(self.dictionaries_changed)
        self.operation.progress.connect(self.status.setText)
        self.operation.finished.connect(self._finished)
        self.cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)
        for control in (self.import_button, self.remove_button, self.profile, self.add_profile_button,
                        self.packs, self.up, self.down, self.language,
                        self.ja_ocr_provider, self.tr_ocr_provider, self.other_ocr_provider,
                        self.translation_partner, self.translation_mode, self.translation_source, self.translation_target, self.translation_endpoint,
                        self.translation_model):
            control.setEnabled(False)
        self.operation.start()
        self.resources.refresh()

    def cancel_operation(self):
        if self.operation is not None:
            self.operation.cancelled.set()
            self.status.setText("Finishing the current step…")
            self.cancel_button.setEnabled(False)

    def _finished(self, status, changed):
        component = self.operation.installed_component if self.operation is not None else ""
        if component:
            self.screenai_directory.setText(component)
            self.settings.setValue("screenai_directory", component)
        self.operation = None
        self.cancel_button.setVisible(False)
        for control in (self.import_button, self.remove_button, self.profile, self.add_profile_button,
                        self.packs, self.up, self.down, self.language,
                        self.ja_ocr_provider, self.tr_ocr_provider, self.other_ocr_provider,
                        self.translation_partner, self.translation_mode, self.translation_source, self.translation_target):
            control.setEnabled(True)
        self.update_translation_controls()
        self.reload(preserve=True)
        self.resources.refresh()
        self.status.setText(status)
        if changed:
            self.dictionaries_changed.emit()
            if self.parent() is not None:
                self.parent().scan_settings_changed.emit()
        if self._close_pending:
            self._close_pending = False
            super().reject()

    def reject(self):
        self.audio_sources.shutdown()
        # Closing Settings leaves the background job running. Cancel is explicit.
        super().reject()

    def closeEvent(self, event):
        self.audio_sources.shutdown()
        super().closeEvent(event)
