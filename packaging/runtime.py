"""Provide streams for model libraries in a windowed executable."""
import os
import sys
from pathlib import Path
from platformdirs import user_cache_dir

if sys.stdout is None or sys.stderr is None:
    log_dir = Path(user_cache_dir("meikipop", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "meikipop-runtime.log"
    if log_path.exists() and log_path.stat().st_size > 1_000_000:
        log_path.replace(log_path.with_suffix(".log.old"))
    stream = log_path.open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
