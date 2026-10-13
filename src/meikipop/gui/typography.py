"""Document fonts with explicit language fallbacks; controls keep the system font."""
import sys
from PyQt6.QtGui import QFont, QFontDatabase


def document_families(language):
    if language == "ja":
        candidates = (("Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "Noto Sans JP") if sys.platform == "win32"
                      else ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", "Noto Sans JP")
                      if sys.platform == "darwin" else ("Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic"))
    else:
        candidates = ("Segoe UI",) if sys.platform == "win32" else ("Helvetica Neue",) if sys.platform == "darwin" else ("Noto Sans", "DejaVu Sans")
    available = set(QFontDatabase.families())
    return tuple(family for family in candidates if family in available)


def default_family(language):
    families = document_families(language)
    return families[0] if families else QFont().family()


def document_font(family, size, language):
    font = QFont()
    if family:
        font.setFamilies(list(dict.fromkeys((family, *document_families(language)))))
    font.setPixelSize(size)
    return font
