"""Activation binding parsing and thread-safe global input state."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Iterable


KEYBOARD_TOKENS = frozenset({"ctrl", "shift", "alt", "cmd"})
MOUSE_TOKENS = frozenset({"middle", "mouse4", "mouse5"})
VALID_TOKENS = KEYBOARD_TOKENS | MOUSE_TOKENS
ALIASES = {
    "control": "ctrl",
    "option": "alt",
    "command": "cmd",
    "meta": "cmd",
    "button2": "middle",
    "x1": "mouse4",
    "x2": "mouse5",
}


def _normalise_token(token: str) -> str:
    token = token.strip().lower()
    return ALIASES.get(token, token)


def parse_activation_bindings(value: str | Iterable[str]) -> tuple[frozenset[str], ...]:
    """Parse comma-separated OR bindings whose plus-separated parts are ANDed."""
    raw_bindings = value.split(",") if isinstance(value, str) else list(value)
    parsed: list[frozenset[str]] = []
    for raw_binding in raw_bindings:
        parts = [_normalise_token(part) for part in str(raw_binding).split("+") if part.strip()]
        if not parts:
            continue
        unknown = set(parts) - VALID_TOKENS
        if unknown:
            raise ValueError(f"Unknown activation token(s): {', '.join(sorted(unknown))}")
        tokens = frozenset(parts)
        if tokens & KEYBOARD_TOKENS and tokens & MOUSE_TOKENS:
            raise ValueError("Mixed keyboard-and-mouse activation chords are not supported")
        if len(tokens & MOUSE_TOKENS) > 1:
            raise ValueError("Mouse buttons must be configured as independent bindings")
        if tokens not in parsed:
            parsed.append(tokens)
    if not parsed:
        raise ValueError("At least one activation binding is required")
    return tuple(parsed)


def serialise_activation_bindings(bindings: Iterable[Iterable[str]]) -> str:
    order = {name: index for index, name in enumerate(("ctrl", "shift", "alt", "cmd", "middle", "mouse4", "mouse5"))}
    return ",".join("+".join(sorted(binding, key=order.__getitem__)) for binding in bindings)


def normalise_activation_bindings(value: str) -> str:
    return serialise_activation_bindings(parse_activation_bindings(value))


@dataclass(frozen=True)
class ActivationTransition:
    became_active: bool = False
    became_inactive: bool = False
    activation_id: int = 0


class ActivationState:
    """Locked pressed-state set with edge detection for independent bindings."""

    def __init__(self, bindings: str = "shift"):
        self._lock = threading.RLock()
        self._pressed: set[str] = set()
        self._bindings = parse_activation_bindings(bindings)
        self._active = False
        self._activation_id = 0

    def set_bindings(self, bindings: str) -> ActivationTransition:
        parsed = parse_activation_bindings(bindings)
        with self._lock:
            was_active = self._active
            self._bindings = parsed
            self._active = self._evaluate()
            if self._active and not was_active:
                self._activation_id += 1
            return ActivationTransition(
                became_active=self._active and not was_active,
                became_inactive=was_active and not self._active,
                activation_id=self._activation_id,
            )

    def update(self, token: str, pressed: bool) -> ActivationTransition:
        token = _normalise_token(token)
        if token not in VALID_TOKENS:
            return ActivationTransition(activation_id=self.activation_id)
        with self._lock:
            was_active = self._active
            if pressed:
                self._pressed.add(token)
            else:
                self._pressed.discard(token)
            self._active = self._evaluate()
            if self._active and not was_active:
                self._activation_id += 1
            return ActivationTransition(
                became_active=self._active and not was_active,
                became_inactive=was_active and not self._active,
                activation_id=self._activation_id,
            )

    def _evaluate(self) -> bool:
        return any(binding <= self._pressed for binding in self._bindings)

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def activation_id(self) -> int:
        with self._lock:
            return self._activation_id


def normalise_pynput_key(key) -> str | None:
    name = getattr(key, "name", "")
    if name in {"shift", "shift_l", "shift_r"}:
        return "shift"
    if name in {"ctrl", "ctrl_l", "ctrl_r"}:
        return "ctrl"
    if name in {"alt", "alt_l", "alt_r", "alt_gr"}:
        return "alt"
    if name in {"cmd", "cmd_l", "cmd_r"}:
        return "cmd"
    return None


def normalise_pynput_button(button) -> str | None:
    name = getattr(button, "name", "")
    return {"middle": "middle", "x1": "mouse4", "x2": "mouse5"}.get(name)
