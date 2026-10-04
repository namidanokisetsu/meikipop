"""Appearance controls shared with legacy themes, stored per language profile."""
import sys
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QFontComboBox, QFormLayout,
                            QLineEdit, QPushButton, QSpinBox, QWidget)
from meikipop.config.config import config
from meikipop.gui.themes import THEMES

KEYS = ("theme_name", "font_family", "font_size_header", "font_size_definitions",
        "color_background", "color_foreground", "color_highlight_word", "color_highlight_reading",
        "background_opacity")
DEFAULTS = {key: getattr(config, key) for key in KEYS}
DEFAULTS["font_family"] = DEFAULTS["font_family"] or ("Segoe UI" if sys.platform == "win32" else "Helvetica Neue" if sys.platform == "darwin" else "Noto Sans")


def load_appearance(settings, profile):
    scale = settings.value(f"profiles/{profile}/scale", 100, type=int) / 100
    for key, default in DEFAULTS.items():
        value = settings.value(f"profiles/{profile}/{key}", default, type=type(default))
        if key.startswith("font_size"):
            value = round(value * scale)
        setattr(config, key, value)


class ProfileAppearance(QWidget):
    def __init__(self, settings, profile, saved):
        super().__init__()
        self.settings, self.profile, self.saved = settings, profile, saved
        form = QFormLayout(self)
        self.theme = QComboBox()
        self.theme.addItems(THEMES)
        form.addRow("Theme", self.theme)
        self.font = QFontComboBox()
        form.addRow("Font", self.font)
        self.controls = {}
        for key, label, minimum, maximum in (
                ("font_size_header", "Word size", 10, 72),
                ("font_size_definitions", "Definition size", 10, 48),
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
        apply = QPushButton("Apply")
        apply.clicked.connect(self.save)
        form.addRow(apply)
        self.reload()
        self.theme.currentTextChanged.connect(self.apply_theme)

    def reload(self):
        self.theme.blockSignals(True)
        self.theme.setCurrentText(self.settings.value(f"profiles/{self.profile()}/theme_name", DEFAULTS["theme_name"]))
        self.theme.blockSignals(False)
        self.font.setCurrentFont(QFont(self.settings.value(f"profiles/{self.profile()}/font_family", DEFAULTS["font_family"])))
        for key, widget in self.controls.items():
            value = self.settings.value(f"profiles/{self.profile()}/{key}", DEFAULTS.get(key, 100))
            if key.startswith("color"):
                self.set_color(key, value)
            else:
                widget.setValue(int(value))

    def set_color(self, key, color):
        self.controls[key].setText(color)
        self.controls[key].setStyleSheet(f"border:2px solid {color};padding:4px;")

    def pick_color(self, key):
        color = QColorDialog.getColor(QColor(self.controls[key].text()), self)
        if color.isValid():
            self.theme.setCurrentText("Custom")
            self.set_color(key, color.name())

    def apply_theme(self, name):
        for key, value in THEMES[name].items():
            if key.startswith("color"):
                self.set_color(key, value)
            elif key in self.controls:
                self.controls[key].setValue(value)

    def save(self):
        prefix = f"profiles/{self.profile()}/"
        self.settings.setValue(prefix + "theme_name", self.theme.currentText())
        self.settings.setValue(prefix + "font_family", self.font.currentFont().family())
        for key, widget in self.controls.items():
            self.settings.setValue(prefix + key, widget.text() if key.startswith("color") else widget.value())
        self.saved()
