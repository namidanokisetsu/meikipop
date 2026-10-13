"""Explicit installation of the author's unmodified font and original license."""
from pathlib import Path, PurePosixPath
import tempfile
import threading
from urllib.request import Request, urlopen
import zipfile

from meikipop.utils.progress import content_length, download_progress
from meikipop.utils.stroke_order_font import FILES, PACKAGE, file_hash, font_directory, font_ready

SOURCE = "https://www.nihilist.org.uk/"
URL = "https://www.dropbox.com/scl/fi/htraf3uqop3nj3sgny1hn/KanjiStrokeOrders-4.005.zip?dl=1&rlkey=kp2gnmsbneeb2jyzyq6sfna0f"
ARCHIVE_SHA256 = "ee3a1e9c9fa6b137b9ba0b9f72eac21a96acd632f65333246fe980b8db0e9930"
MAX_DOWNLOAD = 16 * 1024**2
MAX_EXTRACTED = 32 * 1024**2


def extract_font(archive, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > MAX_EXTRACTED:
            raise ValueError("Stroke-order font archive is too large.")
        for item in bundle.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename or ":" in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe stroke-order font archive.")
        for name, digest in FILES.items():
            member = f"{PACKAGE}/{name}"
            if bundle.namelist().count(member) != 1:
                raise ValueError("Incomplete stroke-order font archive.")
            payload = bundle.read(member)
            destination.mkdir(parents=True, exist_ok=True)
            path = destination / name
            path.write_bytes(payload)
            if file_hash(path) != digest:
                raise ValueError("Stroke-order font verification failed.")


def install(progress=None, cancelled=None, directory=None):
    progress = progress or (lambda text: None)
    cancelled = cancelled or threading.Event()
    if cancelled.is_set():
        raise InterruptedError("Download cancelled.")
    target = font_directory(directory)
    if font_ready(directory):
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stroke-order-", dir=target.parent) as temporary:
        stage = Path(temporary)
        archive = stage / "font.zip"
        with urlopen(Request(URL, headers={"User-Agent": "Meikipop"}), timeout=30) as response, archive.open("wb") as stream:
            size, total = content_length(response), 0
            if size > MAX_DOWNLOAD:
                raise ValueError("Stroke-order font download is too large.")
            progress(download_progress("Stroke-order font", total, size))
            while chunk := response.read(1024 * 1024):
                if cancelled.is_set():
                    raise InterruptedError("Download cancelled.")
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise ValueError("Stroke-order font download is too large.")
                stream.write(chunk)
                progress(download_progress("Stroke-order font", total, size))
        if file_hash(archive) != ARCHIVE_SHA256:
            raise ValueError("Stroke-order font verification failed.")
        payload = stage / "installed"
        extract_font(archive, payload)
        if cancelled.is_set():
            raise InterruptedError("Download cancelled.")
        backup = stage / "previous"
        if target.exists():
            target.replace(backup)
        try:
            payload.replace(target)
        except OSError:
            if backup.exists():
                backup.replace(target)
            raise
    return str(target)


if __name__ == "__main__":
    install(progress=print)
