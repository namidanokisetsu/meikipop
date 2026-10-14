"""Shared popup pronunciation with online, local and system-voice sources."""
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QLocale, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from meikipop.audio.worker import AudioRequest, AudioWorker
from meikipop.audio.sources import database_path, source_order
from meikipop.config.config import config


def speech_locale(language):
    language = {"cmn": "zh", "fil": "tl", "zh-hant": "zh_TW", "zh-hans": "zh_CN",
                "zh-tw": "zh_TW", "zh-hk": "zh_HK"}.get(language, language)
    locale = QLocale(language)
    expected = QLocale.codeToLanguage(language.replace("_", "-").split("-", 1)[0])
    return None if expected in {QLocale.Language.C, QLocale.Language.AnyLanguage} or locale.language() != expected else locale


class LookupAudio(QObject):
    clip_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    result_ready = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._media_devices = QMediaDevices(self)
        self.output = QAudioOutput(self)
        self._media_devices.audioOutputsChanged.connect(self._follow_system_audio_output)
        self._follow_system_audio_output()
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.buffer = None
        self.speech = None
        self.latest = None
        self.current_clip = None
        self._serial = 0
        self._pending = None
        self._speech_error = ""
        self.clip_ready.connect(self._play_clip)
        self.result_ready.connect(self._audio_result)
        # Only exhausted source choices should replace useful lookup content.
        self.worker = AudioWorker(self.clip_ready.emit, lambda _: None, result_callback=self.result_ready.emit)
        self.worker.start()
        self.player.errorOccurred.connect(self._playback_failed)
        self.player.mediaStatusChanged.connect(self._media_status)

    def _follow_system_audio_output(self):
        device = self._media_devices.defaultAudioOutput()
        if self.output.device() != device:
            self.output.setDevice(device)

    def _release_buffer(self):
        if self.buffer is not None:
            self.buffer.close()
            self.buffer.deleteLater()
            self.buffer = None

    def _media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._pending = None
            self._release_buffer()

    def _playback_failed(self, _, text):
        self.current_clip = None
        self._release_buffer()
        if self._pending is not None:
            self._next_source()
        else:
            self.failed.emit(text)

    def _prepare(self, revision, key, settings, profile):
        self.worker.cancel()
        self.latest = None
        self._pending = None
        self.current_clip = None
        self.player.stop()
        self.player.setSource(QUrl())
        self._release_buffer()
        if self.speech:
            self.speech.stop()
        self._serial += 1
        self.latest = (self._serial, key)
        self._pending = None
        self._speech_error = ""
        volume = settings.value(f"profiles/{profile}/audio_volume", config.audio_volume, type=int)
        self.output.setVolume(volume / 100)
        return volume

    def play(self, entry, revision, settings, profile=None, source=None):
        profile = profile or entry.language
        volume = self._prepare(revision, (entry.term, entry.reading or ""), settings, profile)
        self._pending = (entry, database_path(settings, profile), volume,
                         list([source] if source else source_order(settings, profile)))
        self._next_source()

    def _next_source(self):
        if self._pending is None:
            return
        entry, path, volume, sources = self._pending
        while sources:
            source = sources.pop(0)
            if source == "tts":
                if self._speak(entry.reading or entry.term, entry.language, volume):
                    self.current_clip = None
                    return
            elif source == "online":
                language = {"zh-hant": "zh", "zh-hans": "zh", "zh-tw": "zh", "zh-hk": "zh",
                            "cmn": "zh", "fil": "tl"}.get(entry.language, entry.language)
                iso3 = "cmn" if language == "zh" else QLocale.languageToCode(
                    QLocale.codeToLanguage(language.split("-", 1)[0]), QLocale.LanguageCodeType.ISO639Part3)
                self.worker.submit(AudioRequest(self.latest[0], self.latest[1], "", (),
                                                language=language, iso3=iso3, online=True))
                return
            elif path:
                self.worker.submit(AudioRequest(self.latest[0], self.latest[1], path,
                                                (source[3:],) if source.startswith("db:") else (),
                                                strict_sources=source.startswith("db:")))
                return
        self._pending = None
        self.failed.emit(self._speech_error or "No pronunciation available from the selected sources.")

    def _audio_result(self, request, clip):
        if self.latest != (request.activation_id, request.key):
            return
        if clip:
            self._play_clip(clip)
        else:
            self._next_source()

    def play_text(self, text, language, revision, settings, profile=None):
        if not text.strip():
            return False
        volume = self._prepare(revision, ("sentence", language, text), settings, profile or language)
        if not self._speak(text, language, volume):
            self.failed.emit(self._speech_error)

    def _speech_failed(self, _, text):
        serial = self._serial
        def fallback():
            if serial != self._serial or self.latest is None:
                return
            self._speech_error = text
            if self._pending is not None:
                self._next_source()
            else:
                self.failed.emit(text)
        # Some engines emit an error synchronously inside say().
        QTimer.singleShot(0, fallback)

    def _speak(self, text, language, volume):
        from PyQt6.QtTextToSpeech import QTextToSpeech
        locale = speech_locale(language)
        if locale is None:
            self._speech_error = f"No {language} system voice installed."
            return False
        if self.speech is None:
            self.speech = QTextToSpeech(self)
            self.speech.errorOccurred.connect(self._speech_failed)
        self.speech.setLocale(locale)
        voices = [v for v in self.speech.availableVoices() if v.locale().language() == locale.language()]
        if not voices:
            self._speech_error = f"No {locale.nativeLanguageName()} system voice installed."
            return False
        self.speech.setVoice(voices[0])
        self.speech.setVolume(volume / 100)
        self.speech.say(text)
        return True

    def _play_clip(self, clip):
        if self.latest != (clip.activation_id, clip.key):
            return
        self.current_clip = clip
        self.player.stop()
        self._release_buffer()
        self.buffer = QBuffer(self)
        self.buffer.setData(QByteArray(clip.data))
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.player.setSourceDevice(self.buffer, QUrl("memory:///" + clip.filename))
        self.player.play()

    def cancel(self):
        self.worker.cancel()
        self.current_clip = None
        self.latest = None
        self._pending = None
        self.player.stop()
        self.player.setSource(QUrl())
        self._release_buffer()
        if self.speech:
            self.speech.stop()

    def shutdown(self):
        self.cancel()
        self.worker.stop()
        self.worker.join(timeout=2)
