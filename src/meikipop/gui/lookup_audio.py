"""Shared popup pronunciation using the existing local audio repository."""
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QLocale, QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from meikipop.audio.worker import AudioRequest, AudioWorker
from meikipop.config.config import config


class LookupAudio(QObject):
    clip_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.buffer = None
        self.speech = None
        self.latest = None
        self.clip_ready.connect(self._play_clip)
        self.worker = AudioWorker(self.clip_ready.emit, self._status)
        self.worker.start()
        self.player.errorOccurred.connect(lambda _, text: self.failed.emit(text))

    def _status(self, text):
        if not text.startswith("Audio database ready"):
            self.failed.emit(text)

    def play(self, entry, revision, settings):
        self.player.stop()
        if self.speech:
            self.speech.stop()
        self.latest = (revision, (entry.term, entry.reading or ""))
        volume = settings.value(f"profiles/{entry.language}/audio_volume", config.audio_volume, type=int)
        self.output.setVolume(volume / 100)
        path = settings.value("profiles/ja/audio_database", config.audio_database_path)
        if entry.language == "ja" and path:
            sources = settings.value("profiles/ja/audio_sources", config.audio_preferred_sources)
            self.worker.submit(AudioRequest(revision, self.latest[1], path,
                                            tuple(s.strip() for s in sources.split(",") if s.strip())))
            return
        from PyQt6.QtTextToSpeech import QTextToSpeech
        if self.speech is None:
            self.speech = QTextToSpeech(self)
            self.speech.errorOccurred.connect(lambda _, text: self.failed.emit(text))
        locale = QLocale(entry.language)
        self.speech.setLocale(locale)
        voices = [v for v in self.speech.availableVoices() if v.locale().language() == locale.language()]
        if not voices:
            self.failed.emit(f"No {locale.nativeLanguageName()} voice installed. Choose an audio database or install a system voice in Settings.")
            return
        self.speech.setVoice(voices[0])
        self.speech.setVolume(volume / 100)
        self.speech.say(entry.reading or entry.term)

    def _play_clip(self, clip):
        if self.latest != (clip.activation_id, clip.key):
            return
        self.player.stop()
        if self.buffer:
            self.buffer.close()
            self.buffer.deleteLater()
        self.buffer = QBuffer(self)
        self.buffer.setData(QByteArray(clip.data))
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.player.setSourceDevice(self.buffer, QUrl("memory:///" + clip.filename))
        self.player.play()

    def shutdown(self):
        self.latest = None
        self.player.stop()
        if self.speech:
            self.speech.stop()
        self.worker.stop()
        self.worker.join(timeout=2)
