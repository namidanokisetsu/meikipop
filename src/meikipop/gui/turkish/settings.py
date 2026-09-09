"""Turkish settings using Meikipop's presets and activation conventions."""
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QColor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QTabWidget, QWidget,
                            QGroupBox, QCheckBox, QComboBox, QSpinBox, QLineEdit,
                            QFontComboBox, QDialogButtonBox, QPushButton, QLabel,
                            QMessageBox, QColorDialog, QListWidget, QHBoxLayout, QAbstractItemView)

from meikipop.config.config import config
from meikipop.gui.activation import parse_activation_bindings, serialise_activation_bindings
from meikipop.gui.themes import THEMES
from meikipop.gui.shortcut_edit import ShortcutEdit


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("meikipop-turkish Settings")
        self.setMinimumWidth(440)
        self.window = window
        self.fields = {}
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        def tab(name):
            page = QWidget()
            form = QFormLayout(page)
            tabs.addTab(page, name)
            return form

        def check(form, key, label, default):
            field = QCheckBox()
            field.setChecked(window.settings.value(key, default, bool))
            form.addRow(label, field)
            self.fields[key] = field
            return field

        def spin(form, key, label, default, minimum, maximum):
            field = QSpinBox()
            field.setRange(minimum, maximum)
            field.setValue(window.settings.value(key, default, int))
            form.addRow(label, field)
            self.fields[key] = field
            return field

        general = tab("General")
        configured = parse_activation_bindings(window.bindings)
        binding = next((b for b in configured if not b & {"middle", "mouse4", "mouse5"}), frozenset())
        self.activation = QComboBox()
        self.activation.addItems(["None", "ctrl", "shift", "alt", "cmd", "ctrl+shift", "ctrl+alt", "shift+alt", "ctrl+shift+alt"])
        selected = serialise_activation_bindings([binding]) if binding else "None"
        if self.activation.findText(selected) < 0:
            self.activation.addItem(selected)
        self.activation.setCurrentText(selected)
        general.addRow("Keyboard activation:", self.activation)
        self.mouse = {}
        for token, label in (("middle", "Middle"), ("mouse4", "Mouse 4"), ("mouse5", "Mouse 5")):
            field = QCheckBox(label)
            field.setChecked(frozenset({token}) in configured)
            self.mouse[token] = field
            general.addRow("Mouse activation:" if token == "middle" else "", field)
        for key, label, value in (("clipboard_hotkey", "Clipboard shortcut:", window.hotkey),
                                   ("search_hotkey", "Search shortcut:", window.search_hotkey),
                                   ("selection_hotkey", "Selection shortcut:", window.selection_hotkey)):
            preset = {"clipboard_hotkey": "Ctrl+Alt+L", "search_hotkey": "Ctrl+Alt+D", "selection_hotkey": "Ctrl+Alt+S"}[key]
            field = ShortcutEdit(value, window.settings.value(key + "_preset", preset))
            if key == "selection_hotkey":
                field.setEnabled(sys.platform == "win32")
            general.addRow(label, field)
            self.fields[key] = field
        check(general, "auto_clipboard", "Look up copied text:", False)
        check(general, "audio_enabled", "Pronunciation button:", False)
        check(general, "audio_autoplay", "Autoplay pronunciation:", False)
        selection = check(general, "selection_lookup", "Look up double-clicked text:", False)
        selection.setEnabled(sys.platform == "win32")
        check(general, "drag_lookup", "Look up dragged selections:", False).setEnabled(sys.platform == "win32")
        check(general, "auto_scan", "Enable Auto Scan:", config.auto_scan_mode)
        spin(general, "auto_scan_ms", "Scan interval (ms):", max(100, int(config.auto_scan_interval_seconds * 1000)), 100, 60000)

        appearance = tab("Popup Appearance")
        self.theme = QComboBox()
        self.theme.addItems(["Meikipop", *THEMES])
        self.theme.setCurrentText(window.settings.value("popup_theme", "Meikipop"))
        appearance.addRow("Preset:", self.theme)
        self.font = QFontComboBox()
        self.font.setWritingSystem(QFontDatabase.WritingSystem.Latin)
        self.font.setCurrentFont(window.browser.font())
        appearance.addRow("Font Family:", self.font)
        spin(appearance, "text_pixels", "Font Size (Definitions):", config.font_size_definitions, 8, 72)
        spin(appearance, "header_pixels", "Font Size (Header):", config.font_size_header, 8, 72)
        spin(appearance, "background_opacity", "Background Opacity:", config.background_opacity, 50, 255)
        self.colors = {}
        for key, label in (("color_background", "Background:"), ("color_foreground", "Foreground:"),
                           ("color_highlight_word", "Highlight Word:")):
            button = QPushButton(window.settings.value(key, getattr(config, key)))
            button.clicked.connect(lambda _, b=button: self.choose_color(b))
            self.colors[key] = button
            appearance.addRow(label, button)
        self.position = QComboBox()
        for label, value in (("Flip Both", "flip_both"), ("Flip Vertically", "flip_vertically"),
                             ("Flip Horizontally", "flip_horizontally"), ("Visual Novel Mode", "visual_novel_mode")):
            self.position.addItem(label, value)
        self.position.setCurrentIndex(self.position.findData(window.settings.value("popup_position_mode", config.popup_position_mode)))
        appearance.addRow("Position Mode:", self.position)
        spin(appearance, "max_width", "Maximum width:", 560, 240, 1200)
        spin(appearance, "max_height", "Maximum height:", 600, 160, 1200)
        check(appearance, "examples", "Show examples:", config.show_examples)
        self.theme.currentTextChanged.connect(self.apply_theme)

        data = tab("Dictionaries")
        from .rendering import dictionary_order
        self.order = QListWidget()
        self.order.addItems(dictionary_order(window.settings.value("dictionary_order")))
        self.order.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.order.setFixedHeight(90)
        self.order.setCurrentRow(0)
        data.addRow("Order:", self.order)
        arrows = QHBoxLayout()
        for label, step in (("Move up", -1), ("Move down", 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda _, delta=step: self.move_source(delta))
            arrows.addWidget(button)
        data.addRow(arrows)
        from meikipop.dictionary.turkish_wordnet import default_wordnet_path
        from meikipop.dictionary.turkish_wiktionary import default_wiktionary_path
        from meikipop.language.stanza_analyzer import default_model_dir
        from meikipop.ocr.turkish_paddle import model_root
        status = QLabel(window.setup_status or "\n".join((
            f"TDK: {'installed' if window.worker.dictionary.exists() else 'missing'}",
            f"Wiktionary: {'installed' if default_wiktionary_path().exists() else 'missing'}",
            f"Stanza: {'installed' if (Path(window.worker.model_dir or default_model_dir()) / 'tr').exists() else 'missing'}",
            f"KeNet: {'installed' if default_wordnet_path().exists() else 'missing'}",
            f"OCR: {'installed' if (model_root() / 'manifest.json').exists() else 'missing'}")))
        status.setWordWrap(True)
        status.setMaximumWidth(480)
        data.addRow(status)
        window.signals.setup_completed.connect(status.setText)
        window.signals.setup_progress.connect(status.setText)
        for key, label in (("dictionary", "Install / update TDK"), ("wiktionary", "Install / update Wiktionary"), ("wordnet", "Install / update KeNet"),
                           ("model", "Install Stanza models"), ("ocr", "Install OCR models")):
            button = QPushButton(label)
            button.setDisabled(window.setup_thread is not None)
            button.clicked.connect(lambda _, k=key: window.start_setup(k))
            window.signals.setup_busy.connect(button.setDisabled)
            row = QHBoxLayout()
            row.addWidget(button)
            rollback = QPushButton("Roll back")
            rollback.setDisabled(window.setup_thread is not None)
            rollback.clicked.connect(lambda _, k=key: window.start_setup("rollback:" + k))
            window.signals.setup_busy.connect(rollback.setDisabled)
            row.addWidget(rollback)
            data.addRow(row)
        data.addRow(QLabel("KeNet / StarlangSoftware · GPL-3.0\nTDK: ogun/guncel-turkce-sozluk v12"))
        credits = QLabel('<a href="https://github.com/yomidevs/wiktionary-to-yomitan">Wiktionary via wty / Kaikki</a>'
                         ' · <a href="https://en.wiktionary.org/wiki/Wiktionary:Copyrights">CC BY-SA / GFDL</a>')
        credits.setOpenExternalLinks(True)
        data.addRow(credits)
        if not window.worker.dictionary.exists():
            tabs.setCurrentIndex(tabs.count() - 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def move_source(self, delta):
        row = self.order.currentRow()
        target = row + delta
        if 0 <= row < self.order.count() and 0 <= target < self.order.count():
            self.order.insertItem(target, self.order.takeItem(row))
            self.order.setCurrentRow(target)

    def choose_color(self, button):
        color = QColorDialog.getColor(QColor(button.text()), self)
        if color.isValid():
            button.setText(color.name())
            self.theme.setCurrentText("Custom")

    def apply_theme(self, name):
        values = THEMES.get(name, {}) if name != "Meikipop" else {key: getattr(config, key) for key in self.colors}
        for key, button in self.colors.items():
            if key in values:
                button.setText(values[key])
        if "background_opacity" in values:
            self.fields["background_opacity"].setValue(values["background_opacity"])

    def save(self):
        bindings = [self.activation.currentText()] if self.activation.currentText() != "None" else []
        bindings.extend(token for token, field in self.mouse.items() if field.isChecked())
        try:
            bindings = serialise_activation_bindings(parse_activation_bindings(",".join(bindings)))
            self.window.input.set_shortcuts(self.fields["clipboard_hotkey"].text().strip(),
                                             self.fields["search_hotkey"].text().strip(),
                                             self.fields["selection_hotkey"].text().strip())
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Shortcut", str(error))
            return
        settings = self.window.settings
        settings.setValue("dictionary_order", [self.order.item(i).text() for i in range(self.order.count())])
        for key, field in self.fields.items():
            value = field.isChecked() if isinstance(field, QCheckBox) else field.value() if isinstance(field, QSpinBox) else field.text().strip()
            settings.setValue(key, value)
            if isinstance(field, ShortcutEdit):
                settings.setValue(key + "_preset", field.recorder.keySequence().toString())
        for key, button in self.colors.items():
            settings.setValue(key, button.text())
        settings.setValue("font_family", self.font.currentFont().family())
        settings.setValue("popup_theme", self.theme.currentText())
        settings.setValue("popup_position_mode", self.position.currentData())
        settings.setValue("activation_bindings", bindings)
        self.window.bindings = bindings
        self.window.input.activation.set_bindings(bindings)
        self.window.hotkey = settings.value("clipboard_hotkey")
        self.window.search_hotkey = settings.value("search_hotkey")
        self.window.selection_hotkey = settings.value("selection_hotkey")
        self.window.auto_action.setChecked(settings.value("auto_clipboard", False, bool))
        self.window.examples.setChecked(settings.value("examples", True, bool))
        self.window.prefetch_timer.setInterval(settings.value("auto_scan_ms", 500, int))
        self.window.apply_appearance()
        self.window.audio_button.setVisible(settings.value("audio_enabled", False, bool))
        self.window.render()
        self.accept()
