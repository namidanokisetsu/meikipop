"""Optional pronunciation through an installed Turkish system voice."""
from PyQt6.QtCore import QObject, QLocale


class TurkishSpeech(QObject):
    locale = QLocale("tr_TR")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = None
        self.last_error = ""

    def speak(self, text):
        if self.engine is None:
            try:
                from PyQt6.QtTextToSpeech import QTextToSpeech
                self.engine = QTextToSpeech(self)
                # The Windows backend only lists voices for its current locale.
                self.engine.setLocale(self.locale)
                voice = next((v for v in self.engine.availableVoices()
                              if v.locale().language() == QLocale.Language.Turkish), None)
                if voice is None:
                    raise RuntimeError("Windows did not expose a Turkish speech voice.")
                self.engine.setVoice(voice)
            except Exception as error:
                self.last_error = str(error)
                if self.engine is not None:
                    self.engine.deleteLater()
                    self.engine = None
                return False
        self.engine.stop()
        self.engine.say(text)
        self.last_error = ""
        return True

    def stop(self):
        if self.engine is not None:
            self.engine.stop()
