"""Keep macOS input listeners out of Carbon's main-thread-only layout API."""
import sys

from pynput import keyboard


class MacListenerMixin:
    def _run(self):
        if sys.platform == "darwin":
            from pynput._util.darwin import ListenerMixin
            # pynput 1.8.2 reads characters from Quartz events. Its unused
            # keycode_context still calls TISGetInputSourceProperty off-thread.
            return ListenerMixin._run(self)
        return super()._run()

    def start(self):
        from meikipop.utils.macos import require_input_monitoring_permission
        require_input_monitoring_permission()
        return super().start()

    def canonical(self, key):
        if sys.platform == "darwin":
            from pynput._util.darwin_vks import SYMBOLS
            char = SYMBOLS.get(getattr(key, "vk", None), "")
            if len(char) == 1 and char.isascii() and char.isalpha():
                return keyboard.KeyCode.from_char(char.lower())
        return super().canonical(key)


class KeyboardListener(MacListenerMixin, keyboard.Listener):
    pass
