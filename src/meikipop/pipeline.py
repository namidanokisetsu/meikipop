"""Generation-aware messages passed between the worker threads."""
from dataclasses import dataclass
from typing import Any


REUSE_LAST_VALUE = object()


@dataclass(frozen=True)
class PipelineValue:
    activation_id: int
    value: Any


@dataclass(frozen=True)
class LookupResult:
    activation_id: int
    text: str | None
    entries: tuple
