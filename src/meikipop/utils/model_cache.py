"""Keep managed model downloads inside Meikipop's removable data."""
import os
from pathlib import Path
import sys


def configure_model_cache():
    from meikipop.utils.paths import paths
    root = Path(paths.cache_dir) / "huggingface"
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(Path(paths.cache_dir) / "paddlex")
    os.environ["HF_HUB_CACHE"] = str(root / "hub")
    os.environ["HF_XET_CACHE"] = str(root / "xet")
    if sys.platform == "win32":
        # RedirectionGuard rejects the shared Hub cache's user-created symlinks.
        os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
