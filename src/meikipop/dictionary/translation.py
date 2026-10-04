"""Explicit local translation through llama.cpp; no cloud or runtime downloads."""
from dataclasses import asdict, dataclass
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import threading
from urllib.parse import urlsplit

from .library import language_code


DEFAULT_ENDPOINT = "http://127.0.0.1:8766/v1"
DEFAULT_MODEL = "hy-mt2"
MODEL_NAMES = {"quality": "Hy-MT2-7B Q8_0", "lightweight": "Hy-MT2-1.8B Q8_0"}
LANGUAGE_NAMES = {
    "en": "English", "ja": "Japanese", "tr": "Turkish", "zh": "Chinese",
    "zh-hant": "Traditional Chinese", "zh-tw": "Traditional Chinese",
    "zh-hk": "Traditional Chinese", "fr": "French", "pt": "Portuguese",
    "es": "Spanish", "ru": "Russian", "ar": "Arabic", "ko": "Korean",
    "th": "Thai", "it": "Italian", "de": "German", "vi": "Vietnamese",
    "ms": "Malay", "id": "Indonesian", "tl": "Filipino", "fil": "Filipino",
    "hi": "Hindi", "pl": "Polish", "cs": "Czech", "nl": "Dutch",
    "km": "Khmer", "my": "Burmese", "fa": "Persian", "gu": "Gujarati",
    "ur": "Urdu", "te": "Telugu", "mr": "Marathi", "he": "Hebrew",
    "bn": "Bengali", "ta": "Tamil", "uk": "Ukrainian", "bo": "Tibetan",
    "kk": "Kazakh", "mn": "Mongolian", "ug": "Uyghur", "yue": "Cantonese",
    "el": "Greek", "sv": "Swedish", "fi": "Finnish", "da": "Danish",
    "no": "Norwegian", "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian",
}
# Publisher's 33 languages and five regional/minority varieties. Other local
# servers may support more; dictionary support is independent of translation.
MANAGED_LANGUAGES = frozenset("zh en fr pt es ja tr ru ar ko th it de vi ms id tl fil hi pl cs nl km my fa gu ur te mr he bn ta uk bo kk mn ug yue".split())


def default_translation_path():
    from meikipop.utils.paths import paths
    return Path(paths.data_dir) / "translation"


def local_endpoint(value):
    """Return a canonical numeric loopback URL, without any DNS lookup."""
    if not isinstance(value, str) or any(char.isspace() for char in value):
        raise ValueError("Use an HTTP address on localhost, such as " + DEFAULT_ENDPOINT)
    try:
        url = urlsplit(value)
        host = url.hostname
        if host == "localhost":
            host = "127.0.0.1"
        address = ipaddress.ip_address(host)
        port = url.port if url.port is not None else 80
    except (ValueError, TypeError) as error:
        raise ValueError("Translation servers must use localhost or a loopback IP address.") from error
    if (url.scheme != "http" or not address.is_loopback or url.username is not None
            or url.password is not None or url.query or url.fragment or "%" in value
            or "\\" in value or not 1 <= port <= 65535
            or any(part in (".", "..") for part in url.path.split("/"))):
        raise ValueError("Translation servers must use a local HTTP address without credentials or redirects.")
    host = f"[{address}]" if address.version == 6 else str(address)
    return f"http://{host}:{port}" + url.path.rstrip("/")


@dataclass(frozen=True)
class TranslationSettings:
    provider: str = "server"
    profile: str = "quality"
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    auto_start: bool = True

    def validated(self):
        if self.provider not in ("server", "custom") or self.profile not in tuple(MODEL_NAMES):
            raise ValueError("Choose a translation model in Setup.")
        if not isinstance(self.auto_start, bool):
            raise ValueError("Invalid local server startup setting.")
        if self.provider == "server":
            endpoint, model = DEFAULT_ENDPOINT, DEFAULT_MODEL
        else:
            endpoint = local_endpoint(self.endpoint)
            if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 200:
                raise ValueError("Enter a local server model name.")
            if any(ord(char) < 32 for char in self.model):
                raise ValueError("Invalid local server model name.")
            model = self.model.strip()
        return TranslationSettings(self.provider, self.profile, endpoint, model, self.auto_start)


def load_settings(directory=None):
    path = Path(directory or default_translation_path()) / "settings.json"
    try:
        if path.stat().st_size > 16384:
            raise ValueError("Translation settings are too large. Save them again in Setup.")
        values = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return TranslationSettings()
    except (OSError, ValueError) as error:
        raise ValueError("Cannot read translation settings. Save them again in Setup.") from error
    if not isinstance(values, dict):
        raise ValueError("Invalid translation settings. Save them again in Setup.")
    try:
        return TranslationSettings(**values).validated()
    except TypeError as error:
        raise ValueError("Invalid translation settings. Save them again in Setup.") from error


def save_settings(settings, directory=None):
    settings = settings.validated()
    directory = Path(directory or default_translation_path())
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(asdict(settings), output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, directory / "settings.json")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return settings


def _translation_content(response):
    try:
        choice = response["choices"][0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("The local model reached its output limit. Translate a shorter passage.")
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise RuntimeError("The local server returned an invalid translation response.") from error
    if not isinstance(content, str):
        raise RuntimeError("The local server returned no translated text.")
    content = content.strip()
    # Only explicit leading reasoning tags are removable. Keep prose, quotes,
    # and ordinary markup in the translation exactly as the model returned it.
    while content.startswith("<think>"):
        match = re.match(r"<think>.*?</think>\s*", content, re.DOTALL)
        if match is None:
            raise RuntimeError("The local model returned incomplete reasoning. Try a shorter passage.")
        content = content[match.end():]
    if not content:
        raise RuntimeError("The local server returned no translated text.")
    return content


class LocalTranslator:
    def __init__(self, directory=None):
        self.directory = Path(directory or default_translation_path())
        self.last_provider = ""
        self.last_model = ""
        self._connection = None
        self._connection_lock = threading.Lock()
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()
        with self._connection_lock:
            connection = self._connection
            if connection is not None:
                if connection.sock is not None:
                    try:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                connection.close()

    def cache_key(self):
        return load_settings(self.directory)

    def translate(self, text, source, target):
        self._cancelled.clear()
        self.last_provider = self.last_model = ""
        source, target = language_code(source), language_code(target)
        if not text.strip() or source == target:
            return text
        if len(text) > 2000:
            raise ValueError("Enter at most 2,000 characters.")
        target_name = LANGUAGE_NAMES.get(target) or LANGUAGE_NAMES.get(target.split("-", 1)[0])
        if not target_name:
            raise ValueError(f"Translation to {target} is not configured. Dictionary lookup is still available.")
        settings = load_settings(self.directory)
        if settings.provider == "server":
            for code in (source, target):
                if code.split("-", 1)[0] not in MANAGED_LANGUAGES:
                    raise ValueError(f"Hy-MT2 does not list support for {code}. Dictionary lookup is still available.")
        if settings.provider == "server" and settings.auto_start:
            from meikipop.scripts.translation_server import ensure_server
            ensure_server(endpoint=DEFAULT_ENDPOINT, profile=settings.profile, timeout=120,
                          directory=self.directory)
        prompt = (f"Translate the following text into {target_name}. Note that you should only output "
                  "the translated result without any additional explanation:\n" + text)
        # Publisher parameters mapped to llama.cpp's repeat_penalty spelling.
        # https://huggingface.co/tencent/Hy-MT2-7B-GGUF
        request = dict(model=settings.model, messages=[dict(role="user", content=prompt)],
                       temperature=0.7, top_p=0.6, top_k=20, repeat_penalty=1.05,
                       min_p=0.0, max_tokens=4096, stream=False)
        if settings.provider == "server":
            # Match Transformers' penalty -> temperature -> top-k -> top-p
            # ordering, rather than llama.cpp's extra default sampler filters.
            request.update(samplers=["penalties", "temperature", "top_k", "top_p"], repeat_last_n=8192)
        endpoint = urlsplit(settings.endpoint)
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=120)
        try:
            with self._connection_lock:
                if self._cancelled.is_set():
                    raise RuntimeError("Translation cancelled.")
                self._connection = connection
            # http.client bypasses environment proxies and never follows redirects.
            connection.request("POST", endpoint.path + "/chat/completions",
                               body=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                               headers={"Content-Type": "application/json", "Accept": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"Local translation server returned HTTP {response.status}. Check Setup.")
            payload = response.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise RuntimeError("The local translation response was too large.")
            try:
                result = json.loads(payload)
            except (ValueError, UnicodeError) as error:
                raise RuntimeError("The local server returned invalid JSON.") from error
            translated = _translation_content(result)
            if self._cancelled.is_set():
                raise RuntimeError("Translation cancelled.")
        except (OSError, http.client.HTTPException) as error:
            raise RuntimeError("Cannot reach the local translation server. Start it or check Setup.") from error
        finally:
            with self._connection_lock:
                self._connection = None
                connection.close()
        self.last_provider = settings.provider
        self.last_model = MODEL_NAMES[settings.profile] if settings.provider == "server" else settings.model
        return translated

