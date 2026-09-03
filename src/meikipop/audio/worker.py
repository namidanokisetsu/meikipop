"""Coalescing worker that keeps SQLite and BLOB reads off the GUI thread."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from meikipop.audio.repository import AudioRepository, AudioRepositoryError
from meikipop.utils.lastest_queue import LatestValueQueue

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioRequest:
    activation_id: int
    key: tuple[str, str] | None
    database_path: str
    preferred_sources: tuple[str, ...]


class AudioWorker(threading.Thread):
    def __init__(self, clip_callback: Callable, status_callback: Callable):
        super().__init__(daemon=True, name="AudioRepository")
        self._requests = LatestValueQueue()
        self._clip_callback = clip_callback
        self._status_callback = status_callback
        self._running = True
        self._repository = AudioRepository()
        self._last_error = None
        self._reported_missing: set[tuple[str, str]] = set()

    def submit(self, request: AudioRequest):
        self._requests.put(request)

    def stop(self):
        self._running = False
        self._requests.put(None)

    def run(self):
        while self._running:
            request = self._requests.get()
            if request is None or not self._running:
                break
            try:
                if self._repository.path != str(Path(request.database_path).expanduser().resolve()):
                    self._repository.open(request.database_path)
                    sources = self._repository.sources()
                    self._last_error = None
                    self._status_callback(f"Audio database ready. Sources: {', '.join(sources)}")
                if request.key is not None:
                    clip = self._repository.load(
                        request.activation_id, *request.key, request.preferred_sources
                    )
                    if clip:
                        self._clip_callback(clip)
                    elif request.key not in self._reported_missing:
                        logger.info("No pronunciation audio found for %s [%s]", *request.key)
                        self._reported_missing.add(request.key)
                        if len(self._reported_missing) > 500:
                            self._reported_missing.clear()
            except AudioRepositoryError as exc:
                message = str(exc)
                if request.key is None or message != self._last_error:
                    self._status_callback(message)
                if message != self._last_error:
                    logger.warning("Pronunciation audio unavailable: %s", exc)
                    self._last_error = message
            except Exception:
                self._status_callback("Audio lookup failed; see log")
                logger.exception("Pronunciation audio lookup failed")
        self._repository.close()
