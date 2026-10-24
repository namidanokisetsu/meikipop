"""Shared popup bindings for Qt shortcuts and nonactivating Windows overlays."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence


POPUP_ACTIONS = (("replay", "Replay audio", "R"), ("anki", "Add to Anki", "Shift+A"),
                 ("copy", "Copy sentence", "Shift+C"), ("copy_text", "Copy text", "Ctrl+C"),
                 ("back", "Back", "Alt+Left"))


def shortcut_key(profile, action):
    return f"profiles/{profile}/" + ("anki/shortcut" if action == "anki" else f"popup/{action}_shortcut")


def popup_bindings(settings, profile):
    return {action: settings.value(shortcut_key(profile, action),
                                   QKeySequence(QKeySequence.StandardKey.Back).toString() if action == "back" else default)
            for action, _, default in POPUP_ACTIONS}


def native_chord(value):
    sequence = QKeySequence(value)
    if sequence.isEmpty():
        return None
    combination = sequence[0]
    key, flags = combination.key(), combination.keyboardModifiers()
    special = {Qt.Key.Key_Left: 0x25, Qt.Key.Key_Right: 0x27, Qt.Key.Key_Up: 0x26,
               Qt.Key.Key_Down: 0x28, Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22,
               Qt.Key.Key_Home: 0x24, Qt.Key.Key_End: 0x23, Qt.Key.Key_Space: 0x20,
               Qt.Key.Key_Return: 0x0D, Qt.Key.Key_Tab: 0x09, Qt.Key.Key_Delete: 0x2E,
               Qt.Key.Key_Backspace: 0x08, Qt.Key.Key_Insert: 0x2D}
    modifiers = sum(bit for flag, bit in ((Qt.KeyboardModifier.ShiftModifier, 1),
                    (Qt.KeyboardModifier.ControlModifier, 2), (Qt.KeyboardModifier.AltModifier, 4),
                    (Qt.KeyboardModifier.MetaModifier, 8)) if flags & flag)
    if key in special:
        return special[key], modifiers
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return 0x70 + int(key - Qt.Key.Key_F1), modifiers
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9 or Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return int(key), modifiers
    if 0x21 <= key <= 0xFFFF:
        import ctypes
        user32 = ctypes.WinDLL("user32")
        user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
        user32.VkKeyScanW.restype = ctypes.c_short
        code = user32.VkKeyScanW(chr(key))
        if code != -1:
            return code & 0xFF, modifiers | ((code >> 8) & 7)
    raise ValueError("Choose another key combination.")
