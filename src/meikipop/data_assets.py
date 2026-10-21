"""Inventory and removal of app-owned downloads without loading NLP or OCR models."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4


@dataclass(frozen=True)
class DataAsset:
    key: str
    title: str
    language: str = ""
    kind: str = ""
    value: object = ""
    paths: tuple = ()
    size: int = 0
    status: str = "Not installed"
    removable: bool = True


def _roots(data_root, cache_root):
    from meikipop.utils.paths import paths
    return Path(data_root or paths.data_dir).resolve(), Path(cache_root or paths.cache_dir).resolve()


def _size(path):
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for folder, _, files in os.walk(path, followlinks=False):
        for name in files:
            item = Path(folder) / name
            try:
                if not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                pass
    return total


def _pending_paths(data, cache):
    parents = [data, data / "translation", data / "translation/models", data / "fonts",
               cache / "huggingface", cache / "huggingface/hub", cache / "paddlex/official_models"]
    parents.extend((data / "languages").glob("*"))
    for parent in parents:
        for path in parent.glob(".meikipop-removed-*"):
            if not re.fullmatch(r"\.meikipop-removed-[0-9a-f]{32}", path.name):
                continue
            resolved = path.resolve()
            if not path.is_symlink() and any(resolved != root and resolved.is_relative_to(root) for root in (data, cache)):
                yield path


def cleanup_removed_data(*, data_root=None, cache_root=None):
    data, cache = _roots(data_root, cache_root)
    for path in _pending_paths(data, cache):
        try:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        except OSError:
            pass


def inventory(directory, profiles=(), *, data_root=None, cache_root=None, screenai=""):
    from meikipop.dictionary.library import Library
    from meikipop.scripts.translation_server import MODELS, RELEASE, _platform_key
    from meikipop.language.support import STANZA_LANGUAGES
    from meikipop.utils.stroke_order_font import PACKAGE
    data, cache = _roots(data_root, cache_root)
    assets, languages, installed_packs = [], set(profiles), []

    def add(key, title, language="", kind="", value="", paths=(), *, removable=True, status=None):
        paths = tuple(Path(path) for path in paths)
        size = sum(_size(path) for path in paths) if removable else 0
        present = size > 0 if removable else any(path.exists() for path in paths)
        assets.append(DataAsset(key, title, language, kind, value, paths, size,
                                status or ("Installed" if present else "Not installed"), removable))

    for name, model in MODELS.items():
        path = data / "translation/models" / model["file"]
        state = None if not path.exists() else "Installed" if path.stat().st_size == model["size"] else "Incomplete"
        add("translation:" + name, "Hy-MT2 1.8B" if name == "lightweight" else "Hy-MT2 7B",
            kind="translation", value=name, paths=(path,), status=state)
    runtimes = set((data / "translation").glob("runtime-*"))
    try:
        runtimes.add(data / "translation" / f"runtime-{RELEASE}-{_platform_key()}")
    except RuntimeError:
        pass
    for runtime in sorted(runtimes):
        ready = any(runtime.rglob("llama-server.exe")) or any(runtime.rglob("llama-server"))
        state = None if not runtime.exists() else "Installed" if ready else "Incomplete"
        add("runtime:" + runtime.name, "Translation runtime · " + runtime.name.removeprefix("runtime-"),
            kind="runtime", value="runtime", paths=(runtime,), status=state)
    meiki = tuple(
        cache / "huggingface/hub" / name for name in (
            "models--rtr46--meiki.text.detect.v0", "models--rtr46--meiki.txt.recognition.v0"))
    required = ((meiki[0], "meiki.text.detect.v0.1.960x544.onnx"),
                (meiki[1], "meiki.text.rec.v0.960x32.onnx"), (meiki[1], "meiki.text.rec.v0.vertical.32x480.onnx"))
    ready = all(any(path.glob("snapshots/*/" + name)) for path, name in required)
    state = "Installed" if ready else "Incomplete" if any(path.exists() for path in meiki) else None
    add("ocr:meikiocr", "MeikiOCR", kind="ocr", value="meikiocr", paths=meiki, status=state)
    from meikipop.ocr.turkish_paddle import MODELS as PADDLE_MODELS, PADDLE_FILES
    paddle = data / "languages/tr/paddle/3.7.0"
    try:
        manifest = json.loads((paddle / "manifest.json").read_text(encoding="utf-8"))
        ready = manifest.get("models") == PADDLE_MODELS and all(
            (paddle / name / filename).is_file() for name in PADDLE_MODELS.values() for filename in PADDLE_FILES)
    except (OSError, ValueError):
        ready = False
    state = "Installed" if ready else "Incomplete" if paddle.parent.exists() else None
    add("ocr:paddle", "PaddleOCR", kind="ocr", value="paddle", paths=(
        paddle.parent, *(cache / "paddlex/official_models" / name for name in PADDLE_MODELS.values())), status=state)
    from meikipop.ocr.providers.screenai.component import find_in_directory
    ready = find_in_directory(data / "screen_ai") is not None
    state = "Installed" if ready else "Incomplete" if (data / "screen_ai").exists() else None
    add("ocr:screenai", "Chrome Screen AI", kind="ocr", value="screenai", paths=(data / "screen_ai",), status=state)
    if screenai and not Path(screenai).resolve().is_relative_to(data / "screen_ai"):
        add("ocr:screenai-external", "Chrome Screen AI", kind="external", paths=(Path(screenai),),
            removable=False, status="Linked")
    if (cache / "huggingface/xet").exists():
        add("cache:downloads", "Model download cache", kind="cache", paths=(cache / "huggingface/xet",))
    if (data / "translation/downloads").exists():
        add("cache:translation", "Translation download cache", kind="cache", paths=(data / "translation/downloads",))
    for path in _pending_paths(data, cache):
        assets.append(DataAsset("pending:" + str(path), "Removed files", kind="pending", paths=(path,),
                                size=_size(path), status="Clears after restart", removable=False))
    library = Library(directory)
    try:
        for path, meta, _ in library.packs:
            installed_packs.append(meta)
            code = meta["language"]
            languages.add(code)
            add("dictionary:" + path.name, meta["title"], code, "dictionary", path.name,
                (path, path.with_suffix(".assets")), status="Enabled" if meta["enabled"] else "Disabled")
    finally:
        library.close()
    for path in (data / "languages").glob("*/stanza"):
        languages.add(path.parent.name)
    if (data / "fonts" / PACKAGE).exists():
        languages.add("ja")
    for code in sorted(languages):
        # Profile codes never supply unchecked filesystem paths.
        from meikipop.dictionary.library import language_code
        try:
            valid = language_code(code) == code
        except ValueError:
            valid = False
        if not valid:
            continue
        from meikipop.dictionary.catalog import recommendations
        for recommended in recommendations(code):
            if not any(recommended.matches(meta) for meta in installed_packs):
                add("recommended:" + code + ":" + recommended.title, recommended.title, code,
                    "recommended", recommended, removable=False)
        model = data / "languages" / code / "stanza"
        if code in STANZA_LANGUAGES and code not in {"ja", "tr"} or model.exists():
            from meikipop.language.stanza_analyzer import model_status, RESOURCES_VERSION
            state = None if not model.exists() else (
                "Installed" if model_status(code, model / RESOURCES_VERSION) == "Installed" else "Incomplete")
            legacy = code in {"ja", "tr"}
            add("stanza:" + code, "Stanza morphology (legacy)" if legacy else "Stanza morphology", code,
                "legacy" if legacy else "morphology", code, (model,), status=state)
        if code in {"ja", "tr"}:
            add("builtin:" + code, "Japanese word forms" if code == "ja" else "Zeyrek morphology", code,
                status="Built in", removable=False)
        if code == "ja":
            from meikipop.utils.stroke_order_font import font_ready
            path = data / "fonts" / PACKAGE
            state = None if not path.exists() else "Installed" if font_ready(data) else "Incomplete"
            add("font:ja", "Kanji stroke-order font", "ja", "fonts", paths=(path,), status=state)
    return tuple(assets)


def remove_asset(key, directory, refresh, cancelled, *, data_root=None, cache_root=None):
    if cancelled.is_set():
        raise InterruptedError("Removal cancelled.")
    data, cache = _roots(data_root, cache_root)
    assets = inventory(directory, data_root=data, cache_root=cache)
    asset = next((asset for asset in assets if asset.key == key), None)
    if asset is None or not asset.removable:
        raise ValueError("Choose an installed download.")
    if asset.kind == "dictionary":
        from meikipop.dictionary.library import remove_dictionary
        remove_dictionary(directory, asset.value, refresh, cancelled)
        return
    if asset.kind in {"translation", "runtime"}:
        from meikipop.scripts.translation_server import shutdown_server
        shutdown_server()
    staged = []
    try:
        for path in asset.paths:
            if cancelled.is_set():
                raise InterruptedError("Removal cancelled.")
            if not path.exists():
                continue
            resolved = path.resolve()
            if path.is_symlink() or not any(resolved != root and resolved.is_relative_to(root) for root in (data, cache)):
                raise ValueError("Download is outside Meikipop's data folders.")
            temporary = path.with_name(".meikipop-removed-" + uuid4().hex)
            path.rename(temporary)
            staged.append((path, temporary))
    except Exception:
        for original, temporary in reversed(staged):
            if temporary.exists() and not original.exists():
                temporary.rename(original)
        raise
    try:
        for _, temporary in staged:
            try:
                shutil.rmtree(temporary) if temporary.is_dir() else temporary.unlink()
            except PermissionError:
                # Mapped Windows files are collected after their process exits.
                pass
    finally:
        refresh()


def remove_language_data(language, directory, refresh, cancelled, *, data_root=None, cache_root=None):
    if cancelled.is_set():
        raise InterruptedError("Removal cancelled.")
    assets = inventory(directory, (language,), data_root=data_root, cache_root=cache_root)
    for asset in assets:
        if asset.language == language and asset.removable and any(path.exists() for path in asset.paths):
            remove_asset(asset.key, directory, refresh, cancelled, data_root=data_root, cache_root=cache_root)
