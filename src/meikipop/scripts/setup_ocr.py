"""Explicit OCR model installation from the desktop settings worker."""
from pathlib import Path
import hashlib
import tempfile
from urllib.request import Request, urlopen
import zipfile

from meikipop.utils.progress import content_length, download_progress


def extract_component(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > 2 * 1024**3:
            raise ValueError("OCR component exceeds 2 GB.")
        for item in bundle.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe OCR component archive.")
        bundle.extractall(destination)


def install_screenai(progress, cancelled):
    from meikipop.ocr.providers.screenai.component import component_url, find_in_directory
    from meikipop.utils.paths import paths
    root = Path(paths.data_dir) / "screen_ai"
    root.mkdir(parents=True, exist_ok=True)
    url = component_url().replace("/p/", "/dl/") + "/+/latest"
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        stage = Path(temporary)
        archive = stage / "component.zip"
        digest = hashlib.sha256()
        with urlopen(Request(url, headers={"User-Agent": "Meikipop"}), timeout=30) as response, archive.open("wb") as output:
            total = 0
            size = content_length(response)
            progress(download_progress("Screen AI", total, size))
            while chunk := response.read(1024 * 1024):
                if cancelled.is_set():
                    raise InterruptedError("Download cancelled.")
                total += len(chunk)
                if total > 1024**3:
                    raise ValueError("OCR download exceeds 1 GB.")
                output.write(chunk)
                digest.update(chunk)
                progress(download_progress("Screen AI", total, size))
        extracted = stage / "component"
        extract_component(archive, extracted)
        if not find_in_directory(extracted):
            raise ValueError("The download does not contain a compatible OCR component.")
        if cancelled.is_set():
            raise InterruptedError("Download cancelled.")
        target = root / digest.hexdigest()
        if not target.exists():
            extracted.replace(target)
        return str(find_in_directory(target))


def install(provider, progress, cancelled):
    if cancelled.is_set():
        raise InterruptedError("Model setup cancelled.")
    if provider == "screenai":
        return install_screenai(progress, cancelled)
    if provider == "vision":
        return ""
    from meikipop.scripts.setup_morphology import _run
    import sys
    progress("Downloading OCR models…")
    arguments = ["--setup-ocr", provider]
    if not getattr(sys, "frozen", False):
        arguments = ["-m", "meikipop.scripts.quick_lookup", *arguments]
    _run(arguments, cancelled)
    return ""


def setup_models(provider):
    if provider == "paddle":
        from meikipop.ocr.turkish_paddle import setup_ocr
        setup_ocr()
    elif provider == "meikiocr":
        from meikiocr import MeikiOCR
        MeikiOCR(provider="CPUExecutionProvider")
    else:
        raise ValueError("Unknown OCR provider.")
