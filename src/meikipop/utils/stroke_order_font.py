"""Optional app-private Kanji Stroke Order font; runtime never downloads files."""
import hashlib
from pathlib import Path

VERSION = "4.005"
PACKAGE = f"KanjiStrokeOrders-{VERSION}"
FONT_FILENAME = f"KanjiStrokeOrders_v{VERSION}.ttf"
FILES = {
    FONT_FILENAME: "15525b225e9a9f08445eabdb5cac5c145431ac845107e3109b3fdcbfb77ac733",
    "LICENCE.txt": "06911c4187807499c44fd36897df4b4ad56d606b3e2d941847f990b35bfcc622",
    f"README_en_v{VERSION}.txt": "a1ded74a939937c22a975cca1656168ac59588354579d6468eaffb90b4e5117b",
}
_verified = None
_registered = None


def font_directory(directory=None):
    if directory is None:
        from meikipop.utils.paths import paths
        directory = paths.data_dir
    return Path(directory) / "fonts" / PACKAGE


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _signature(directory):
    stats = [(directory / name).stat() for name in FILES]
    return (str(directory.resolve()), *((stat.st_size, stat.st_mtime_ns) for stat in stats))


def font_ready(directory=None):
    global _verified
    folder = font_directory(directory)
    try:
        signature = _signature(folder)
        if _verified is None or _verified[0] != signature:
            valid = all((folder / name).is_file() and file_hash(folder / name) == digest for name, digest in FILES.items())
            _verified = (signature, valid)
        return _verified[1]
    except OSError:
        return False


def stroke_order_family(character="", directory=None):
    """Register installed glyphs lazily on the Qt GUI thread, with normal-font fallback."""
    global _registered
    if not font_ready(directory) or len(character) > 1:
        return ""
    from PyQt6.QtCore import QThread
    from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication, QRawFont
    app = QGuiApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        return ""
    folder = font_directory(directory)
    try:
        signature = _signature(folder)
    except OSError:
        return ""
    if _registered is None or _registered[0] != signature:
        if _registered is not None:
            QFontDatabase.removeApplicationFont(_registered[1])
        font_id = QFontDatabase.addApplicationFont(str(folder / FONT_FILENAME))
        families = QFontDatabase.applicationFontFamilies(font_id)
        family = families[0] if families else ""
        _registered = (signature, font_id, family, QRawFont.fromFont(QFont(family)) if family else None)
    family, raw = _registered[2:]
    return family if family and (not character or raw.supportsCharacter(ord(character))) else ""
