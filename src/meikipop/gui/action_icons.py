"""Small monochrome action icons drawn locally for the shared popup."""
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer


_SHAPES = {
    "anki": '<rect x="3" y="5" width="15" height="16" rx="2"/><path d="M7 2h14v15M7 13h7M10.5 9.5v7"/>',
    "audio": '<path d="M3 9h4l5-4v14l-5-4H3ZM16 8c3 2 3 6 0 8M19 5c5 4 5 10 0 14"/>',
    "audio_sentence": '<path d="M3 9h4l5-4v14l-5-4H3ZM16 8c3 2 3 6 0 8M17 3h5M17 21h5"/>',
    "back": '<path d="m14 5-7 7 7 7M7 12h13"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M16 8V4H4v12h4"/>',
    "pin": '<path d="m8 3 8 0-1 7 3 3v2H6v-2l3-3-1-7ZM12 15v7"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="m9 3 1-1h4l1 1v2l2 1 2-1 2 3-1 2-1 1v2l1 1 1 2-2 3-2-1-2 1v2l-1 1h-4l-1-1v-2l-2-1-2 1-2-3 1-2 1-1v-2l-1-1-1-2 2-3 2 1 2-1V3Z"/>',
    "translate": '<path d="M3 4h10M8 2v2M11 4c0 6-3 9-8 11M5 7c1 3 4 6 7 7M13 21l4-11 4 11M14.5 17h5"/>',
}


def action_icon(name, color):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
           f'<g fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" '
           f'stroke-linejoin="round">{_SHAPES[name]}</g></svg>')
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
