import unittest

from meikipop.gui.lookup_session import LookupSession, popup_mode


class LookupSessionTests(unittest.TestCase):
    def test_outside_click_can_return_to_hover_without_reentering_the_zone(self):
        state = LookupSession(enabled=True, hovering=True)
        state.dismiss(resume_hover=True)
        state.hide()
        self.assertTrue(state.scanning())
        state.dismiss()
        self.assertFalse(state.scanning())

    def test_popup_hide_keeps_hover_active_but_suppresses_held_shortcut(self):
        state = LookupSession(enabled=True, hovering=True, holding=True)
        state.hide()
        self.assertTrue(state.dismissed)
        self.assertTrue(state.scanning())
        state.dismiss()
        state.hide()
        self.assertFalse(state.scanning())

    def test_hover_dismissal_requires_leaving_area_and_does_not_block_explicit_hold(self):
        state = LookupSession(enabled=True)
        state.hover(True)
        self.assertTrue(state.scanning())
        state.dismiss()
        self.assertFalse(state.scanning())
        state.hold(False)
        self.assertFalse(state.scanning())
        state.hold(True)
        self.assertTrue(state.scanning())
        state.hold(False)
        self.assertFalse(state.scanning())
        state.hover(False)
        state.hover(True)
        self.assertTrue(state.scanning())
        state.suspended = True
        self.assertFalse(state.accepts(state.generation))

    def test_dismissal_requires_release_before_another_hold(self):
        state = LookupSession(enabled=True)
        self.assertTrue(state.hold(True))
        state.dismiss()
        state.dismiss()
        self.assertFalse(state.hold(True))
        self.assertFalse(state.scanning())
        state.hold(False)
        self.assertTrue(state.hold(True))

    def test_old_completion_does_not_clear_new_capture(self):
        state = LookupSession(enabled=True, holding=True)
        old = state.generation
        state.capture_generation = old
        state.invalidate()
        state.capture_generation = state.generation
        state.finish_capture(old)
        self.assertEqual(state.capture_generation, state.generation)
        self.assertFalse(state.accepts(old))
        self.assertTrue(state.accepts(state.generation))
        self.assertFalse(state.accepts(state.generation, pinned=True))

    def test_disable_clears_suppression_and_requires_fresh_hold(self):
        state = LookupSession(enabled=True, holding=True)
        state.hide()
        state.enable(False)
        self.assertFalse(state.scanning())
        self.assertFalse(state.hold(True))
        state.enable(True)
        self.assertTrue(state.hold(True))

    def test_popup_modes(self):
        self.assertEqual(popup_mode(visible=False, preview=True, pinned=True, passive=False), "hidden")
        self.assertEqual(popup_mode(visible=True, preview=True, pinned=True, passive=False), "reading")
        self.assertEqual(popup_mode(visible=True, preview=True, pinned=False, passive=False), "preview")
        self.assertEqual(popup_mode(visible=True, preview=False, pinned=False, passive=True), "passive")
        self.assertEqual(popup_mode(visible=True, preview=False, pinned=False, passive=False), "search")
