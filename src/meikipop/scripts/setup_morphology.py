"""Explicit model setup for optional shared-popup lemmatization."""
import argparse
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import subprocess
import sys


def _run(arguments, cancelled=None):
    # As in the Turkish setup helper, pythonw downloaders need real streams.
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        console = executable.with_name("Meikipop-cli.exe")
        if console.exists():
            executable = console
    if cancelled and cancelled.is_set():
        raise InterruptedError("Model setup cancelled.")
    process = subprocess.Popen([str(executable), *arguments], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    # Let the current install step finish so cancellation cannot leave half an
    # installed Python package. No following step starts after cancellation.
    output, _ = process.communicate()
    if cancelled and cancelled.is_set():
        raise InterruptedError("Model setup cancelled.")
    if process.returncode:
        detail = output.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "Model setup failed.")


def install(language, progress=None, cancelled=None):
    from meikipop.language.stanza_analyzer import STANZA_VERSION
    from meikipop.language.support import STANZA_LANGUAGES
    if language == "ja" or language not in STANZA_LANGUAGES:
        raise ValueError("Choose a language with base-form model support.")
    if getattr(sys, "frozen", False):
        if progress:
            progress("Downloading base-form model…")
        _run(["--setup-morphology", language], cancelled)
        return
    def installed(package):
        try:
            return version(package).split("+")[0]
        except PackageNotFoundError:
            return None
    if installed("stanza") != STANZA_VERSION or installed("torch") != "2.8.0":
        if progress:
            progress("Installing base-form support…")
        if not installed("pip"):
            _run(["-m", "ensurepip"], cancelled)
        pip = ["-m", "pip", "install", "--disable-pip-version-check"]
        if installed("torch") != "2.8.0":
            cpu = ["--index-url", "https://download.pytorch.org/whl/cpu"] if sys.platform != "darwin" else []
            _run([*pip, "torch==2.8.0", *cpu], cancelled)
        _run([*pip, f"stanza=={STANZA_VERSION}"], cancelled)
    if progress:
        progress("Downloading base-form model…")
    _run(["-m", "meikipop.scripts.setup_morphology", language], cancelled)


def main():
    from meikipop.dictionary.library import language_code
    from meikipop.language.stanza_analyzer import setup_models
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", type=language_code)
    parser.add_argument("--install", action="store_true", help="Also install optional Python dependencies")
    args = parser.parse_args()
    if args.language == "ja":
        parser.error("Japanese already uses the bundled deconjugation rules.")
    if args.install:
        install(args.language, progress=print)
    else:
        setup_models(language=args.language)
        from meikipop.language.stanza_analyzer import StanzaAnalyzer
        StanzaAnalyzer(language=args.language)


if __name__ == "__main__":
    main()
