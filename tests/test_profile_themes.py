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
from meikipop.gui.profile_appearance import DEFAULTS, ProfileAppearance, load_appearance
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

    def test_presets_keep_text_and_metadata_readable(self):
        self.assertEqual(set(THEMES), {"Monochrome Dark", "Light", "Custom"})
        for name, theme in THEMES.items():
            if not theme:
                continue
            with self.subTest(theme=name):
                bg = theme['color_background']
                self.assertEqual(theme['background_opacity'], 255)
                self.assertGreaterEqual(contrast(bg, theme['color_foreground']), 7)
                for key in ('color_highlight_word', 'color_highlight_reading'):
                    self.assertGreaterEqual(contrast(bg, theme[key]), 4.5)
                for key in ('color_background', 'color_foreground', 'color_highlight_word', 'color_highlight_reading'):
                    red, green, blue, _ = QColor(theme[key]).getRgb()
                    self.assertEqual(red, green)
                    self.assertEqual(green, blue)
                if name == 'Monochrome Dark':
                    self.assertEqual(bg, '#000000')
                    self.assertGreaterEqual(contrast(bg, theme['color_foreground']), 20)
                    self.assertGreaterEqual(contrast(bg, theme['color_highlight_word']), 12)
                self.assertGreaterEqual(contrast(bg, surface_colors(bg, theme['color_foreground'])['muted']), 4.5)

    def test_headword_furigana_is_opt_in_and_only_shown_for_japanese(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            profile = ['ja']
            widget = ProfileAppearance(settings, lambda: profile[0], Mock())
            try:
                self.assertFalse(widget.headword_furigana.isChecked())
                self.assertFalse(widget.definition_furigana.isChecked())
                self.assertEqual(widget.controls['furigana_scale'].value(), 50)
                widget.controls['furigana_scale'].setValue(60)
                widget.headword_furigana.click()
                widget.definition_furigana.click()
                self.assertTrue(settings.value('profiles/ja/definition_furigana', False, bool))
                self.assertTrue(settings.value('profiles/ja/headword_furigana', False, bool))
                profile[0] = 'tr'
                widget.reload()
                self.assertFalse(widget.form.isRowVisible(widget.headword_furigana))
                self.assertFalse(widget.form.isRowVisible(widget.definition_furigana))
                self.assertFalse(widget.form.isRowVisible(widget.controls['furigana_scale']))
                widget.save()
                self.assertFalse(settings.contains('profiles/tr/headword_furigana'))
                self.assertFalse(settings.contains('profiles/tr/definition_furigana'))
                self.assertFalse(settings.contains('profiles/tr/furigana_scale'))
                profile[0] = 'ja'
                widget.reload()
                self.assertTrue(widget.headword_furigana.isChecked())
                self.assertTrue(widget.definition_furigana.isChecked())
                self.assertTrue(widget.form.isRowVisible(widget.headword_furigana))
                self.assertEqual(widget.controls['furigana_scale'].value(), 60)
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
                widget.theme.setCurrentText('Monochrome Dark')
                widget.theme.setCurrentText('Custom')
                self.assertEqual(widget.controls['color_background'].text(), '#102030')
                self.assertEqual(settings.value('profiles/tr/theme_name'), 'Dusk')
                widget.controls['scale'].setValue(120)
                self.assertEqual(settings.value('profiles/ja/scale', type=int), 120)
            finally:
                config.__dict__.update(previous)
                widget.deleteLater()

    def test_removed_preset_migrates_without_losing_saved_or_custom_colors(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            settings.setValue('profiles/tr/theme_name', 'Dusk')
            settings.setValue('profiles/tr/color_background', '#28231F')
            settings.setValue('profiles/tr/color_highlight_word', '#E4BD8B')
            settings.setValue('profiles/tr/custom/color_foreground', '#eeeeee')
            previous = dict(config.__dict__)
            try:
                load_appearance(settings, 'tr')
                self.assertEqual(config.theme_name, 'Monochrome Dark')
                self.assertEqual(config.color_highlight_word, '#FFFFFF')
                self.assertEqual(settings.value('profiles/tr/theme_name'), 'Monochrome Dark')
                widget = ProfileAppearance(settings, lambda: 'tr', Mock())
                widget.theme.setCurrentText('Light')
                widget.theme.setCurrentText('Custom')
                load_appearance(settings, 'tr')
                self.assertEqual(config.color_background, '#28231F')
                self.assertEqual(config.color_highlight_word, '#E4BD8B')
                self.assertEqual(config.color_foreground, '#eeeeee')
                widget.theme.setCurrentText('Monochrome Dark')
                widget.deleteLater()
                widget = ProfileAppearance(settings, lambda: 'tr', Mock())
                widget.theme.setCurrentText('Custom')
                self.assertEqual(widget.controls['color_background'].text(), '#28231F')
                widget.deleteLater()
                self.assertFalse(settings.contains('profiles/ja/theme_name'))
            finally:
                config.__dict__.update(previous)

    def test_new_custom_palette_starts_from_defaults_before_preset_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            widget = ProfileAppearance(settings, lambda: 'ja', Mock())
            try:
                widget.theme.setCurrentText('Light')
                widget.theme.setCurrentText('Custom')
                for key in THEMES['Monochrome Dark']:
                    self.assertEqual(settings.value('profiles/ja/custom/' + key), DEFAULTS[key])
            finally:
                widget.deleteLater()
