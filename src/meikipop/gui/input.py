"""Event-driven global keyboard and mouse input tracking."""
from __future__ import annotations

import logging
import threading

from pynput import keyboard, mouse

from meikipop.config.config import config
from meikipop.gui.activation import ActivationState, normalise_pynput_button, normalise_pynput_key
from meikipop.pipeline import PipelineValue, REUSE_LAST_VALUE

logger = logging.getLogger(__name__)


class InputLoop(threading.Thread):
    """Own activation edge detection; listener callbacks only update state."""

    def __init__(self, shared_state):
        super().__init__(daemon=True, name="InputLoop")
        self.shared_state = shared_state
        self.mouse_controller = mouse.Controller()
        self.activation = ActivationState(config.activation_bindings)
        self._wake = threading.Event()
        self._movement_pending = False
        self._movement_lock = threading.Lock()
        self._keyboard_listener = None
        self._mouse_listener = None
        self.started_auto_mode = False

    def _on_key_press(self, key):
        token = normalise_pynput_key(key)
        if token:
            self.activation.update(token, True)
            self._wake.set()

    def _on_key_release(self, key):
        token = normalise_pynput_key(key)
        if token:
            self.activation.update(token, False)
            self._wake.set()

    def _on_click(self, _x, _y, button, pressed):
        token = normalise_pynput_button(button)
        if token:
            self.activation.update(token, pressed)
            self._wake.set()

    def _on_move(self, _x, _y):
        with self._movement_lock:
            self._movement_pending = True
        self._wake.set()

    def _consume_movement(self):
        with self._movement_lock:
            moved = self._movement_pending
            self._movement_pending = False
        return moved

    def _dispatch_movement(self, active, activation_id):
        """Handle pointer movement without activating Manual mode by itself."""
        if config.auto_scan_mode and config.auto_scan_on_mouse_move:
            self.shared_state.request_screenshot()

        if active or (config.auto_scan_mode and config.auto_scan_mode_lookups_without_hotkey):
            hit_id = activation_id if active else 0
            self.shared_state.hit_scan_queue.put(PipelineValue(hit_id, REUSE_LAST_VALUE))

    def run(self):
        logger.debug("Input thread started.")
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self._mouse_listener = mouse.Listener(on_move=self._on_move, on_click=self._on_click)
        self._keyboard_listener.start()
        self._mouse_listener.start()
        previous_active = self.activation.active
        observed_activation_id = self.activation.activation_id
        try:
            while self.shared_state.running:
                self._wake.wait(0.1)
                self._wake.clear()
                if not config.is_enabled:
                    previous_active = self.activation.active
                    observed_activation_id = self.activation.activation_id
                    self.shared_state.set_activation(observed_activation_id, False)
                    continue
                active = self.activation.active
                activation_id = self.activation.activation_id
                if activation_id != observed_activation_id:
                    self.shared_state.set_activation(activation_id, active)
                    if not config.auto_scan_mode:
                        logger.info("Input: activation %s pressed; triggering screenshot", activation_id)
                        self.shared_state.request_screenshot(activation_id)
                    else:
                        # Reuse the latest auto-scan OCR immediately, but tag the
                        # hit test as a fresh activation for lookup/audio delivery.
                        self.shared_state.hit_scan_queue.put(PipelineValue(activation_id, REUSE_LAST_VALUE))
                    observed_activation_id = activation_id
                elif previous_active and not active:
                    self.shared_state.set_activation(activation_id, False)
                    logger.info("Input: activation %s released", activation_id)

                if not self.started_auto_mode and config.auto_scan_mode:
                    self.shared_state.request_screenshot()
                self.started_auto_mode = config.auto_scan_mode
                if self._consume_movement():
                    self._dispatch_movement(active, activation_id)
                previous_active = active
        except Exception:
            logger.exception("The input loop stopped unexpectedly")
        finally:
            for listener in (self._keyboard_listener, self._mouse_listener):
                if listener:
                    listener.stop()
            for listener in (self._keyboard_listener, self._mouse_listener):
                if listener:
                    listener.join(timeout=2)
            logger.debug("Input thread stopped.")

    def stop(self):
        self._wake.set()
        for listener in (self._keyboard_listener, self._mouse_listener):
            if listener:
                listener.stop()

    def is_virtual_hotkey_down(self):
        return self.activation.active or (config.auto_scan_mode and config.auto_scan_mode_lookups_without_hotkey)

    def reapply_settings(self):
        logger.debug("InputLoop: applying activation bindings %r", config.activation_bindings)
        transition = self.activation.set_bindings(config.activation_bindings)
        if transition.became_active:
            self.shared_state.set_activation(transition.activation_id, True)
        elif transition.became_inactive:
            self.shared_state.set_activation(transition.activation_id, False)
        self._wake.set()

    def get_mouse_pos(self):
        pos = self.mouse_controller.position
        return int(pos[0]), int(pos[1])
