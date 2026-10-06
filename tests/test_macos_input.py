import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pynput import keyboard

from meikipop.gui.keyboard_listener import KeyboardListener
from meikipop.gui.shortcut_edit import ShortcutEdit
from meikipop.gui.text_shortcuts import TextHotKeys
from meikipop.utils.macos import require_input_monitoring_permission


class ShortcutRecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_recorded_command_and_control_roundtrip_without_changing_saved_binding(self):
        for platform, physical, sequence in (("darwin", "cmd", "Ctrl"), ("darwin", "ctrl", "Meta"),
                                              ("win32", "ctrl", "Ctrl"), ("win32", "cmd", "Meta")):
            with self.subTest(platform=platform, physical=physical), patch("meikipop.gui.shortcut_edit.sys.platform", platform):
                field = ShortcutEdit(f"<{physical}>+<shift>+d")
                self.assertEqual(field.recorder.keySequence(), QKeySequence(sequence + "+Shift+D"))
                self.assertEqual(set(field.binding().split("+")), {f"<{physical}>", "<shift>", "d"})
                field.deleteLater()

    def test_key_recording_persists_and_disable_preserves_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            field = ShortcutEdit("<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d")
            field.show()
            field.recorder.setFocus()
            QTest.keyClick(field.recorder, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            expected = {"<cmd>" if sys.platform == "darwin" else "<ctrl>", "<shift>", "k"}
            self.assertEqual(set(field.binding().split("+")), expected)
            settings.setValue("hotkey", field.text()); settings.sync()
            reloaded = QSettings(settings.fileName(), QSettings.Format.IniFormat)
            restored = ShortcutEdit(reloaded.value("hotkey"))
            self.assertEqual(restored.text(), field.text())
            field.enabled.setChecked(False)
            self.assertEqual(field.text(), "")
            field.enabled.setChecked(True)
            self.assertEqual(field.text(), restored.text())
            field.close(); field.deleteLater(); restored.deleteLater()


class InputPermissionTests(unittest.TestCase):
    def test_denied_permission_keeps_configured_shortcut_for_next_launch(self):
        from types import SimpleNamespace
        from meikipop.gui.quick_lookup import QuickLookupWindow
        from meikipop.utils.macos import InputMonitoringPermissionError
        settings = Mock()
        window = SimpleNamespace(settings=settings, _keys=None, hotkey_requested=Mock(), show_message=Mock())
        with patch("meikipop.gui.text_shortcuts.TextHotKeys") as listener:
            listener.return_value.start.side_effect = InputMonitoringPermissionError("Input Monitoring denied")
            warning = QuickLookupWindow.apply_shortcut(window, "<cmd>+d", "Ctrl+D")
        self.assertEqual(warning, "Input Monitoring denied")
        settings.setValue.assert_any_call("hotkey", "<cmd>+d")
        settings.setValue.assert_any_call("hotkey_preset", "Ctrl+D")
        self.assertIsNone(window._keys)

    def test_denied_monitoring_is_actionable_and_never_starts_thread(self):
        modules = {"Quartz": Mock(CGPreflightListenEventAccess=Mock(return_value=False))}
        with patch("sys.platform", "darwin"), patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "Input Monitoring"):
                require_input_monitoring_permission()
            with patch("threading.Thread.start") as start:
                with self.assertRaises(RuntimeError):
                    TextHotKeys({"<cmd>+d": Mock()}).start()
            start.assert_not_called()

    def test_other_platforms_do_not_call_macos_permission_api(self):
        with patch("sys.platform", "win32"), patch.dict(sys.modules, {"Quartz": None}):
            require_input_monitoring_permission()


@unittest.skipUnless(sys.platform == "darwin", "macOS event tap")
class MacListenerTests(unittest.TestCase):
    def test_permission_symbol_is_resolved_before_listener_thread_starts(self):
        from pynput._util.darwin import HIServices
        events = []
        listener = KeyboardListener()
        with patch("meikipop.utils.macos.require_input_monitoring_permission"), \
                patch.object(HIServices, "AXIsProcessTrusted", side_effect=lambda: events.append("resolve")), \
                patch.object(keyboard.Listener, "start", side_effect=lambda: events.append("start")):
            listener.start()
        self.assertEqual(events, ["resolve", "start"])

    def test_all_keyboard_listeners_bypass_carbon_layout_context(self):
        for factory in (lambda: KeyboardListener(), lambda: TextHotKeys({"<cmd>+d": Mock()})):
            listener = factory()
            with patch("pynput.keyboard._darwin.keycode_context", side_effect=AssertionError("Carbon on worker")), \
                    patch("pynput._util.darwin.ListenerMixin._run") as run:
                listener._run()
            run.assert_called_once_with(listener)

    def test_latin_shortcut_activates_with_russian_event_and_releases_cleanly(self):
        activated = Mock()
        listener = TextHotKeys({"<cmd>+<shift>+d": activated})
        chord = (keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char("в", vk=2))
        for _ in range(2):
            for key in chord: listener._on_press(key)
            for key in reversed(chord): listener._on_release(key)
        self.assertEqual(activated.call_count, 2)

    def test_unicode_injection_does_not_turn_character_into_dummy_virtual_key(self):
        activated = Mock()
        listener = TextHotKeys({"<cmd>+<shift>+k": activated})
        for key in (keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char("k", vk=0)):
            listener._on_press(key, injected=True)
        activated.assert_called_once_with()

    def test_native_listener_can_be_replaced_after_qt_starts(self):
        from Quartz import CGPreflightListenEventAccess
        if not CGPreflightListenEventAccess():
            self.skipTest("Input Monitoring is not granted to this test process")
        code = '''
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QWidget
from meikipop.gui.text_shortcuts import TextHotKeys
app = QApplication([])
window = QWidget(); window.show()
def replace():
    for _ in range(3):
        listener = TextHotKeys({'<cmd>+<shift>+d': lambda: None})
        listener.start(); listener.wait(); listener.stop(); listener.join(2)
        assert not listener.is_alive()
    app.quit()
QTimer.singleShot(100, replace)
app.exec()
'''
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
