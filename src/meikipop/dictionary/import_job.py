"""Isolate ZIP decompression and JSON parsing from the GUI's Python runtime."""
import json
import multiprocessing
from pathlib import Path
from queue import Empty, Full
from time import monotonic

from .archive import DictionaryArchive
from .library import import_yomitan, library_changed


def import_batch(paths, directory, language, progress, cancelled):
    imported, errors, warnings = 0, [], []
    for path in paths:
        if cancelled.is_set():
            break
        try:
            progress(f"Importing {Path(path).name} · 0%")
            with DictionaryArchive(path) as archive:
                metadata = json.loads(archive.read("index.json"))
            source = metadata.get("sourceLanguage") or language
            if not source:
                raise ValueError("No source language in this archive. Choose its language and import again.")
            notices = []
            import_yomitan(path, directory, language=source, progress=progress,
                           cancelled=cancelled.is_set, warnings=notices)
            if notices:
                warnings.append(f"{Path(path).name}: imported with a ZIP checksum warning.")
            imported += 1
        except InterruptedError:
            break
        except Exception as error:
            errors.append(f"{Path(path).name}: {error}")
    status = f"Imported {imported}."
    if cancelled.is_set():
        status += " Cancelled. Completed imports were kept."
    return "\n".join([status, *warnings, *errors]), bool(imported)


def _worker(paths, directory, language, recommended, messages, cancelled):
    last_update = 0

    def progress(text):
        nonlocal last_update
        now = monotonic()
        if now - last_update < 0.1 and not text.endswith((" 0%", " 100%")):
            return
        last_update = now
        try:
            messages.put_nowait(("progress", text))
        except Full:
            pass

    try:
        if recommended is not None:
            from .catalog import install_recommended
            install_recommended(recommended, directory, progress, cancelled)
            result = ("Dictionary installed.", True)
        else:
            result = import_batch(paths, directory, language, progress, cancelled)
    except Exception as error:
        result = (str(error), False)
    messages.put(("finished", result))


def background_import(paths, directory, language, recommended, progress, cancelled):
    context = multiprocessing.get_context("spawn")
    messages, child_cancelled = context.Queue(maxsize=32), context.Event()
    process = context.Process(target=_worker, args=(paths, directory, language, recommended, messages, child_cancelled))
    process.start()
    result = None
    try:
        while True:
            if cancelled.is_set():
                child_cancelled.set()
            try:
                kind, value = messages.get(timeout=0.1)
            except Empty:
                if not process.is_alive():
                    break
                continue
            if kind == "progress":
                progress(value)
            else:
                result = value
                break
        process.join()
        if result is None:
            raise RuntimeError(f"Dictionary import stopped unexpectedly ({process.exitcode}).")
        if result[1]:
            library_changed(directory)
        return result
    finally:
        child_cancelled.set()
        process.join(timeout=1)
        messages.close()
