import unittest
from unittest.mock import patch

from meikipop.config.config import config
from meikipop.gui.input import InputLoop
from meikipop.pipeline import PipelineValue, REUSE_LAST_VALUE


class _HitScanQueue:
    def __init__(self):
        self.values = []

    def put(self, value):
        self.values.append(value)


class _SharedState:
    def __init__(self):
        self.screenshot_requests = []
        self.hit_scan_queue = _HitScanQueue()

    def request_screenshot(self, activation_id=None):
        self.screenshot_requests.append(activation_id)


class InputMovementTests(unittest.TestCase):
    def setUp(self):
        self.shared = _SharedState()
        self.input_loop = InputLoop.__new__(InputLoop)
        self.input_loop.shared_state = self.shared

    def test_manual_mode_ignores_unactivated_mouse_movement(self):
        with patch.object(config, "auto_scan_mode", False):
            self.input_loop._dispatch_movement(active=False, activation_id=7)

        self.assertEqual(self.shared.screenshot_requests, [])
        self.assertEqual(self.shared.hit_scan_queue.values, [])

    def test_manual_mode_reuses_result_while_activation_is_held(self):
        with patch.object(config, "auto_scan_mode", False):
            self.input_loop._dispatch_movement(active=True, activation_id=7)

        self.assertEqual(
            self.shared.hit_scan_queue.values,
            [PipelineValue(7, REUSE_LAST_VALUE)],
        )

    def test_auto_mode_can_scan_and_lookup_on_movement(self):
        with patch.object(config, "auto_scan_mode", True), \
                patch.object(config, "auto_scan_on_mouse_move", True), \
                patch.object(config, "auto_scan_mode_lookups_without_hotkey", True):
            self.input_loop._dispatch_movement(active=False, activation_id=7)

        self.assertEqual(self.shared.screenshot_requests, [None])
        self.assertEqual(
            self.shared.hit_scan_queue.values,
            [PipelineValue(0, REUSE_LAST_VALUE)],
        )


if __name__ == "__main__":
    unittest.main()
