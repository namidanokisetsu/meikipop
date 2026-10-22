"""A separate reading surface for the source sentence and its translation."""
from html import escape

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QLabel

from meikipop.config.config import config
from meikipop.gui.ruby import RubyBrowser
from meikipop.gui.section_scroll import ReadingPosition
from meikipop.gui.popup_style import surface_colors


class TranslationView(RubyBrowser):
    language_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__(selection_lookup=False)
        self.setOpenLinks(False)
        self.setAccessibleName("Translation")
        self.anchorClicked.connect(self._language_clicked)
        self._content = None
        self.loading = QLabel(self.viewport())
        self.loading.setAccessibleName("Translating")
        self.loading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.loading.hide()
        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(350)
        self.loading_timer.timeout.connect(self._animate_loading)
        self._loading_frame = 0
        self.verticalScrollBar().valueChanged.connect(self._position_loading)

    def set_busy(self, busy):
        self.loading.setVisible(busy)
        if busy:
            self._loading_frame = 0
            self._animate_loading()
            self.loading_timer.start()
        else:
            self.loading_timer.stop()

    def _animate_loading(self):
        self.loading.setText("." * (self._loading_frame % 3 + 1))
        self._loading_frame += 1
        self._position_loading()

    def _position_loading(self):
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        rect = self.cursorRect(cursor)
        metrics = self.loading.fontMetrics()
        self.loading.setGeometry(rect.left(), rect.bottom(), metrics.horizontalAdvance("..."), metrics.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "loading"):
            self._position_loading()

    def _language_clicked(self, url):
        if url.scheme() == "language" and url.path() in ("source", "target"):
            self.language_requested.emit(url.path())

    def set_content(self, text, translation, source, target, message=""):
        muted = surface_colors(config.color_background, config.color_foreground)["muted"]
        label_size = max(10, round(config.font_size_sentence * .75))
        content = (text, translation, source, target, message, config.color_foreground, muted, label_size)
        if content == self._content:
            return
        position = ReadingPosition(self) if self._content and text == self._content[0] else None
        parts = [f'<style>p {{margin:2px 0;}} a {{color:{muted};font-size:{label_size}px;text-decoration:none;}}'
                 f'body {{color:{config.color_foreground};}} hr {{margin:6px 0;}}</style>']
        for role, label, value in (("source", source, text), ("target", target, translation)):
            if role == "target":
                parts.append('<hr>')
            parts.append(f'<p><a name="scroll-section-{role}"></a>'
                         f'<a href="language:{role}">{escape(label)}</a></p>'
                         f'<p>{escape(value).replace(chr(10), "<br>")}</p>')
        if message:
            parts.append(f'<p>{escape(message).replace(chr(10), "<br>")}</p>')
        self.setHtml(''.join(parts))
        if position is not None:
            position.restore(self)
        self._content = content
        self.loading.setStyleSheet(f"color:{muted};background:transparent;border:none;")
        self._position_loading()
