"""Pure lookup transitions; Qt owns timers, capture, focus and rendering."""
from dataclasses import dataclass


@dataclass
class LookupSession:
    enabled: bool = False
    holding: bool = False
    dismissed: bool = False
    generation: int = 0
    capture_generation: int | None = None

    def enable(self, enabled):
        self.enabled = bool(enabled)
        if not enabled:
            self.holding = self.dismissed = False

    def hold(self, active):
        if not active:
            self.dismissed = False
        if not self.enabled or active and self.dismissed or active == self.holding:
            return False
        self.holding = active
        return True

    def dismiss(self):
        self.dismissed = self.dismissed or self.holding
        self.holding = False

    def hide(self):
        self.dismissed = self.dismissed or self.holding

    def invalidate(self):
        self.generation += 1
        self.capture_generation = None

    def scanning(self, pinned=False):
        return self.enabled and self.holding and not self.dismissed and not pinned

    def accepts(self, generation, pinned=False):
        return generation == self.generation and self.scanning(pinned)

    def finish_capture(self, generation):
        if self.capture_generation == generation:
            self.capture_generation = None


def popup_mode(*, visible, preview, pinned, passive):
    if not visible:
        return "hidden"
    if preview:
        return "reading" if pinned else "preview"
    return "passive" if passive else "search"
