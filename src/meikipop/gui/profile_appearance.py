"""Live appearance controls and a saved custom palette per language profile."""
import sys
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFontComboBox, QFormLayout,
                            QPushButton, QSpinBox, QVBoxLayout, QWidget)
from meikipop.config.config import config
from meikipop.gui.themes import THEMES, theme_name
from meikipop.gui.settings_section import SettingsSection
from meikipop.gui.typography import default_family
from meikipop.gui.action_icons import POPUP_ACTIONS

KEYS = ("theme_name", "font_family", "font_size_header", "font_size_definitions", "font_size_sentence",
        "color_background", "color_foreground", "color_highlight_word", "color_highlight_reading",
        "background_opacity", "pitch_colors", "kanji_stroke_order")
DEFAULTS = {key: getattr(config, key) for key in KEYS}
_configured_font = DEFAULTS["font_family"]
DEFAULTS["furigana_scale"] = 50
DEFAULTS["font_family"] = DEFAULTS["font_family"] or ("Segoe UI" if sys.platform == "win32" else "Helvetica Neue" if sys.platform == "darwin" else "Noto Sans")


def custom_palette(settings, profile):
    prefix = f"profiles/{profile}/"
    palette = {}
    for key in THEMES["Dark"]:
        custom = prefix + "custom/" + key
        palette[key] = settings.value(custom, DEFAULTS[key], type=type(DEFAULTS[key]))
    return palette


def load_appearance(settings, profile):
    scale = settings.value(f"profiles/{profile}/scale", 100, type=int) / 100
    custom = custom_palette(settings, profile)
    name = theme_name(settings.value(f"profiles/{profile}/theme_name", DEFAULTS["theme_name"]))
    palette = custom if name == "Custom" else THEMES[name]
    for key, default in DEFAULTS.items():
        if key == "font_family" and not _configured_font:
            default = default_family(profile)
        if key in palette:
            value = palette[key]
        else:
            value = settings.value(f"profiles/{profile}/{key}", default, type=type(default))
        if key == "theme_name":
            value = name
        if key == "background_opacity":
            value = settings.value(f"profiles/{profile}/{key}", value, type=int)
        if key in ("pitch_colors", "kanji_stroke_order") and profile != "ja":
            value = False
        if key.startswith("font_size"):
            value = round(value * scale)
        setattr(config, key, value)


class ProfileAppearance(QWidget):
    def __init__(self, settings, profile, saved):
        super().__init__()
        self.settings, self.profile, self.saved = settings, profile, saved
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40)
        self._preview_timer.timeout.connect(self._apply_preview)
        self._loading = True
        layout = QVBoxLayout(self)
        general, preview, pinned, actions = QWidget(), QWidget(), QWidget(), QWidget()
        actions_form = QFormLayout(actions)
        self.action_controls = {}
        for name, label in POPUP_ACTIONS:
            control = QCheckBox(label)
            self.action_controls[name] = control
            actions_form.addRow(control)
        form = self.form = self.detail_form = QFormLayout(general)
        detail_form = form
        preview_form = self.preview_form = QFormLayout(preview)
        pinned_form = self.pinned_form = QFormLayout(pinned)
        self.theme = QComboBox()
        self.theme.addItems(THEMES)
        form.addRow("Theme", self.theme)
        self.compact_preview = QCheckBox("First dictionary only")
        self.compact_preview.setToolTip("First matching dictionary; pin to show all dictionaries")
        preview_form.addRow(self.compact_preview)
        self.preview_frequency = QCheckBox("Frequency")
        self.preview_pitch = QCheckBox("Pitch")
        self.preview_grammar = QCheckBox("Grammar labels")
        self.pinned_frequency = QCheckBox("Frequency")
        self.pinned_pitch = QCheckBox("Pitch")
        self.pinned_grammar = QCheckBox("Grammar labels")
        self.preview_definitions = QSpinBox()
        self.preview_definitions.setRange(0, 50)
        self.preview_definitions.setSpecialValueText("All")
        self.preview_definitions.setToolTip("Meanings shown in preview")
        preview_form.addRow(self.preview_frequency)
        preview_form.addRow(self.preview_pitch)
        preview_form.addRow(self.preview_grammar)
        preview_form.addRow("Definitions", self.preview_definitions)
        pinned_form.addRow(self.pinned_frequency)
        pinned_form.addRow(self.pinned_pitch)
        pinned_form.addRow(self.pinned_grammar)
        self.pinned_sentence = QCheckBox("Show sentence when pinned")
        pinned_form.addRow(self.pinned_sentence)
        self.snap_scrolling = QCheckBox("Snap scrolling")
        self.snap_scrolling.setToolTip("Scroll between dictionary sections")
        pinned_form.addRow(self.snap_scrolling)
        self.font = QFontComboBox()
        detail_form.addRow("Font", self.font)
        self.headword_furigana = QCheckBox("Headword furigana")
        detail_form.addRow(self.headword_furigana)
        self.definition_furigana = QCheckBox("Definition furigana")
        detail_form.addRow(self.definition_furigana)
        self.pitch_colors = QCheckBox("Pitch colors")
        detail_form.addRow(self.pitch_colors)
        self.kanji_stroke_order = QCheckBox("Stroke order in kanji")
        detail_form.addRow(self.kanji_stroke_order)
        self.font_install = QPushButton("Download stroke-order font")
        self.font_install.setFlat(True)
        detail_form.addRow(self.font_install)
        self.controls = {}
        for key, label, minimum, maximum in (
                ("font_size_header", "Word size", 10, 72),
                ("font_size_definitions", "Definition size", 10, 48),
                ("font_size_sentence", "Sentence size", 10, 48),
                ("furigana_scale", "Furigana size", 30, 100),
                ("scale", "Text scale", 70, 200), ("background_opacity", "Background opacity", 0, 100)):
            widget = QSpinBox()
            widget.setRange(minimum, maximum)
            if key in ("furigana_scale", "scale", "background_opacity"):
                widget.setSuffix("%")
            self.controls[key] = widget
            if key == "scale":
                widget.setToolTip("Scales word, definition and sentence sizes together")
            (form if key in ("scale", "background_opacity") else detail_form).addRow(label, widget)
        for key, label in (("color_background", "Background"), ("color_foreground", "Text"),
                           ("color_highlight_word", "Word"), ("color_highlight_reading", "Reading")):
            button = QPushButton()
            button.clicked.connect(lambda _, key=key: self.pick_color(key))
            self.controls[key] = button
            form.addRow(label, button)
        self.general_section = SettingsSection("General", general)
        self.preview_section = SettingsSection("Preview", preview)
        self.pinned_section = SettingsSection("Pinned", pinned)
        self.actions_section = SettingsSection("Buttons", actions)
        for section in (self.general_section, self.preview_section, self.pinned_section, self.actions_section):
            layout.addWidget(section)
        self.general_section.toggle.setChecked(True)
        layout.addStretch()
        self.reload()
        self.theme.currentTextChanged.connect(self.apply_theme)
        self.font.currentFontChanged.connect(self.save)
        self.headword_furigana.toggled.connect(self.save)
        self.definition_furigana.toggled.connect(self.save)
        self.pitch_colors.toggled.connect(self.save)
        self.kanji_stroke_order.toggled.connect(self.save)
        self.preview_frequency.toggled.connect(self.save)
        self.preview_pitch.toggled.connect(self.save)
        for control in (self.preview_grammar, self.pinned_frequency, self.pinned_pitch, self.pinned_grammar):
            control.toggled.connect(self.save)
        self.preview_definitions.valueChanged.connect(self.save)
        self.compact_preview.toggled.connect(self.save)
        self.pinned_sentence.toggled.connect(self.save)
        self.snap_scrolling.toggled.connect(self.save)
        for control in self.action_controls.values():
            control.toggled.connect(self.save)
        for key, widget in self.controls.items():
            if not key.startswith("color"):
                widget.valueChanged.connect(self.save)

    def _apply_preview(self):
        self.saved()

    def reload(self):
        self._loading = True
        prefix = f"profiles/{self.profile()}/"
        self.preview_frequency.setChecked(self.settings.value(prefix + "preview_frequency", True, bool))
        self.preview_pitch.setChecked(self.settings.value(prefix + "preview_pitch", True, bool))
        self.preview_grammar.setChecked(self.settings.value(prefix + "preview_grammar", False, bool))
        for name, control in self.action_controls.items():
            control.setChecked(self.settings.value(prefix + "buttons/" + name, True, bool))
        for name in ("pinned_frequency", "pinned_pitch", "pinned_grammar"):
            getattr(self, name).setChecked(self.settings.value(prefix + name, True, bool))
        self.preview_definitions.setValue(self.settings.value(prefix + "preview_definitions", 1, int))
        self.preview_form.setRowVisible(self.preview_pitch, self.profile() == "ja")
        self.pinned_form.setRowVisible(self.pinned_pitch, self.profile() == "ja")
        custom = custom_palette(self.settings, self.profile())
        self.theme.blockSignals(True)
        name = theme_name(self.settings.value(f"profiles/{self.profile()}/theme_name", DEFAULTS["theme_name"]))
        self.theme.setCurrentText(name)
        self.theme.blockSignals(False)
        self.compact_preview.setChecked(self.settings.value(f"profiles/{self.profile()}/compact_preview", True, bool))
        self.pinned_sentence.setChecked(self.settings.value(f"profiles/{self.profile()}/pinned_sentence", False, bool))
        self.snap_scrolling.setChecked(self.settings.value(f"profiles/{self.profile()}/snap_scrolling", False, bool))
        self.font.setCurrentFont(QFont(self.settings.value(f"profiles/{self.profile()}/font_family",
                                                         _configured_font or default_family(self.profile()))))
        self.headword_furigana.setChecked(self.settings.value("profiles/ja/headword_furigana", False, bool))
        self.detail_form.setRowVisible(self.headword_furigana, self.profile() == "ja")
        self.definition_furigana.setChecked(self.settings.value("profiles/ja/definition_furigana", True, bool))
        self.detail_form.setRowVisible(self.definition_furigana, self.profile() == "ja")
        self.pitch_colors.setChecked(self.settings.value("profiles/ja/pitch_colors", DEFAULTS["pitch_colors"], bool))
        self.detail_form.setRowVisible(self.pitch_colors, self.profile() == "ja")
        self.kanji_stroke_order.setChecked(self.settings.value("profiles/ja/kanji_stroke_order", DEFAULTS["kanji_stroke_order"], bool))
        self.detail_form.setRowVisible(self.kanji_stroke_order, self.profile() == "ja")
        from meikipop.utils.stroke_order_font import font_ready
        self.detail_form.setRowVisible(self.font_install, self.profile() == "ja" and not font_ready())
        self.detail_form.setRowVisible(self.controls["furigana_scale"], self.profile() == "ja")
        for key, widget in self.controls.items():
            value = self.settings.value(f"profiles/{self.profile()}/{key}", DEFAULTS.get(key, 100))
            value = (custom if name == "Custom" else THEMES[name]).get(key, value)
            if key == "background_opacity":
                value = round(self.settings.value(f"profiles/{self.profile()}/{key}", value, type=int) * 100 / 255)
            if key.startswith("color"):
                self.set_color(key, value)
            else:
                widget.setValue(int(value))
            if key.startswith("color"):
                self.form.setRowVisible(widget, name == "Custom")
        self._loading = False

    def set_color(self, key, color):
        self.controls[key].setText(color)
        self.controls[key].setStyleSheet(f"border:2px solid {color};padding:4px;")

    def pick_color(self, key):
        color = QColorDialog.getColor(QColor(self.controls[key].text()), self)
        if color.isValid():
            self.set_color(key, color.name())
            self.save()

    def apply_theme(self, name):
        self._loading = True
        palette = THEMES[name] if name != "Custom" else custom_palette(self.settings, self.profile())
        for key, value in palette.items():
            if key.startswith("color"):
                self.set_color(key, value)
        for key, widget in self.controls.items():
            if key.startswith("color"):
                self.form.setRowVisible(widget, name == "Custom")
        self._loading = False
        self.save()

    def save(self, *_):
        if self._loading:
            return
        prefix = f"profiles/{self.profile()}/"
        self.settings.setValue(prefix + "theme_name", self.theme.currentText())
        self.settings.setValue(prefix + "compact_preview", self.compact_preview.isChecked())
        self.settings.setValue(prefix + "preview_frequency", self.preview_frequency.isChecked())
        self.settings.setValue(prefix + "preview_pitch", self.preview_pitch.isChecked())
        for name, control in self.action_controls.items():
            self.settings.setValue(prefix + "buttons/" + name, control.isChecked())
        for name in ("preview_grammar", "pinned_frequency", "pinned_pitch", "pinned_grammar"):
            self.settings.setValue(prefix + name, getattr(self, name).isChecked())
        self.settings.setValue(prefix + "preview_definitions", self.preview_definitions.value())
        self.settings.setValue(prefix + "pinned_sentence", self.pinned_sentence.isChecked())
        self.settings.setValue(prefix + "snap_scrolling", self.snap_scrolling.isChecked())
        self.settings.setValue(prefix + "font_family", self.font.currentFont().family())
        if self.profile() == "ja":
            self.settings.setValue(prefix + "headword_furigana", self.headword_furigana.isChecked())
            self.settings.setValue(prefix + "definition_furigana", self.definition_furigana.isChecked())
            self.settings.setValue(prefix + "pitch_colors", self.pitch_colors.isChecked())
            self.settings.setValue(prefix + "kanji_stroke_order", self.kanji_stroke_order.isChecked())
        for key, widget in self.controls.items():
            if key == "furigana_scale" and self.profile() != "ja":
                continue
            value = widget.text() if key.startswith("color") else widget.value()
            if key == "background_opacity":
                value = round(value * 255 / 100)
            self.settings.setValue(prefix + key, value)
            if self.theme.currentText() == "Custom" and (key.startswith("color") or key == "background_opacity"):
                self.settings.setValue(prefix + "custom/" + key, value)
        if isinstance(self.sender(), QSpinBox):
            if not self._preview_timer.isActive():
                self._preview_timer.start()
        else:
            self._preview_timer.stop()
            self.saved()
