"""Live appearance controls and a saved custom palette per language profile."""
import sys
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFontComboBox, QFormLayout,
                            QPushButton, QSpinBox, QWidget)
from meikipop.config.config import config
from meikipop.gui.themes import THEMES, theme_name

KEYS = ("theme_name", "font_family", "font_size_header", "font_size_definitions",
        "color_background", "color_foreground", "color_highlight_word", "color_highlight_reading",
        "background_opacity")
DEFAULTS = {key: getattr(config, key) for key in KEYS}
DEFAULTS["furigana_scale"] = 50
DEFAULTS["font_family"] = DEFAULTS["font_family"] or ("Segoe UI" if sys.platform == "win32" else "Helvetica Neue" if sys.platform == "darwin" else "Noto Sans")


def load_appearance(settings, profile):
    scale = settings.value(f"profiles/{profile}/scale", 100, type=int) / 100
    name = theme_name(settings.value(f"profiles/{profile}/theme_name", DEFAULTS["theme_name"]))
    for key, default in DEFAULTS.items():
        if key in THEMES.get(name, {}):
            value = THEMES[name][key]
        else:
            value = settings.value(f"profiles/{profile}/{key}", default, type=type(default))
        if key == "theme_name":
            value = name
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
        self._preview_timer.timeout.connect(self.saved)
        self._loading = True
        form = self.form = QFormLayout(self)
        self.theme = QComboBox()
        self.theme.addItems(THEMES)
        form.addRow("Theme", self.theme)
        self.compact_preview = QCheckBox("Compact preview")
        self.compact_preview.setToolTip("Pin to expand the full entry")
        form.addRow(self.compact_preview)
        self.font = QFontComboBox()
        form.addRow("Font", self.font)
        self.headword_furigana = QCheckBox("Furigana")
        form.addRow("Headword reading", self.headword_furigana)
        self.controls = {}
        for key, label, minimum, maximum in (
                ("font_size_header", "Word size", 10, 72),
                ("font_size_definitions", "Definition size", 10, 48),
                ("furigana_scale", "Furigana size (%)", 30, 100),
                ("scale", "Scale (%)", 70, 200), ("background_opacity", "Opacity", 80, 255)):
            widget = QSpinBox()
            widget.setRange(minimum, maximum)
            self.controls[key] = widget
            form.addRow(label, widget)
        for key, label in (("color_background", "Background"), ("color_foreground", "Text"),
                           ("color_highlight_word", "Word"), ("color_highlight_reading", "Reading")):
            button = QPushButton()
            button.clicked.connect(lambda _, key=key: self.pick_color(key))
            self.controls[key] = button
            form.addRow(label, button)
        self.reload()
        self.theme.currentTextChanged.connect(self.apply_theme)
        self.font.currentFontChanged.connect(self.save)
        self.headword_furigana.toggled.connect(self.save)
        self.compact_preview.toggled.connect(self.save)
        for key, widget in self.controls.items():
            if not key.startswith("color"):
                widget.valueChanged.connect(self.save)

    def reload(self):
        self._loading = True
        self.theme.blockSignals(True)
        name = theme_name(self.settings.value(f"profiles/{self.profile()}/theme_name", DEFAULTS["theme_name"]))
        self.theme.setCurrentText(name)
        self.theme.blockSignals(False)
        self.compact_preview.setChecked(self.settings.value(f"profiles/{self.profile()}/compact_preview",
                                       self.settings.value("compact_preview", True, bool), bool))
        self.font.setCurrentFont(QFont(self.settings.value(f"profiles/{self.profile()}/font_family", DEFAULTS["font_family"])))
        self.headword_furigana.setChecked(self.settings.value("profiles/ja/headword_furigana", False, bool))
        self.form.setRowVisible(self.headword_furigana, self.profile() == "ja")
        self.form.setRowVisible(self.controls["furigana_scale"], self.profile() == "ja")
        for key, widget in self.controls.items():
            value = self.settings.value(f"profiles/{self.profile()}/{key}", DEFAULTS.get(key, 100))
            value = THEMES.get(name, {}).get(key, value)
            if key.startswith("color"):
                self.set_color(key, value)
            else:
                widget.setValue(int(value))
            if key.startswith("color") or key == "background_opacity":
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
        palette = THEMES[name] if name != "Custom" else {
            key: self.settings.value(f"profiles/{self.profile()}/custom/{key}",
                                     widget.text() if key.startswith("color") else widget.value())
            for key, widget in self.controls.items() if key.startswith("color") or key == "background_opacity"}
        for key, value in palette.items():
            if key.startswith("color"):
                self.set_color(key, value)
            elif key in self.controls:
                self.controls[key].setValue(int(value))
        for key, widget in self.controls.items():
            if key.startswith("color") or key == "background_opacity":
                self.form.setRowVisible(widget, name == "Custom")
        self._loading = False
        self.save()

    def save(self, *_):
        if self._loading:
            return
        prefix = f"profiles/{self.profile()}/"
        self.settings.setValue(prefix + "theme_name", self.theme.currentText())
        self.settings.setValue(prefix + "compact_preview", self.compact_preview.isChecked())
        self.settings.setValue(prefix + "font_family", self.font.currentFont().family())
        if self.profile() == "ja":
            self.settings.setValue(prefix + "headword_furigana", self.headword_furigana.isChecked())
        for key, widget in self.controls.items():
            if key == "furigana_scale" and self.profile() != "ja":
                continue
            value = widget.text() if key.startswith("color") else widget.value()
            self.settings.setValue(prefix + key, value)
            if self.theme.currentText() == "Custom" and (key.startswith("color") or key == "background_opacity"):
                self.settings.setValue(prefix + "custom/" + key, value)
        if isinstance(self.sender(), QSpinBox):
            if not self._preview_timer.isActive():
                self._preview_timer.start()
        else:
            self._preview_timer.stop()
            self.saved()
