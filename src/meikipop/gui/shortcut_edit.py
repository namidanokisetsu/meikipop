"""Record one key combination while keeping enablement independent."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QCheckBox, QKeySequenceEdit


class ShortcutEdit(QWidget):
    def __init__(self, value="", preset="Ctrl+Alt+L"):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox()
        self.enabled.setToolTip("Enable shortcut")
        self.enabled.setChecked(bool(value))
        layout.addWidget(self.enabled)
        aliases = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Meta",
                   "esc": "Esc", "page_up": "PgUp", "page_down": "PgDown"}
        display = "+".join(aliases.get(k.strip("<>"), k.strip("<>").title()) for k in value.split("+")) if value else preset
        self.recorder = QKeySequenceEdit(QKeySequence(display))
        self.recorder.setMaximumSequenceLength(1)
        self.recorder.setToolTip("Click and press your shortcut")
        layout.addWidget(self.recorder)

    def binding(self):
        sequence = self.recorder.keySequence()
        if sequence.isEmpty():
            raise ValueError("Record a shortcut first.")
        combination = sequence[0]
        modifiers = combination.keyboardModifiers()
        parts = [name for flag, name in ((Qt.KeyboardModifier.ControlModifier, "<ctrl>"),
                 (Qt.KeyboardModifier.AltModifier, "<alt>"), (Qt.KeyboardModifier.ShiftModifier, "<shift>"),
                 (Qt.KeyboardModifier.MetaModifier, "<cmd>")) if modifiers & flag]
        key = int(combination.key())
        special = {Qt.Key.Key_Escape: "esc", Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
                   Qt.Key.Key_Space: "space", Qt.Key.Key_Tab: "tab", Qt.Key.Key_Backspace: "backspace",
                   Qt.Key.Key_Delete: "delete", Qt.Key.Key_Insert: "insert", Qt.Key.Key_Home: "home",
                   Qt.Key.Key_End: "end", Qt.Key.Key_PageUp: "page_up", Qt.Key.Key_PageDown: "page_down",
                   Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down"}
        if key in special:
            parts.append("<" + special[key] + ">")
        elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F20:
            parts.append(f"<f{key - Qt.Key.Key_F1 + 1}>")
        elif 0x21 <= key <= 0x10ffff:
            parts.append(chr(key).lower())
        else:
            raise ValueError("Choose another key combination.")
        return "+".join(parts)

    def text(self):
        return self.binding() if self.enabled.isChecked() else ""
