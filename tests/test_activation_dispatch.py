import unittest

from meikipop.gui.activation import ActivationState
from meikipop.main import SharedState


class ActivationDispatchTests(unittest.TestCase):
    def test_one_screenshot_request_per_activation_transition(self):
        state = ActivationState("shift,middle")
        shared = SharedState()
        for token, pressed in (
            ("shift", True),
            ("middle", True),
            ("shift", False),
            ("middle", False),
            ("middle", True),
        ):
            transition = state.update(token, pressed)
            if transition.became_active:
                shared.request_screenshot(transition.activation_id)

        self.assertEqual(shared.consume_screenshot_request(), 1)
        self.assertEqual(shared.consume_screenshot_request(), 2)
        self.assertFalse(shared._screenshot_requests)

    def test_background_requests_coalesce(self):
        shared = SharedState()
        shared.request_screenshot()
        shared.request_screenshot()
        self.assertEqual(len(shared._screenshot_requests), 1)


if __name__ == "__main__":
    unittest.main()
