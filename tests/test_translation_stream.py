import io
import json
import threading
import unittest
from unittest.mock import Mock
from meikipop.dictionary.translation_stream import events, read_translation


def event(text, finish=None):
    return ('data: ' + json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': finish}]},
                                  ensure_ascii=False) + '\r\n\r\n').encode()


class StreamTests(unittest.TestCase):
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
