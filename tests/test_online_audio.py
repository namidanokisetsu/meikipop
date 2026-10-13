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

    def test_japanese_reading_qualifiers_take_priority_over_generic_files(self):
        for suffix in (" (いも)", "（いも）"):
            with self.subTest(suffix=suffix):
                client = OnlineAudio()
                pages = {str(i): {"title": title, "imageinfo": [{"url": f"https://upload.wikimedia.org/{i}.wav"}]}
                         for i, title in enumerate(("File:L7-ja-妹.wav", "File:LL-Q5287 (jpn)-Speaker-妹 (いもうと).wav",
                                                    f"File:LL-Q5287 (jpn)-Speaker-妹{suffix}.wav"))}
                with patch.object(client, "_fetch", side_effect=[{"query": {"pages": pages}}, b"RIFFfixture"]) as fetch:
                    result = client.lookup("妹", "ja", "jpn", reading="いも")
                    self.assertEqual(result[0], "2.wav")
                    self.assertEqual(result[1], "Lingua Libre")
                    self.assertEqual(fetch.call_args.args[0], "https://upload.wikimedia.org/2.wav")

    def test_mismatched_reading_qualifier_is_rejected(self):
        client = OnlineAudio()
        page = {"title": "File:LL-Q5287 (jpn)-Speaker-日本語 (にっぽんご).wav", "imageinfo": [{"url": "https://upload.wikimedia.org/wrong.wav"}]}
        with patch.object(client, "_fetch", return_value={"query": {"pages": {"1": page}}}) as fetch:
            self.assertIsNone(client.lookup("日本語", "ja", "jpn", reading="にほんご"))
            self.assertEqual(fetch.call_count, 1)

    def test_failure_cache_recovers_earlier_than_a_genuine_miss(self):
        import requests
        client = OnlineAudio()
        with patch("meikipop.audio.online.monotonic", return_value=100), patch.object(client, "_fetch", side_effect=requests.Timeout):
            self.assertIsNone(client.lookup("ev", "tr", "tur"))
        with patch("meikipop.audio.online.monotonic", return_value=111), patch.object(client, "_fetch", return_value={}) as fetch:
            self.assertIsNone(client.lookup("ev", "tr", "tur"))
            fetch.assert_called_once()
        with patch("meikipop.audio.online.monotonic", return_value=122), patch.object(client, "_fetch") as fetch:
            self.assertIsNone(client.lookup("ev", "tr", "tur"))
            fetch.assert_not_called()

    def test_cached_audio_is_not_returned_after_cancellation(self):
        client = OnlineAudio()
        client.cache[("ev", "tr", "tur", "")] = (float("inf"), ("fixture",), 3600)
        self.assertIsNone(client.lookup("ev", "tr", "tur", cancelled=lambda: True))

    def test_multiword_spaces_match_commons_underscores(self):
        client = OnlineAudio()
        page = {"title": "File:En-New_York.ogg", "imageinfo": [{"url": "https://upload.wikimedia.org/audio.ogg"}]}
        with patch.object(client, "_fetch", side_effect=[{"query": {"pages": {"1": page}}}, b"OggSfixture"]):
            self.assertIsNotNone(client.lookup("New York", "en", "eng"))

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
