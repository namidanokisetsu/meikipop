import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication
from meikipop.config.config import config
from meikipop.gui.profile_appearance import ProfileAppearance, load_appearance
from meikipop.gui.popup_style import surface_colors
from meikipop.gui.themes import THEMES


def luminance(color):
    rgb = QColor(color).getRgbF()[:3]
    channels = [c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in rgb]
    return sum(c*w for c, w in zip(channels, (.2126, .7152, .0722)))


def contrast(a, b):
    values = sorted((luminance(a), luminance(b)))
    return (values[1]+.05)/(values[0]+.05)


class ProfileThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_four_presets_keep_text_and_metadata_readable(self):
        self.assertEqual(set(THEMES), {"Charcoal", "Slate", "Dusk", "Light", "Custom"})
        for name, theme in THEMES.items():
            if not theme:
                continue
            with self.subTest(theme=name):
                bg = theme['color_background']
                self.assertEqual(theme['background_opacity'], 255)
                self.assertGreaterEqual(contrast(bg, theme['color_foreground']), 7)
                for key in ('color_highlight_word', 'color_highlight_reading'):
                    self.assertGreaterEqual(contrast(bg, theme[key]), 4.5)
                self.assertGreaterEqual(contrast(bg, surface_colors(bg, theme['color_foreground'])['muted']), 4.5)

    def test_headword_furigana_is_opt_in_and_only_shown_for_japanese(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            profile = ['ja']
            widget = ProfileAppearance(settings, lambda: profile[0], Mock())
            try:
                self.assertFalse(widget.headword_furigana.isChecked())
                widget.headword_furigana.click()
                self.assertTrue(settings.value('profiles/ja/headword_furigana', False, bool))
                profile[0] = 'tr'
                widget.reload()
                self.assertFalse(widget.form.isRowVisible(widget.headword_furigana))
                widget.save()
                self.assertFalse(settings.contains('profiles/tr/headword_furigana'))
                profile[0] = 'ja'
                widget.reload()
                self.assertTrue(widget.headword_furigana.isChecked())
                self.assertTrue(widget.form.isRowVisible(widget.headword_furigana))
            finally:
                widget.deleteLater()

    def test_live_theme_changes_preserve_custom_palette_and_other_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder)/'settings.ini'), QSettings.Format.IniFormat)
            settings.setValue('profiles/tr/theme_name', 'Dusk')
            widget = ProfileAppearance(settings, lambda: 'ja', Mock())
            previous = dict(config.__dict__)
            try:
                widget.theme.setCurrentText('Light')
                self.assertEqual(settings.value('profiles/ja/theme_name'), 'Light')
                load_appearance(settings, 'ja')
                self.assertEqual(config.color_background, '#FFFFFF')
                widget.theme.setCurrentText('Custom')
                widget.set_color('color_background', '#102030')
                widget.save()
                widget.theme.setCurrentText('Slate')
                widget.theme.setCurrentText('Custom')
                self.assertEqual(widget.controls['color_background'].text(), '#102030')
                self.assertEqual(settings.value('profiles/tr/theme_name'), 'Dusk')
                widget.controls['scale'].setValue(120)
                self.assertEqual(settings.value('profiles/ja/scale', type=int), 120)
            finally:
                config.__dict__.update(previous)
                widget.deleteLater()
