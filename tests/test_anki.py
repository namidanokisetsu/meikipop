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
    def test_sentence_readings_use_literal_headwords_without_full_search(self):
        from unittest.mock import Mock
        from meikipop.anki import sentence_readings
        library = Mock()
        cat = Entry("1", "猫", "ねこ", "Words", "ja", ("cat",))
        museum = Entry("2", "博物館", "はくぶつかん", "Words", "ja", ("museum",))
        library.lookup.side_effect = lambda text, *args, **kwargs: (museum,) if text == museum.term else ()
        self.assertEqual(sentence_readings("猫と博物館", [cat], library), " 猫[ねこ]と 博物館[はくぶつかん]")
        library.search.assert_not_called()
        self.assertTrue(all(call.kwargs == {"limit": 1, "tolerant": False}
                            for call in library.lookup.call_args_list))

    def setUp(self):
        self.requests = []
        self.error = None
        self.can_add = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                if body["action"] == "canAddNotesWithErrorDetail":
                    result = owner.can_add if owner.can_add is not None else [
                        dict(canAdd=True) for _ in body["params"]["notes"]]
                else:
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
        self.assertNotIn("meikipop-pitch:", note["fields"]["Pitch"])
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
        self.assertEqual(mapping["chosenDefinition"], "popup-selection-text")
        self.assertEqual(suggest_fields(["glossary-first", "glossary", "popup-selection-text"]),
                         {name: name for name in ("glossary-first", "glossary", "popup-selection-text")})
        for field in ("sentenceAudio", "supplement", "miscInfo"):
            self.assertEqual(mapping[field], "")
        self.assertEqual(suggest_fields(["Sentence-Furigana", "Word Reading"]),
                         {"Sentence-Furigana": "sentence_furigana", "Word Reading": "reading"})

    def test_media_uploads_to_mapped_fields_before_one_note_write(self):
        options = replace(self.options, fields={"Front": "expression", "Back": "picture"})
        client = AnkiClient(options)
        with patch.object(client, "call", side_effect=[["Front", "Back"], [{"canAdd": True}], "image.png", 123]) as call:
            client.add({"expression": "cat", "_media": {"picture": {"filename": "image.png", "data": b"png"}}})
        self.assertEqual([item.args[0] for item in call.call_args_list],
                         ["modelFieldNames", "canAddNotesWithErrorDetail", "storeMediaFile", "addNote"])
        self.assertEqual(call.call_args.kwargs["note"]["fields"]["Back"], '<img src="image.png">')
        with patch.object(client, "call", side_effect=[["Front", "Back"], [{"canAdd": True}], ValueError("Media failed")]) as call:
            with self.assertRaisesRegex(ValueError, "Media failed"):
                client.add({"expression": "cat", "_media": {"picture": {"filename": "image.png", "data": b"png"}}})
        self.assertNotIn("addNote", [item.args[0] for item in call.call_args_list])

    def test_duplicate_scopes_use_native_anki_options(self):
        for scope, expected in (("deck", ("Japanese::Words", False)), ("deckroot", ("Japanese", True)),
                                ("collection", None)):
            with self.subTest(scope=scope):
                self.requests.clear()
                options = replace(self.options, deck="Japanese::Words", duplicate_scope=scope, check_all_models=True)
                client = AnkiClient(options)
                client.check("cat")
                client.add({"expression": "cat"})
                self.assertEqual([request["action"] for request in self.requests],
                                 ["modelFieldNames", "canAddNotesWithErrorDetail", "addNote"])
                checked = self.requests[1]["params"]["notes"][0]["options"]
                self.assertEqual(checked, self.requests[-1]["params"]["note"]["options"])
                self.assertEqual(checked["duplicateScope"], "collection" if scope == "collection" else "deck")
                details = checked["duplicateScopeOptions"]
                self.assertTrue(details["checkAllModels"])
                if expected:
                    self.assertEqual((details["deckName"], details["checkChildren"]), expected)
                else:
                    self.assertNotIn("deckName", details)

    def test_existing_notes_use_exact_native_search_and_scoped_ids(self):
        decks = {"Japanese": 1, "Japanese::Words": 2, "Other": 3}
        for scope, expected in (("deck", "did:2 "), ("deckroot", "did:1,2 "),
                                ("decks", "did:2,3 "), ("collection", "")):
            with self.subTest(scope=scope):
                options = replace(self.options, deck="Japanese::Words", duplicate_scope=scope,
                                  duplicate_decks=("Other",))
                client = AnkiClient(options)
                responses = [{"Basic": 10, "Other type": 20}]
                if scope != "collection":
                    responses.append(decks)
                responses.append([{"result": [123, 456], "error": None}, {"result": [], "error": None}])
                with patch.object(client, "call", side_effect=responses) as call:
                    self.assertEqual(client.existing_notes(['猫 "x"', "dog", "dog"]), {'猫 "x"': (123, 456)})
                actions = call.call_args.kwargs["actions"]
                self.assertEqual(actions[0]["params"]["query"], expected + '("dupe:10,猫 &quot;x&quot;")')
                self.assertEqual([action["action"] for action in actions], ["findNotes", "findNotes"])
                self.assertEqual(actions[0]["key"], "test-key")

    def test_existing_notes_across_note_types_and_malformed_responses(self):
        options = replace(self.options, duplicate_scope="collection", check_all_models=True, duplicate_action="allow")
        client = AnkiClient(options)
        with patch.object(client, "call", side_effect=[{"Basic": 10, "Other": 20}, [{"result": [123], "error": None}]]) as call:
            self.assertEqual(client.existing_notes(["cat"]), {"cat": (123,)})
        query = call.call_args.kwargs["actions"][0]["params"]["query"]
        self.assertEqual(query, '("dupe:10,cat" or "dupe:20,cat")')
        for result in ([{"result": [True], "error": None}], [{"result": [123], "error": "failure"}], []):
            with patch.object(client, "call", side_effect=[{"Basic": 10}, result]), self.assertRaises(ValueError):
                client.existing_notes(["cat"])

    def test_selected_decks_include_destination_once_and_block_before_media(self):
        options = replace(self.options, duplicate_scope="decks", duplicate_decks=("Other", "Japanese", "Other"))
        self.can_add = [{"canAdd": True}, {"canAdd": False, "error": "duplicate"}]
        with self.assertRaisesRegex(ValueError, "Other.*duplicate"):
            AnkiClient(options).add({"expression": "cat", "_media": {"picture": {"data": b"png"}}})
        self.assertEqual([request["action"] for request in self.requests],
                         ["modelFieldNames", "canAddNotesWithErrorDetail"])
        notes = self.requests[-1]["params"]["notes"]
        self.assertEqual([note["deckName"] for note in notes], ["Japanese", "Other"])
        self.assertEqual([note["options"]["duplicateScopeOptions"]["deckName"] for note in notes], ["Japanese", "Other"])

    def test_allow_duplicates_skips_check_and_each_new_save_revalidates(self):
        client = AnkiClient(replace(self.options, duplicate_action="allow"))
        for _ in range(2):
            client.add({"expression": "cat"})
        self.assertEqual([request["action"] for request in self.requests],
                         ["modelFieldNames", "addNote", "modelFieldNames", "addNote"])
        self.assertTrue(self.requests[-1]["params"]["note"]["options"]["allowDuplicate"])

    def test_invalid_duplicate_response_never_writes(self):
        for response in ([], [True], [{"canAdd": "true"}], [{"canAdd": False}]):
            with self.subTest(response=response):
                self.can_add = response
                with self.assertRaises(ValueError):
                    AnkiClient(self.options).add({"expression": "cat"})
        self.assertNotIn("addNote", [request["action"] for request in self.requests])

    def test_unmapped_content_is_not_rendered(self):
        from unittest.mock import Mock
        entries = [Entry("1", "cat", "", "Words", "en", ("cat",)),
                   Entry("2", "cat", "", "Other", "en", ("feline",))]
        converter = Mock()
        converter.extract_glosses.return_value = ["first"]
        with patch("meikipop.anki.sentence_readings") as readings, patch("meikipop.anki.render_pitches") as pitch:
            values = note_values(entries, "cat here", converter=converter, sources={"expression"})
            converter.extract_glosses.assert_not_called()
            readings.assert_not_called()
            pitch.assert_not_called()
        self.assertEqual(values["expression"], "cat")
        self.assertEqual(values["glossary"], "")
        values = note_values(entries, converter=converter, sources={"glossary-first"})
        converter.extract_glosses.assert_called_once_with(["cat"])
        self.assertIn("first", values["glossary-first"])
        self.assertEqual(values["glossary"], "")

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
        self.assertEqual(values["popup-selection-text"], "chosen &lt;sense&gt;<br>example")
        self.assertIn("<div>light</div>", values["glossary-first"])
        self.assertIn("text-align:left", values["glossary-first"])
        self.assertIn("<div>light</div>", values["glossary"])
        self.assertNotIn("chosen", values["glossary"])
        self.assertEqual(values["pitch"], "")
