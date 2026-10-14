"""Versioned ranking counts, generated at packaging time or cached locally."""
import json
from pathlib import Path
import tempfile

# Bump when the lexicon, parser fixes or family-count algorithm changes.
FILENAME = "zeyrek-0.1.3-families-v1.json"


def load_counts(compute):
    from meikipop.utils.paths import paths
    cached = Path(paths.cache_dir) / "turkish" / FILENAME
    for path in (Path(paths.get_resource_path("turkish")) / FILENAME, cached):
        counts = read_counts(path)
        if counts is not None:
            return counts
    counts = compute()
    try:
        write_counts(cached, counts)
    except OSError:
        pass  # Read-only caches must not prevent offline lookup.
    return counts


def read_counts(path):
    try:
        counts = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(counts, dict) and counts and all(
                isinstance(key, str) and type(value) is int and value > 0 for key, value in counts.items()):
            return counts
    except (OSError, ValueError):
        pass
    return None


def write_counts(path, counts):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(counts, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
