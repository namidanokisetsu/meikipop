"""Optional sentence navigation through the existing dictionary lookup."""
from html import escape

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTextBrowser

from meikipop.config.config import config
from meikipop.language.profiles import get_profile


class SentenceView(QTextBrowser):
    word_clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text, self.language, self.spans, self.selected = "", "", (), None
        self.setAccessibleName("Sentence words")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setMaximumHeight(110)
        self.setMinimumHeight(45)
        self.anchorClicked.connect(self._clicked)
        self.hide()

    def set_sentence(self, text, language, spans=None):
        if (text, language) != (self.text, self.language):
            self.selected = None
            self.spans = get_profile(language).word_spans(text)
        self.text, self.language = text, language
        if spans is not None:
            self.spans = spans
        self.render()

    def render(self):
        def plain(text):
            return escape(text).replace(" ", "&nbsp;").replace("\n", "<br>")
        pieces, offset = [], 0
        for start, end in self.spans:
            pieces.append(plain(self.text[offset:start]))
            color = config.color_highlight_word if self.selected == (start, end) else config.color_foreground
            pieces.append(f'<a href="word:{start}:{end}" style="color:{color};text-decoration:none;">'
                          + plain(self.text[start:end]) + '</a>')
            offset = end
        pieces.append(plain(self.text[offset:]))
        html = "".join(pieces)
        if html != getattr(self, "_html", None):
            self._html = html
            scroll = self.verticalScrollBar().value()
            self.setHtml(html)
            self.verticalScrollBar().setValue(scroll)

    def _clicked(self, url):
        if url.scheme() != "word":
            return
        try:
            span = tuple(map(int, url.path().split(":")))
        except ValueError:
            return
        if span not in self.spans:
            return
        self.selected = span
        self.render()
        self.word_clicked.emit(*span)
