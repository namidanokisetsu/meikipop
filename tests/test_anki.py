import json
import socket
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from meikipop.anki import AnkiClient, AnkiSettings, endpoint_address, note_values, suggest_fields
from meikipop.dictionary.library import Entry
from meikipop.dictionary.pitch import Pitch


class AnkiTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.error = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                result = {"version": 6, "deckNames": ["Japanese"], "modelNames": ["Basic"],
                          "modelFieldNames": ["Front", "Back", "Sentence", "Pitch"], "addNote": 123}[body["action"]]
                raw = json.dumps(dict(result=result, error=owner.error)).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs=dict(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.options = AnkiSettings(True, f"http://127.0.0.1:{self.server.server_port}", "test-key", "Japanese", "Basic",
                                    {"Front": "expression", "Back": "glossary", "Sentence": "sentence", "Pitch": "pitch"})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def test_catalog_and_unicode_export_with_duplicate_protection(self):
        client = AnkiClient(self.options)
        self.assertEqual(client.catalog(), (["Japanese"], ["Basic"]))
        entry = Entry("1", "猫", "ねこ", "Words", "ja", ("cat <animal>",), pitches=(Pitch("Accent", "ねこ", 1),))
        self.assertEqual(client.add(note_values([entry], "猫を見た。")), 123)
        body = self.requests[-1]
        self.assertEqual((body["action"], body["version"], body["key"]), ("addNote", 6, "test-key"))
        note = body["params"]["note"]
        self.assertEqual(note["fields"]["Front"], "猫")
        self.assertEqual(note["fields"]["Sentence"], "猫を見た。")
        self.assertIn("&lt;animal&gt;", note["fields"]["Back"])
        self.assertIn("ꜜ", note["fields"]["Pitch"])
        self.assertFalse(note["options"]["allowDuplicate"])
        self.assertEqual(note["options"]["duplicateScope"], "deck")

    def test_field_matching_follows_kikitori_and_leaves_unrelated_fields_empty(self):
        fields = ["word", "READING", "sentence", "sentenceFurigana", "sentenceTranslation",
                  "chosenDefinition", "definition", "picture", "wordAudio", "sentenceAudio",
                  "pitchPositions", "pitchCategories", "freqSort", "supplement", "miscInfo", "Readng"]
        mapping = suggest_fields(fields)
        self.assertEqual(mapping["word"], "expression")
        self.assertEqual(mapping["READING"], "reading")
        self.assertEqual(mapping["Readng"], "reading")
        self.assertEqual(mapping["sentenceFurigana"], "sentence_furigana")
        self.assertEqual(mapping["sentenceTranslation"], "sentence_translation")
        self.assertEqual(mapping["wordAudio"], "word_audio")
        self.assertEqual(mapping["picture"], "picture")
        self.assertEqual(mapping["chosenDefinition"], "glossary")
        for field in ("sentenceAudio", "supplement", "miscInfo"):
            self.assertEqual(mapping[field], "")
        self.assertEqual(suggest_fields(["Sentence-Furigana", "Word Reading"]),
                         {"Sentence-Furigana": "sentence_furigana", "Word Reading": "reading"})

    def test_media_uploads_to_mapped_fields_before_one_note_write(self):
        options = replace(self.options, fields={"Front": "expression", "Back": "picture"})
        client = AnkiClient(options)
        with patch.object(client, "call", side_effect=[["Front", "Back"], "image.png", 123]) as call:
            client.add({"expression": "cat", "_media": {"picture": {"filename": "image.png", "data": b"png"}}})
        self.assertEqual([item.args[0] for item in call.call_args_list], ["modelFieldNames", "storeMediaFile", "addNote"])
        self.assertEqual(call.call_args.kwargs["note"]["fields"]["Back"], '<img src="image.png">')
        with patch.object(client, "call", side_effect=[["Front", "Back"], ValueError("Media failed")]) as call:
            with self.assertRaisesRegex(ValueError, "Media failed"):
                client.add({"expression": "cat", "_media": {"picture": {"filename": "image.png", "data": b"png"}}})
        self.assertNotIn("addNote", [item.args[0] for item in call.call_args_list])

    def test_kikitori_furigana_translation_and_pitch_values(self):
        entry = Entry("1", "猫", "ねこ", "Words", "ja", ("cat",), pitches=(Pitch("Accent", "ねこ", 1),))
        values = note_values([entry], "猫がいる。", translation="A cat <here>.")
        self.assertEqual(values["sentence_furigana"], " 猫[ねこ]がいる。")
        self.assertEqual(values["sentence_translation"], "A cat &lt;here&gt;.")
        self.assertEqual(values["pitch_positions"], "1")
        self.assertEqual(values["pitch_categories"], "atamadaka")

    def test_mapping_changes_and_disabled_integration_never_write(self):
        for options in (replace(self.options, enabled=False), replace(self.options, fields={"Front": "sentence"}),
                        replace(self.options, fields={"Front": "expression", "Deleted": "reading"})):
            with self.assertRaises(ValueError):
                AnkiClient(options).add({"expression": "猫"})
        self.assertNotIn("addNote", [request["action"] for request in self.requests])

    def test_duplicate_and_api_errors_are_preserved(self):
        self.error = "cannot create note because it is a duplicate"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            AnkiClient(self.options).call("addNote", note={})
        self.assertEqual(len(self.requests), 1)

    def test_timeout_is_not_retried_and_does_not_claim_failure_to_save(self):
        with patch("meikipop.anki.http.client.HTTPConnection") as connection:
            connection.return_value.getresponse.side_effect = socket.timeout()
            with self.assertRaisesRegex(ValueError, "Check Anki before retrying"):
                AnkiClient(self.options).call("addNote", note={})
            self.assertEqual(connection.return_value.request.call_count, 1)

    def test_redirect_is_not_followed(self):
        with patch("meikipop.anki.http.client.HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status, response.read.return_value = 302, b""
            with self.assertRaises(ValueError):
                AnkiClient(self.options).catalog()
            self.assertEqual(connection.return_value.request.call_count, 1)

    def test_remote_addresses_rejected_and_selection_escaped(self):
        for address in ("http://example.org:8765", "http://127.0.0.1@evil.org", "https://localhost", "file:///tmp/test"):
            with self.assertRaises(ValueError):
                endpoint_address(address)
        self.assertEqual(endpoint_address("http://localhost:8765"), ("127.0.0.1", 8765))
        entry = Entry("1", "ışık", "", "Türkçe", "tr", ("light",))
        values = note_values([entry], "Işık <parlak>.", "chosen <sense>\nexample")
        self.assertEqual(values["glossary"], "chosen &lt;sense&gt;<br>example")
        self.assertEqual(values["pitch"], "")
