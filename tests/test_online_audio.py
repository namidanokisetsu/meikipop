import unittest
from unittest.mock import patch

from meikipop.audio.online import OnlineAudio


class OnlineAudioTests(unittest.TestCase):
    def test_japanese_wav_and_reading_are_included_with_indexed_search(self):
        client = OnlineAudio()
        info = {"query": {"pages": {"1": {"title": "File:L7-ja-猫.wav", "imageinfo": [{
            "url": "https://upload.wikimedia.org/audio.wav", "extmetadata": {}}]}}}}
        with patch.object(client, "_fetch", side_effect=[info, b"RIFFfixture"]) as fetch:
            result = client.lookup("猫", "ja", "jpn", reading="ねこ")
            self.assertEqual(result[2], b"RIFFfixture")
            query = fetch.call_args_list[0].kwargs["params"]["gsrsearch"]
            self.assertIn('intitle:"猫"', query)
            self.assertIn('ねこ', query)
            self.assertNotIn('(?:', query)

    def test_exact_language_and_word_filter_and_cached_recording_credit(self):
        client = OnlineAudio()
        recording = {
            "url": "https://upload.wikimedia.org/audio.ogg", "user": "Speaker",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Ru-привет.ogg",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}}}
        results = {"query": {"pages": {str(i): {"title": title, "imageinfo": [recording]}
                   for i, title in enumerate(("File:En-привет.ogg", "File:Ru-приветствие.ogg", "File:Ru-привет.ogg"))}}}
        with patch.object(client, "_fetch", side_effect=[results, b"OggSfixture"]) as fetch:
            result = client.lookup("приве\u0301т", "ru", "rus")
            self.assertEqual(fetch.call_args_list[0].kwargs["params"]["generator"], "search")
            self.assertEqual(result[1:4], ("Wiktionary", b"OggSfixture", "Speaker · CC BY-SA 4.0"))
            self.assertEqual(client.lookup("привет", "ru", "rus"), result)
            self.assertEqual(fetch.call_count, 2)

    def test_lingua_libre_fallback_and_missing_recording_cache(self):
        client = OnlineAudio()
        empty = {"query": {"pages": {}}}
        info = {"query": {"pages": {"1": {"title": "File:LL-Q256 (tur)-Speaker-ev.wav", "imageinfo": [{
            "url": "https://upload.wikimedia.org/audio.wav", "extmetadata": {}}]}}}}
        with patch.object(client, "_fetch", side_effect=[info, b"RIFFfixture"]):
            self.assertEqual(client.lookup("ev", "tr", "tur")[1], "Lingua Libre")
        with patch.object(client, "_fetch", return_value=empty) as fetch:
            self.assertIsNone(client.lookup("absent", "en", "eng"))
            self.assertIsNone(client.lookup("absent", "en", "eng"))
            self.assertEqual(fetch.call_count, 1)

    def test_network_failures_are_cached_but_cancellation_is_not(self):
        import requests
        client = OnlineAudio()
        with patch.object(client, "_fetch", side_effect=requests.Timeout) as fetch:
            self.assertIsNone(client.lookup("ev", "tr", "tur"))
            self.assertIsNone(client.lookup("ev", "tr", "tur"))
            self.assertEqual(fetch.call_count, 1)
        client = OnlineAudio()
        with patch.object(client, "_fetch", side_effect=InterruptedError):
            self.assertIsNone(client.lookup("ev", "tr", "tur", cancelled=lambda: True))
            self.assertFalse(client.cache)

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
