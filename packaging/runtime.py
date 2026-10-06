"""Provide streams for model libraries in a windowed executable."""
import os
import sys
from pathlib import Path
from platformdirs import user_cache_dir

if sys.platform == "darwin":
    import certifi
    # The bundled OpenSSL cannot use the build runner's certificate paths.
    # Keep an explicitly configured trust store and verify downloads normally.
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())

class DiagnosticStream:
    def __init__(self, original, log):
        self.original, self.log = original, log

    def write(self, text):
        self.log.write(text)
        if self.original is not None:
            self.original.write(text)
        return len(text)

    def flush(self):
        self.log.flush()
        if self.original is not None:
            self.original.flush()

    def __getattr__(self, name):
        return getattr(self.original if self.original is not None else self.log, name)


if sys.stdout is None or sys.stderr is None or sys.platform == "darwin":
    log_dir = Path(user_cache_dir("meikipop", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "meikipop-runtime.log"
    if log_path.exists() and log_path.stat().st_size > 1_000_000:
        log_path.replace(log_path.with_suffix(".log.old"))
    stream = log_path.open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    sys.stderr = DiagnosticStream(sys.stderr, stream)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
