import unittest

from meikipop.gui.activation import (
    ActivationState,
    normalise_activation_bindings,
    parse_activation_bindings,
)


class ActivationBindingTests(unittest.TestCase):
    def test_aliases_and_or_semantics(self):
        self.assertEqual(normalise_activation_bindings("Shift,button2"), "shift,middle")
        state = ActivationState("shift,middle")
        self.assertTrue(state.update("shift", True).became_active)
        self.assertEqual(state.activation_id, 1)
        transition = state.update("shift", False)
        self.assertFalse(transition.became_active)
        self.assertTrue(transition.became_inactive)

    def test_keyboard_chord_uses_and_semantics(self):
        state = ActivationState("ctrl+shift")
        self.assertFalse(state.update("ctrl", True).became_active)
        self.assertTrue(state.update("shift", True).became_active)
        self.assertTrue(state.active)
        self.assertFalse(state.update("ctrl", False).became_active)
        self.assertFalse(state.active)

    def test_overlapping_bindings_are_one_session(self):
        state = ActivationState("shift,middle")
        self.assertTrue(state.update("shift", True).became_active)
        self.assertFalse(state.update("middle", True).became_active)
        self.assertFalse(state.update("shift", False).became_inactive)
        self.assertTrue(state.active)
        self.assertTrue(state.update("middle", False).became_inactive)
        self.assertEqual(state.activation_id, 1)
        self.assertTrue(state.update("middle", True).became_active)
        self.assertEqual(state.activation_id, 2)

    def test_invalid_and_mixed_bindings_are_rejected(self):
        for value in ("shift+middle", "bogus", "", "middle+mouse4"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_activation_bindings(value)


if __name__ == "__main__":
    unittest.main()
