"""Bounded Wikimedia pronunciation lookup, run only on the audio worker."""
from collections import OrderedDict
from html import unescape
import json
import re
from time import monotonic
from urllib.parse import urlsplit

import requests


class OnlineAudio:
    API = "https://commons.wikimedia.org/w/api.php"
    MAX_AUDIO = 6 * 1024 * 1024

    def __init__(self):
        self.cache = OrderedDict()

    def _fetch(self, url, *, params=None, cancelled, deadline, audio=False):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"commons.wikimedia.org", "upload.wikimedia.org"}:
            raise ValueError("Unexpected recording host")
        limit = self.MAX_AUDIO if audio else 2 * 1024 * 1024
        remaining = deadline - monotonic()
        if cancelled() or remaining <= 0:
            raise InterruptedError()
        with requests.get(url, params=params, timeout=(min(1.5, remaining), min(2, remaining)), stream=True, allow_redirects=False,
                          headers={"User-Agent": "Meikipop/2.0 (desktop pronunciation lookup)"}) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("Unexpected recording redirect")
            chunks, size = [], 0
            for chunk in response.iter_content(32768):
                if cancelled() or monotonic() >= deadline:
                    raise InterruptedError()
                size += len(chunk)
                if size > limit:
                    raise ValueError("Recording response is too large")
                chunks.append(chunk)
        data = b"".join(chunks)
        if not audio:
            return json.loads(data)
        if not (data.startswith((b"OggS", b"RIFF", b"fLaC", b"ID3")) or
                len(data) > 1 and data[0] == 255 and data[1] & 224 == 224):
            raise ValueError("Invalid recording data")
        return data

    def lookup(self, term, language, iso3, cancelled=lambda: False):
        # Russian stress belongs in display/TTS, not in Commons file names.
        term = term.replace("\u0301", "") if language in ("ru", "uk", "be") else term
        key = (term, language, iso3)
        cached = self.cache.get(key)
        if cached and monotonic() - cached[0] < (3600 if cached[1] else 180):
            self.cache.move_to_end(key)
            return cached[1]
        if not term or len(term) > 200 or not re.fullmatch(r"[a-z]{2,3}", language):
            return None
        deadline = monotonic() + 5
        escaped = re.escape(term).replace("/", r"\/")
        patterns = [(f"{language}(-[a-zA-Z]{{2}})?-{escaped}[0-9]*\\.ogg", "Wiktionary")]
        if re.fullmatch(r"[a-z]{3}", iso3):
            patterns.append((f"LL-Q[0-9]+ \\({iso3}\\)-.+-{escaped}\\.wav", "Lingua Libre"))
        result = None
        try:
            pattern = "(" + "|".join(pattern for pattern, _ in patterns) + ")"
            response = self._fetch(self.API, params={"action": "query", "format": "json", "generator": "search",
                "gsrnamespace": 6, "gsrlimit": 10, "gsrsearch": f"intitle:/{pattern}/i",
                "prop": "imageinfo", "iiprop": "url|user|extmetadata"},
                cancelled=cancelled, deadline=deadline)
            if "error" in response:
                raise ValueError("Recording search failed")
            for pattern, source in patterns:
                for page in response.get("query", {}).get("pages", {}).values():
                    if not re.fullmatch("File:" + pattern, page.get("title", ""), re.IGNORECASE):
                        continue
                    for info in page.get("imageinfo", []):
                        url = info.get("url", "")
                        metadata = info.get("extmetadata", {})
                        artist = metadata.get("Artist", {}).get("value") or info.get("user", "")
                        credit = " · ".join(filter(None, (unescape(re.sub(r"<[^>]+>", "", str(value)))
                            for value in (artist, metadata.get("LicenseShortName", {}).get("value", "")))))
                        try:
                            data = self._fetch(url, cancelled=cancelled, deadline=deadline, audio=True)
                        except (requests.RequestException, ValueError):
                            continue
                        result = (urlsplit(url).path.rsplit("/", 1)[-1], source, data, credit,
                                  info.get("descriptionurl", ""))
                        break
                    if result:
                        break
                if result:
                    break
        except (requests.RequestException, ValueError, InterruptedError):
            if cancelled():
                return None
            # Cache failed lookups too, so repeated playback doesn't repeat the wait.
        self.cache[key] = (monotonic(), result)
        self.cache.move_to_end(key)
        while len(self.cache) > 128 or sum(len(item[1][2]) for item in self.cache.values() if item[1]) > 24 * 1024 * 1024:
            self.cache.popitem(last=False)
        return result
