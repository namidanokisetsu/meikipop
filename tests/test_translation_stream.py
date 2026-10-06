import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic
import unittest
from unittest.mock import Mock
from meikipop.dictionary.translation_stream import events, read_translation


def event(text, finish=None):
    return ('data: ' + json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': finish}]},
                                  ensure_ascii=False) + '\r\n\r\n').encode()


class StreamTests(unittest.TestCase):
    def test_loopback_stream_cancels_a_blocked_read_without_retry(self):
        from meikipop.dictionary.translation import LocalTranslator, TranslationSettings
        ready, release = threading.Event(), threading.Event()
        requests, errors = [], []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(event('猫'))
                self.wfile.flush()
                release.wait(2)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        serving = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        serving.start()
        translator = LocalTranslator()
        translator.settings_override = TranslationSettings(provider='custom', endpoint=f'http://127.0.0.1:{server.server_port}/v1')
        def translate():
            try:
                translator.translate('cat', 'en', 'ja', on_text=lambda text: ready.set())
            except RuntimeError as error:
                errors.append(str(error))
        worker = threading.Thread(target=translate)
        worker.start()
        try:
            self.assertTrue(ready.wait(2))
            start = monotonic()
            translator.cancel()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertLess(monotonic()-start, 1)
            self.assertEqual(len(requests), 1)
            self.assertTrue(errors)
            self.assertEqual(translator.last_model, '')
        finally:
            release.set()
            worker.join(2)
            server.shutdown()
            server.server_close()
            serving.join(2)

    def test_every_byte_boundary_and_utf8(self):
        payload = event('猫') + event(' ev', 'stop') + b'data: [DONE]\r\n\r\n'
        response = Mock()
        response.read1.side_effect = [payload[i:i+1] for i in range(len(payload))]
        progress = Mock()
        result = read_translation(response, threading.Event(), progress)
        self.assertEqual(result, '猫 ev')
        self.assertEqual([call.args[0] for call in progress.call_args_list], ['猫', '猫 ev'])

    def test_malformed_disconnect_limit_and_invalid_utf8(self):
        for payload in (event('half'), b'data: {bad}\n\n', b'data: \xff\n\n',
                        event('half', 'length') + b'data: [DONE]\n\n', b'x' * (1024*1024+1)):
            with self.subTest(size=len(payload)), self.assertRaises(RuntimeError):
                read_translation(io.BytesIO(payload), threading.Event(), Mock())

    def test_cancel_during_stream_and_reasoning_is_not_displayed(self):
        cancelled = threading.Event()
        payload = event('<thi') + event('nk>private') + event('</think>猫') + b'data: [DONE]\n\n'
        seen = []
        self.assertEqual(read_translation(io.BytesIO(payload), cancelled, seen.append), '猫')
        self.assertEqual(seen, ['', '', '猫'])
        def chunks():
            yield event('first')
            cancelled.set()
            yield event('late')
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            list(events(chunks(), cancelled))
