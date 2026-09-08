"""Optional pronunciation through an installed Turkish system voice."""
from PyQt6.QtCore import QObject, QLocale


class TurkishSpeech(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = None

    def speak(self, text):
        if self.engine is None:
            from PyQt6.QtTextToSpeech import QTextToSpeech
            self.engine = QTextToSpeech(self)
            voice = next((v for v in self.engine.availableVoices()
                          if v.locale().language() == QLocale.Language.Turkish), None)
            if voice is None:
                self.engine.deleteLater()
                self.engine = None
                return False
            self.engine.setVoice(voice)
        self.engine.stop()
        self.engine.say(text)
        return True

    def stop(self):
        if self.engine is not None:
            self.engine.stop()
