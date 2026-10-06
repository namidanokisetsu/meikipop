"""Immutable recognized pixels and source offsets, independent of the pointer."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RecognizedFrame:
    request: object
    paragraphs: tuple
    language: str
    provider: tuple
    scene: int
    captured_at: float

    @property
    def identity(self):
        return (self.request.generation, self.request.screen, self.request.geometry,
                self.request.crop, self.request.scale, self.language, self.provider, self.scene)

    def point(self, x, y):
        left, top, width, height = self.request.crop
        return ((x-left) / width, (y-top) / height)
