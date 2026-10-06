"""Coalescing worker for local recordings and cancellable online downloads."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from meikipop.audio.repository import AudioClip, AudioRepository, AudioRepositoryError
from meikipop.utils.lastest_queue import LatestValueQueue

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioRequest:
    activation_id: int
    key: tuple[str, str] | None
    database_path: str
    preferred_sources: tuple[str, ...]
    strict_sources: bool = False
    language: str = ""
    iso3: str = ""
    online: bool = False


class AudioWorker(threading.Thread):
    def __init__(self, clip_callback: Callable, status_callback: Callable, result_callback=None, sources_callback=None):
        super().__init__(daemon=True, name="AudioRepository")
        self._requests = LatestValueQueue()
        self._clip_callback = clip_callback
        self._status_callback = status_callback
        self._result_callback = result_callback
        self._sources_callback = sources_callback
        self._running = True
        self._repository = AudioRepository()
        self._last_error = None
        self._reported_missing: set[tuple[str, str]] = set()
        self._latest_request = None
        self._online = None

    def submit(self, request: AudioRequest):
        self._latest_request = request
        self._requests.put(request)

    def cancel(self):
        self._latest_request = None

    def stop(self):
        self._running = False
        self._requests.put(None)

    def run(self):
        while self._running:
            request = self._requests.get()
            if request is None or not self._running:
                break
            if request.online:
                self._online_result(request)
                continue
            try:
                if self._repository.path != str(Path(request.database_path).expanduser().resolve()):
                    self._repository.open(request.database_path)
                    sources = self._repository.sources()
                    self._last_error = None
                    self._status_callback(f"Audio database ready. Sources: {', '.join(sources)}")
                if request.key is None and self._sources_callback:
                    self._sources_callback(request.database_path, self._repository.sources())
                if request.key is not None:
                    clip = self._repository.load(
                        request.activation_id, *request.key, request.preferred_sources, strict_sources=request.strict_sources
                    )
                    if self._result_callback:
                        self._result_callback(request, clip)
                    elif clip:
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
                if request.key is not None and self._result_callback:
                    self._result_callback(request, None)
            except Exception:
                self._status_callback("Audio lookup failed; see log")
                logger.exception("Pronunciation audio lookup failed")
                if request.key is not None and self._result_callback:
                    self._result_callback(request, None)
        self._repository.close()

    def _online_result(self, request):
        from meikipop.audio.online import OnlineAudio
        if self._online is None:
            self._online = OnlineAudio()
        cancelled = lambda: not self._running or self._latest_request is not request
        clip = None
        try:
            result = self._online.lookup(request.key[0], request.language, request.iso3, cancelled)
            if result:
                filename, source, data, credit, page_url = result
                clip = AudioClip(request.activation_id, request.key, filename, source, data, credit, page_url)
        except Exception:
            logger.debug("Online pronunciation unavailable", exc_info=True)
        if not cancelled() and self._result_callback:
            self._result_callback(request, clip)
