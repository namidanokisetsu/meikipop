"""Standalone Turkish entry point and bundled setup helper."""
import multiprocessing
import os
import sys


def main():
    multiprocessing.freeze_support()
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    if sys.argv[1:2] == ["--self-check"]:
        import importlib
        for name in ("PyQt6.QtWidgets", "stanza", "torch", "paddle", "paddleocr", "paddlex",
                     "meikipop.gui.turkish.window", "meikipop.dictionary.turkish_assets"):
            importlib.import_module(name)
        from meikipop.utils.paths import paths
        from pathlib import Path
        assert Path(paths.get_resource_path("turkish/wiktionary.json")).is_file()
        print("meikipop-turkish: bundled dependencies and resources OK")
        return 0
    from meikipop.scripts.turkish import main as turkish_main
    if sys.argv[1:2] == ["--setup"]:
        return turkish_main(sys.argv[2:])
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("meikipop-turkish")
    return turkish_main(["turkish-clipboard", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
