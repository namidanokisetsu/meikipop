import unittest
from unittest.mock import patch

from meikipop.audio.online import OnlineAudio


class OnlineAudioTests(unittest.TestCase):
    def test_exact_language_and_word_filter_and_cached_recording_credit(self):
        client = OnlineAudio()
        results = {"query": {"search": [{"title": title} for title in
                   ("File:Ru-привет.ogg", "File:En-привет.ogg", "File:Ru-приветствие.ogg")]}}
        info = {"query": {"pages": {"1": {"imageinfo": [{
            "url": "https://upload.wikimedia.org/audio.ogg", "user": "Speaker",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Ru-привет.ogg",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}}}}
        with patch.object(client, "_fetch", side_effect=[results, info, b"OggSfixture"]) as fetch:
            result = client.lookup("приве\u0301т", "ru", "rus")
            self.assertEqual(fetch.call_args_list[1].kwargs["params"]["titles"], "File:Ru-привет.ogg")
            self.assertEqual(result[1:4], ("Wiktionary", b"OggSfixture", "Speaker · CC BY-SA 4.0"))
            self.assertEqual(client.lookup("привет", "ru", "rus"), result)
            self.assertEqual(fetch.call_count, 3)

    def test_lingua_libre_fallback_and_missing_recording_cache(self):
        client = OnlineAudio()
        empty = {"query": {"search": []}}
        results = {"query": {"search": [{"title": "File:LL-Q7737 (rus)-Speaker-привет.wav"}]}}
        info = {"query": {"pages": {"1": {"imageinfo": [{
            "url": "https://upload.wikimedia.org/audio.wav", "extmetadata": {}}]}}}}
        with patch.object(client, "_fetch", side_effect=[empty, results, info, b"RIFFfixture"]):
            self.assertEqual(client.lookup("привет", "ru", "rus")[1], "Lingua Libre")
        with patch.object(client, "_fetch", return_value=empty) as fetch:
            self.assertIsNone(client.lookup("absent", "en", "eng"))
            self.assertIsNone(client.lookup("absent", "en", "eng"))
            self.assertEqual(fetch.call_count, 2)

    def test_requests_are_bounded_cancelled_and_reject_non_audio_or_foreign_hosts(self):
        from time import monotonic
        client = OnlineAudio()
        options = dict(cancelled=lambda: False, deadline=monotonic() + 10, audio=True)
        with patch("meikipop.audio.online.requests.get") as get:
            with self.assertRaises(ValueError):
                client._fetch("https://example.com/audio", **options)
            get.assert_not_called()
            with self.assertRaises(InterruptedError):
                client._fetch(client.API, cancelled=lambda: True, deadline=monotonic() + 10)
            get.assert_not_called()
            response = get.return_value.__enter__.return_value
            response.is_redirect = False
            response.iter_content.return_value = [b"<html>error</html>"]
            with self.assertRaises(ValueError):
                client._fetch(client.API, **options)
            client.MAX_AUDIO = 4
            response.iter_content.return_value = [b"OggS", b"overflow"]
            with self.assertRaises(ValueError):
                client._fetch(client.API, **options)
