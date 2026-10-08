import json
from contextlib import nullcontext
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meikipop.dictionary.translation import (
    DEFAULT_ENDPOINT, DEFAULT_MODEL, LocalTranslator, TranslationSettings,
    _translation_content, load_settings, local_endpoint, save_settings,
)


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.translator = LocalTranslator(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def server(self, content="A translated sentence.", status=200, result=None, payload=None):
        if result is None:
            result = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        response = Mock(status=status)
        response.read.return_value = payload if payload is not None else json.dumps(result).encode()
        connection = Mock()
        connection.getresponse.return_value = response
        self.connection = connection
        self.response = response
        return patch("meikipop.dictionary.translation.http.client.HTTPConnection", return_value=connection)

    def manual(self, **kwargs):
        return save_settings(TranslationSettings(auto_start=False, **kwargs), self.directory)

    def test_defaults_are_quality_and_no_runtime_models_are_imported(self):
        self.assertEqual(load_settings(self.directory), TranslationSettings())
        with patch.dict(sys.modules, {"torch": None, "ctranslate2": None, "sentencepiece": None}):
            self.manual()
            with self.server():
                self.assertEqual(self.translator.translate("Merhaba.", "tr", "en"), "A translated sentence.")
        self.assertEqual(self.translator.last_model, "Hy-MT2-7B Q8_0")

    def test_json_response_to_stream_request_is_not_retried(self):
        self.manual()
        progress = Mock()
        with self.server():
            self.response.getheader.return_value = "application/json"
            self.assertEqual(self.translator.translate("cat", "en", "ja", on_text=progress), "A translated sentence.")
        self.connection.request.assert_called_once()
        self.assertTrue(json.loads(self.connection.request.call_args.kwargs["body"])["stream"])

    def test_custom_stream_rejection_requires_explicit_nonstream_preference(self):
        self.manual(provider="custom")
        with self.server(status=400), self.assertRaisesRegex(RuntimeError, "Turn off Stream"):
            self.translator.translate("cat", "en", "ja", on_text=Mock())
        self.connection.request.assert_called_once()

    def test_cancel_before_startup_does_not_clear_request_cancellation(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.server(), self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.translator.translate("cat", "en", "ja", cancelled=cancelled)
        self.connection.request.assert_not_called()

    def test_settings_are_atomic_and_change_translation_cache_key(self):
        first = self.translator.cache_key()
        value = save_settings(TranslationSettings(profile="lightweight"), self.directory)
        self.assertEqual(load_settings(self.directory), value)
        self.assertNotEqual(first, self.translator.cache_key())
        self.assertEqual([path.name for path in self.directory.iterdir()], ["settings.json"])
        with self.assertRaises(ValueError):
            save_settings(TranslationSettings(provider="ct2"), self.directory)
        self.assertEqual(load_settings(self.directory), value)

    def test_invalid_settings_are_actionable_and_do_not_silently_change_provider(self):
        for value in ('[]', '{"provider":"cloud"}', '{"profile":[]}', '{"auto_start":"false"}', 'bad json'):
            with self.subTest(value=value):
                (self.directory / "settings.json").write_text(value)
                with self.assertRaisesRegex(ValueError, "(?i)settings?"):
                    load_settings(self.directory)

    def test_only_numeric_loopback_and_localhost_are_allowed(self):
        self.assertEqual(local_endpoint("http://localhost:8766/v1/"), DEFAULT_ENDPOINT)
        self.assertEqual(local_endpoint("http://[::1]:8000/v1"), "http://[::1]:8000/v1")
        self.assertEqual(local_endpoint("http://127.0.0.2:9000"), "http://127.0.0.2:9000")
        for address in (
            "https://example.com/v1", "http://192.168.1.2:8080/v1", "http://0.0.0.0:8080",
            "http://example.com", "http://localhost.example.com", "file:///tmp/socket",
            "http://user:password@localhost", "http://127.0.0.1:0/v1", "http://127.0.0.1:99999",
            "http://localhost/v1?url=outside", "http://localhost/v1#test", "http://127.1",
            "http://[::ffff:192.168.1.2]", "http://localhost/../v1", "http://localhost/%2e/v1",
            "http://localhost/\\evil", "http://localhost\n/v1",
        ):
            with self.subTest(address=address), self.assertRaises(ValueError):
                local_endpoint(address)

    def test_publisher_prompt_parameters_and_exact_original_text(self):
        self.manual()
        with self.server("これは本です。"):
            result = self.translator.translate("This is a book.\n\nThank you.", "en", "ja")
        args, kwargs = self.connection.request.call_args
        self.assertEqual(args, ("POST", "/v1/chat/completions"))
        request = json.loads(kwargs["body"])
        self.assertEqual(request["messages"], [{
            "role": "user",
            "content": "Translate the following text into Japanese. Note that you should only output "
                       "the translated result without any additional explanation:\nThis is a book.\n\nThank you.",
        }])
        self.assertEqual(request["model"], DEFAULT_MODEL)
        self.assertEqual(request["temperature"], 0.7)
        self.assertEqual(request["top_p"], 0.6)
        self.assertEqual(request["top_k"], 20)
        self.assertEqual(request["repeat_penalty"], 1.05)
        self.assertEqual(request["repeat_last_n"], 8192)
        self.assertEqual(request["min_p"], 0.0)
        self.assertEqual(request["samplers"], ["penalties", "temperature", "top_k", "top_p"])
        self.assertEqual(request["max_tokens"], 4096)
        self.assertEqual(result, "これは本です。")
        self.connection.close.assert_called_once()

    def test_managed_model_rejects_unlisted_source_and_target_languages(self):
        self.manual()
        with self.server():
            for source, target in (("el", "en"), ("en", "sv"), ("bg", "tr")):
                with self.subTest(source=source, target=target), self.assertRaisesRegex(ValueError, "does not list support"):
                    self.translator.translate("text", source, target)
            self.connection.request.assert_not_called()
        save_settings(TranslationSettings(provider="custom", model="wider-model"), self.directory)
        with self.server("Greek translation"):
            self.assertEqual(self.translator.translate("text", "en", "el"), "Greek translation")

    def test_mandarin_profile_can_translate_in_both_directions(self):
        self.manual()
        for source, target, name in (("en", "cmn", "Chinese"), ("cmn", "en", "English")):
            with self.subTest(source=source, target=target), self.server("translation"):
                self.assertEqual(self.translator.translate("text", source, target), "translation")
                request = json.loads(self.connection.request.call_args.kwargs["body"])
                self.assertIn(f"into {name}.", request["messages"][0]["content"])

    def test_cancel_interrupts_active_response_and_disallows_late_result(self):
        self.manual()
        with self.server():
            self.connection.getresponse.side_effect = lambda: (self.translator.cancel(), self.response)[1]
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.translator.translate("text", "tr", "en")
            self.connection.sock.shutdown.assert_called_once()
        self.assertEqual(self.translator.last_model, "")
        self.assertIsNone(self.translator._connection)

    def test_custom_server_never_starts_or_downloads_a_managed_model(self):
        save_settings(TranslationSettings(provider="custom", endpoint="http://localhost:9090/v1",
                                          model="custom-model"), self.directory)
        manager = SimpleNamespace(ensure_server=Mock(side_effect=AssertionError("Unexpected startup")),
                                  install_model=Mock(side_effect=AssertionError("Unexpected download")))
        with patch.dict(sys.modules, {"meikipop.scripts.translation_server": manager}), self.server():
            self.translator.translate("Merhaba.", "tr", "en")
        self.assertEqual(self.translator.last_provider, "custom")
        self.assertEqual(self.translator.last_model, "custom-model")
        manager.ensure_server.assert_not_called()
        manager.install_model.assert_not_called()

    def test_managed_start_is_lazy_and_uses_explicit_selected_profile(self):
        save_settings(TranslationSettings(profile="lightweight"), self.directory)
        manager = SimpleNamespace(ensure_server=Mock(), install_model=Mock(), request_lock=lambda *_: nullcontext())
        with patch.dict(sys.modules, {"meikipop.scripts.translation_server": manager}), self.server():
            manager.ensure_server.assert_not_called()
            self.translator.translate("猫", "ja", "en")
        manager.ensure_server.assert_called_once_with(endpoint=DEFAULT_ENDPOINT, profile="lightweight",
                                                      timeout=120, directory=self.directory, cancelled=self.translator._cancelled,
                                                      keep_warm=False, request_id=0)
        manager.install_model.assert_not_called()
        self.assertEqual(self.translator.last_model, "Hy-MT2-1.8B Q8_0")

    def test_missing_managed_model_does_not_fall_back_or_make_a_request(self):
        manager = SimpleNamespace(ensure_server=Mock(side_effect=RuntimeError("Install the selected model.")),
                                  request_lock=lambda *_: nullcontext())
        with patch.dict(sys.modules, {"meikipop.scripts.translation_server": manager}), self.server():
            with self.assertRaisesRegex(RuntimeError, "Install"):
                self.translator.translate("猫", "ja", "en")
        self.connection.request.assert_not_called()
        self.assertEqual(self.translator.last_model, "")

    def test_environment_proxies_are_bypassed_by_direct_loopback_connection(self):
        self.manual()
        with patch.dict(os.environ, {"HTTP_PROXY": "http://outside.invalid", "ALL_PROXY": "http://outside.invalid"}):
            with self.server() as constructor:
                self.translator.translate("猫", "ja", "en")
        constructor.assert_called_once_with("127.0.0.1", 8766, timeout=120)

    def test_redirect_and_http_errors_are_not_followed_or_fallen_back(self):
        self.manual()
        for status in (302, 404, 503):
            with self.subTest(status=status), self.server(status=status):
                with self.assertRaisesRegex(RuntimeError, str(status)):
                    self.translator.translate("猫", "ja", "en")
                self.connection.request.assert_called_once()
                self.response.read.assert_not_called()
                self.connection.close.assert_called_once()

    def test_connection_failure_clears_previous_source_and_closes_socket(self):
        self.manual()
        with self.server():
            self.translator.translate("猫", "ja", "en")
            self.connection.request.side_effect = ConnectionRefusedError()
            with self.assertRaisesRegex(RuntimeError, "Cannot reach"):
                self.translator.translate("犬", "ja", "en")
        self.assertEqual(self.translator.last_model, "")

    def test_invalid_or_oversized_response_fails_clearly(self):
        self.manual()
        for payload, expected in ((b"bad json", "invalid JSON"), (b"x" * (1024 * 1024 + 1), "too large")):
            with self.subTest(expected=expected), self.server(payload=payload):
                with self.assertRaisesRegex(RuntimeError, expected):
                    self.translator.translate("猫", "ja", "en")
                self.response.read.assert_called_once_with(1024 * 1024 + 1)

    def test_only_explicit_thinking_blocks_are_removed(self):
        def response(content, **kwargs):
            return {"choices": [{"message": {"content": content, **kwargs}}]}
        self.assertEqual(_translation_content(response("<think>Reasoning\nonly</think>\nCat.")), "Cat.")
        self.assertEqual(_translation_content(response('"Cat."\n<b>Example</b>')), '"Cat."\n<b>Example</b>')
        self.assertEqual(_translation_content(response("Cat.", reasoning_content="private reasoning")), "Cat.")
        with self.assertRaisesRegex(RuntimeError, "incomplete reasoning"):
            _translation_content(response("<think>unfinished"))
        for content in ("", None):
            with self.assertRaisesRegex(RuntimeError, "no translated text"):
                _translation_content(response(content))

    def test_truncated_or_malformed_translation_is_never_presented_as_complete(self):
        for response in (
            {"choices": [{"finish_reason": "length", "message": {"content": "half"}}]},
            {"choices": []}, {"choices": [None]}, {"choices": [{"message": {}}]}, [],
        ):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                _translation_content(response)

    def test_identity_empty_and_invalid_input_do_not_start_a_model(self):
        with patch("meikipop.dictionary.translation.http.client.HTTPConnection") as connection:
            self.assertEqual(self.translator.translate("hello", "en", "en"), "hello")
            self.assertEqual(self.translator.translate("", "ja", "en"), "")
            with self.assertRaisesRegex(ValueError, "2,000"):
                self.translator.translate("a" * 2001, "ja", "en")
            with self.assertRaisesRegex(ValueError, "not configured"):
                self.translator.translate("hello", "en", "xx")
            connection.assert_not_called()


class TranslationSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.QtCore import QSettings
        from meikipop.gui.dictionary_manager import SetupDialog
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.translation_directory = self.directory / "translation"
        self.load = patch("meikipop.dictionary.translation.load_settings",
                          side_effect=lambda: load_settings(self.translation_directory))
        self.load.start()
        settings = QSettings(str(self.directory / "qt.ini"), QSettings.Format.IniFormat)
        self.dialog = SetupDialog(self.directory / "library", settings, Mock())

    def tearDown(self):
        if self.dialog.operation is not None:
            self.dialog.cancel_operation()
            self.dialog.operation.thread.join(timeout=2)
        self.dialog.hide()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.load.stop()
        self.temp.cleanup()

    def test_selection_saves_explicit_model_and_refreshes_search(self):
        changed = Mock()
        self.dialog.dictionaries_changed.connect(changed)
        self.dialog.translation_mode.setCurrentIndex(1)
        from meikipop.dictionary.translation import load_profile_settings
        self.assertEqual(load_profile_settings(self.dialog.settings, "ja").profile, "lightweight")
        self.assertEqual(load_profile_settings(self.dialog.settings, "tr").profile, "quality")
        changed.assert_not_called()
        self.assertTrue(self.dialog.translation_endpoint.isHidden())

    def test_custom_address_is_validated_before_saving_and_has_no_download_action(self):
        self.dialog.translation_mode.setCurrentIndex(2)
        self.assertFalse(self.dialog.translation_endpoint.isHidden())
        self.assertTrue(all(row.isHidden() for row in self.dialog.resources.model_rows.values()))
        self.dialog.translation_endpoint.setText("https://outside.invalid/v1")
        self.assertFalse(self.dialog.save_translation())
        self.assertFalse((self.translation_directory / "settings.json").exists())
        self.dialog.translation_endpoint.setText("http://localhost:8000/v1")
        self.dialog.translation_model.setText("my-local-model")
        self.assertTrue(self.dialog.save_translation())
        from meikipop.dictionary.translation import load_profile_settings
        self.assertEqual(load_profile_settings(self.dialog.settings, "ja").provider, "custom")

    def test_explicit_download_runs_off_ui_thread_and_cancels_cooperatively(self):
        started = threading.Event()
        main_thread = threading.get_ident()
        called_threads = []

        def install(*, profile, progress, cancelled):
            called_threads.append(threading.get_ident())
            self.assertEqual(profile, "quality")
            progress("Downloading selected model")
            started.set()
            cancelled.wait(2)
            if cancelled.is_set():
                raise InterruptedError()

        manager = SimpleNamespace(install_model=install)
        with patch.dict(sys.modules, {"meikipop.scripts.translation_server": manager}):
            self.dialog.resources.downloads["quality"].click()
            self.assertTrue(started.wait(2))
            self.assertFalse(self.dialog.translation_mode.isEnabled())
            self.dialog.cancel_operation()
            deadline = time.monotonic() + 2
            while self.dialog.operation is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
        self.assertIsNone(self.dialog.operation)
        self.assertNotEqual(called_threads[0], main_thread)
        self.assertIn("cancelled", self.dialog.status.text())
        self.assertTrue(self.dialog.resources.downloads["quality"].isEnabled())


if __name__ == "__main__":
    unittest.main()
