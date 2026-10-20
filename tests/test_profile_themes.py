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
from meikipop.gui.themes import THEMES, theme_name


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

    def test_percentage_opacity_applies_to_presets_and_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            settings.setValue('profiles/ja/theme_name', 'Green')
            widget = ProfileAppearance(settings, lambda: 'ja', lambda: load_appearance(settings, 'ja'))
            try:
                self.assertEqual(widget.controls['background_opacity'].value(), 90)
                self.assertEqual(widget.controls['background_opacity'].suffix(), '%')
                self.assertFalse(widget.form.isRowVisible(widget.controls['color_background']))
                self.assertTrue(widget.form.isRowVisible(widget.controls['background_opacity']))
                widget.controls['background_opacity'].setValue(50)
                load_appearance(settings, 'ja')
                self.assertEqual(config.background_opacity, 128)
                widget.reload()
                self.assertEqual(widget.controls['background_opacity'].value(), 50)
                self.assertEqual(widget.theme.currentText(), 'Green')
            finally:
                widget.deleteLater()

    def test_presets_keep_text_and_metadata_readable(self):
        self.assertEqual(set(THEMES), {"Green", "Dark", "Light", "Custom"})
        for name, theme in THEMES.items():
            if not theme:
                continue
            with self.subTest(theme=name):
                bg = theme['color_background']
                self.assertEqual(theme['background_opacity'], 230)
                self.assertGreaterEqual(contrast(bg, theme['color_foreground']), 7)
                for key in ('color_highlight_word', 'color_highlight_reading'):
                    self.assertGreaterEqual(contrast(bg, theme[key]), 4.5)
                for key in ('color_background', 'color_foreground', 'color_highlight_word', 'color_highlight_reading'):
                    red, green, blue, _ = QColor(theme[key]).getRgb()
                    if name != 'Green':
                        self.assertEqual(red, green)
                        self.assertEqual(green, blue)
                if name == 'Dark':
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
                self.assertTrue(widget.definition_furigana.isChecked())
                self.assertEqual(widget.controls['furigana_scale'].value(), 50)
                widget.controls['furigana_scale'].setValue(60)
                widget.headword_furigana.click()
                self.assertTrue(settings.value('profiles/ja/definition_furigana', False, bool))
                self.assertTrue(settings.value('profiles/ja/headword_furigana', False, bool))
                profile[0] = 'tr'
                widget.reload()
                self.assertFalse(widget.detail_form.isRowVisible(widget.headword_furigana))
                self.assertFalse(widget.detail_form.isRowVisible(widget.definition_furigana))
                self.assertFalse(widget.detail_form.isRowVisible(widget.controls['furigana_scale']))
                widget.save()
                self.assertFalse(settings.contains('profiles/tr/headword_furigana'))
                self.assertFalse(settings.contains('profiles/tr/definition_furigana'))
                self.assertFalse(settings.contains('profiles/tr/furigana_scale'))
                profile[0] = 'ja'
                widget.reload()
                self.assertTrue(widget.headword_furigana.isChecked())
                self.assertTrue(widget.definition_furigana.isChecked())
                self.assertTrue(widget.detail_form.isRowVisible(widget.headword_furigana))
                self.assertEqual(widget.controls['furigana_scale'].value(), 60)
            finally:
                widget.deleteLater()

    def test_explicit_definition_reading_preference_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            settings.setValue('profiles/ja/definition_furigana', False)
            widget = ProfileAppearance(settings, lambda: 'ja', Mock())
            try:
                self.assertFalse(widget.definition_furigana.isChecked())
                widget.save()
                self.assertFalse(settings.value('profiles/ja/definition_furigana', True, bool))
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
                widget.theme.setCurrentText('Dark')
                widget.theme.setCurrentText('Custom')
                self.assertEqual(widget.controls['color_background'].text(), '#102030')
                self.assertEqual(settings.value('profiles/tr/theme_name'), 'Dusk')
                widget.controls['scale'].setValue(120)
                self.assertEqual(settings.value('profiles/ja/scale', type=int), 120)
            finally:
                config.__dict__.update(previous)
                widget.deleteLater()

    def test_unknown_preset_uses_defaults_without_migrating_saved_colors(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            settings.setValue('profiles/tr/theme_name', 'Dusk')
            settings.setValue('profiles/tr/color_background', '#28231F')
            settings.setValue('profiles/tr/color_highlight_word', '#E4BD8B')
            settings.setValue('profiles/tr/custom/color_foreground', '#eeeeee')
            previous = dict(config.__dict__)
            try:
                load_appearance(settings, 'tr')
                self.assertEqual(config.theme_name, 'Dark')
                self.assertEqual(config.color_highlight_word, '#FFFFFF')
                self.assertEqual(settings.value('profiles/tr/theme_name'), 'Dusk')
                widget = ProfileAppearance(settings, lambda: 'tr', Mock())
                widget.theme.setCurrentText('Light')
                widget.theme.setCurrentText('Custom')
                load_appearance(settings, 'tr')
                self.assertEqual(config.color_background, DEFAULTS['color_background'])
                self.assertEqual(config.color_highlight_word, DEFAULTS['color_highlight_word'])
                self.assertEqual(config.color_foreground, '#eeeeee')
                widget.theme.setCurrentText('Dark')
                widget.deleteLater()
                widget = ProfileAppearance(settings, lambda: 'tr', Mock())
                widget.theme.setCurrentText('Custom')
                self.assertEqual(widget.controls['color_background'].text(), DEFAULTS['color_background'])
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
                for key in THEMES['Dark']:
                    self.assertEqual(settings.value('profiles/ja/custom/' + key), DEFAULTS[key])
            finally:
                widget.deleteLater()

    def test_default_dark_and_legacy_name_keep_saved_opacity(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            previous = dict(config.__dict__)
            widget = ProfileAppearance(settings, lambda: 'ja', Mock())
            try:
                self.assertEqual(widget.theme.currentText(), 'Dark')
                self.assertEqual(widget.controls['background_opacity'].value(), 90)
                self.assertEqual(widget.preview_definitions.value(), 3)
                self.assertFalse(widget.pinned_sentence.isChecked())
                self.assertFalse(widget.snap_scrolling.isChecked())
                self.assertEqual([section.toggle.text() for section in
                                  (widget.general_section, widget.preview_section, widget.pinned_section)],
                                 ['General', 'Preview', 'Pinned'])
                widget.preview_grammar.setChecked(True)
                widget.pinned_grammar.setChecked(False)
                widget.pinned_frequency.setChecked(False)
                widget.reload()
                self.assertTrue(widget.preview_grammar.isChecked())
                self.assertFalse(widget.pinned_grammar.isChecked())
                self.assertFalse(widget.pinned_frequency.isChecked())
                for key in ('background_opacity', 'scale', 'furigana_scale'):
                    self.assertEqual(widget.controls[key].suffix(), '%')
                self.assertEqual(theme_name('Monochrome Dark'), 'Dark')
                settings.setValue('profiles/ja/theme_name', 'Monochrome Dark')
                settings.setValue('profiles/ja/background_opacity', 128)
                widget.reload()
                load_appearance(settings, 'ja')
                self.assertEqual(widget.theme.currentText(), 'Dark')
                self.assertEqual(config.theme_name, 'Dark')
                self.assertEqual(config.background_opacity, 128)
                self.assertEqual(settings.value('profiles/ja/theme_name'), 'Monochrome Dark')
                self.assertNotIn('Monochrome Dark', [widget.theme.itemText(i) for i in range(widget.theme.count())])
            finally:
                config.__dict__.update(previous)
                widget.deleteLater()

    def test_pitch_colors_default_on_and_persist_only_for_japanese(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.ini')
            settings = QSettings(path, QSettings.Format.IniFormat)
            profile = ['ja']
            previous = dict(config.__dict__)
            widget = ProfileAppearance(settings, lambda: profile[0], lambda: load_appearance(settings, profile[0]))
            try:
                self.assertTrue(widget.pitch_colors.isChecked())
                self.assertTrue(widget.detail_form.isRowVisible(widget.pitch_colors))
                load_appearance(settings, 'ja')
                self.assertTrue(config.pitch_colors)
                widget.pitch_colors.click()
                self.assertFalse(config.pitch_colors)
                settings.sync()
                self.assertFalse(QSettings(path, QSettings.Format.IniFormat).value('profiles/ja/pitch_colors', True, bool))
                profile[0] = 'tr'
                widget.reload()
                self.assertFalse(widget.detail_form.isRowVisible(widget.pitch_colors))
                widget.save()
                self.assertFalse(config.pitch_colors)
                self.assertFalse(settings.contains('profiles/tr/pitch_colors'))
                profile[0] = 'ja'
                widget.reload()
                self.assertFalse(widget.pitch_colors.isChecked())
                widget.pitch_colors.click()
                self.assertTrue(config.pitch_colors)
                load_appearance(settings, 'tr')
                self.assertFalse(config.pitch_colors)
                load_appearance(settings, 'ja')
                self.assertTrue(config.pitch_colors)
            finally:
                config.__dict__.update(previous)
                widget.deleteLater()

    def test_stroke_order_preference_is_optional_and_isolated_from_turkish(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'settings.ini'), QSettings.Format.IniFormat)
            profile = ['ja']
            previous = dict(config.__dict__)
            widget = ProfileAppearance(settings, lambda: profile[0], lambda: load_appearance(settings, profile[0]))
            try:
                self.assertTrue(widget.kanji_stroke_order.isChecked())
                widget.kanji_stroke_order.click()
                self.assertFalse(config.kanji_stroke_order)
                profile[0] = 'tr'
                widget.reload(); widget.save()
                self.assertFalse(widget.detail_form.isRowVisible(widget.kanji_stroke_order))
                self.assertFalse(settings.contains('profiles/tr/kanji_stroke_order'))
                profile[0] = 'ja'
                widget.reload()
                self.assertFalse(widget.kanji_stroke_order.isChecked())
                widget.kanji_stroke_order.click()
                self.assertTrue(config.kanji_stroke_order)
                load_appearance(settings, 'tr')
                self.assertFalse(config.kanji_stroke_order)
            finally:
                config.__dict__.update(previous)
                widget.deleteLater()
