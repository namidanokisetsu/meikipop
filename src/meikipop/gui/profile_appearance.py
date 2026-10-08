"""Live appearance controls and a saved custom palette per language profile."""
import sys
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFontComboBox, QFormLayout,
                            QPushButton, QSpinBox, QVBoxLayout, QWidget)
from meikipop.config.config import config
from meikipop.gui.themes import THEMES, theme_name
from meikipop.gui.settings_section import SettingsSection

KEYS = ("theme_name", "font_family", "font_size_header", "font_size_definitions",
        "color_background", "color_foreground", "color_highlight_word", "color_highlight_reading",
        "background_opacity")
DEFAULTS = {key: getattr(config, key) for key in KEYS}
DEFAULTS["furigana_scale"] = 50
DEFAULTS["font_family"] = DEFAULTS["font_family"] or ("Segoe UI" if sys.platform == "win32" else "Helvetica Neue" if sys.platform == "darwin" else "Noto Sans")


def custom_palette(settings, profile):
    prefix = f"profiles/{profile}/"
    palette = {}
    for key in THEMES["Monochrome Dark"]:
        custom = prefix + "custom/" + key
        if not settings.contains(custom):
            # Seed before a preset can overwrite the user's saved colors.
            settings.setValue(custom, settings.value(prefix + key, DEFAULTS[key]))
        palette[key] = settings.value(custom, DEFAULTS[key], type=type(DEFAULTS[key]))
    return palette


def load_appearance(settings, profile):
    scale = settings.value(f"profiles/{profile}/scale", 100, type=int) / 100
    custom = custom_palette(settings, profile)
    name = theme_name(settings.value(f"profiles/{profile}/theme_name", DEFAULTS["theme_name"]))
    settings.setValue(f"profiles/{profile}/theme_name", name)
    palette = custom if name == "Custom" else THEMES[name]
    for key, default in DEFAULTS.items():
        if key in palette:
            value = palette[key]
        else:
            value = settings.value(f"profiles/{profile}/{key}", default, type=type(default))
        if key == "theme_name":
            value = name
        if key == "background_opacity":
            value = settings.value(f"profiles/{profile}/{key}", value, type=int)
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
        form = self.form = QFormLayout()
        layout.addLayout(form)
        details = QWidget()
        detail_form = self.detail_form = QFormLayout(details)
        self.theme = QComboBox()
        self.theme.addItems(THEMES)
        form.addRow("Theme", self.theme)
        self.compact_preview = QCheckBox("Compact preview")
        self.compact_preview.setToolTip("Pin to expand the full entry")
        form.addRow(self.compact_preview)
        self.pinned_sentence = QCheckBox("Show sentence when pinned")
        detail_form.addRow(self.pinned_sentence)
        self.snap_scrolling = QCheckBox("Snap scrolling")
        self.snap_scrolling.setToolTip("Scroll between dictionary sections")
        detail_form.addRow(self.snap_scrolling)
        self.font = QFontComboBox()
        detail_form.addRow("Font", self.font)
        self.headword_furigana = QCheckBox("Headword furigana")
        detail_form.addRow(self.headword_furigana)
        self.definition_furigana = QCheckBox("Definition furigana")
        detail_form.addRow(self.definition_furigana)
        self.controls = {}
        for key, label, minimum, maximum in (
                ("font_size_header", "Word size", 10, 72),
                ("font_size_definitions", "Definition size", 10, 48),
                ("furigana_scale", "Furigana size (%)", 30, 100),
                ("scale", "Text size (%)", 70, 200), ("background_opacity", "Background opacity", 0, 100)):
            widget = QSpinBox()
            widget.setRange(minimum, maximum)
            if key == "background_opacity":
                widget.setSuffix("%")
            self.controls[key] = widget
            (form if key in ("scale", "background_opacity") else detail_form).addRow(label, widget)
        for key, label in (("color_background", "Background"), ("color_foreground", "Text"),
                           ("color_highlight_word", "Word"), ("color_highlight_reading", "Reading")):
            button = QPushButton()
            button.clicked.connect(lambda _, key=key: self.pick_color(key))
            self.controls[key] = button
            form.addRow(label, button)
        self.details = SettingsSection("Customize", details)
        layout.addWidget(self.details)
        layout.addStretch()
        self.reload()
        self.theme.currentTextChanged.connect(self.apply_theme)
        self.font.currentFontChanged.connect(self.save)
        self.headword_furigana.toggled.connect(self.save)
        self.definition_furigana.toggled.connect(self.save)
        self.compact_preview.toggled.connect(self.save)
        self.pinned_sentence.toggled.connect(self.save)
        self.snap_scrolling.toggled.connect(self.save)
        for key, widget in self.controls.items():
            if not key.startswith("color"):
                widget.valueChanged.connect(self.save)

    def _apply_preview(self):
        self.saved()

    def reload(self):
        self._loading = True
        custom = custom_palette(self.settings, self.profile())
        self.theme.blockSignals(True)
        name = theme_name(self.settings.value(f"profiles/{self.profile()}/theme_name", DEFAULTS["theme_name"]))
        self.theme.setCurrentText(name)
        self.theme.blockSignals(False)
        self.compact_preview.setChecked(self.settings.value(f"profiles/{self.profile()}/compact_preview",
                                       self.settings.value("compact_preview", True, bool), bool))
        self.pinned_sentence.setChecked(self.settings.value(f"profiles/{self.profile()}/pinned_sentence", True, bool))
        self.snap_scrolling.setChecked(self.settings.value(f"profiles/{self.profile()}/snap_scrolling", False, bool))
        self.font.setCurrentFont(QFont(self.settings.value(f"profiles/{self.profile()}/font_family", DEFAULTS["font_family"])))
        self.headword_furigana.setChecked(self.settings.value("profiles/ja/headword_furigana", False, bool))
        self.detail_form.setRowVisible(self.headword_furigana, self.profile() == "ja")
        self.definition_furigana.setChecked(self.settings.value("profiles/ja/definition_furigana", True, bool))
        self.detail_form.setRowVisible(self.definition_furigana, self.profile() == "ja")
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
            elif key in self.controls:
                self.controls[key].setValue(round(value * 100 / 255) if key == "background_opacity" else int(value))
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
        self.settings.setValue(prefix + "pinned_sentence", self.pinned_sentence.isChecked())
        self.settings.setValue(prefix + "snap_scrolling", self.snap_scrolling.isChecked())
        self.settings.setValue(prefix + "font_family", self.font.currentFont().family())
        if self.profile() == "ja":
            self.settings.setValue(prefix + "headword_furigana", self.headword_furigana.isChecked())
            self.settings.setValue(prefix + "definition_furigana", self.definition_furigana.isChecked())
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
