"""A separate reading surface for the source sentence and its translation."""
from html import escape

from PyQt6.QtCore import pyqtSignal

from meikipop.config.config import config
from meikipop.gui.ruby import RubyBrowser
from meikipop.gui.section_scroll import ReadingPosition


class TranslationView(RubyBrowser):
    language_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__(selection_lookup=False)
        self.setOpenLinks(False)
        self.setAccessibleName("Translation")
        self.anchorClicked.connect(self._language_clicked)
        self._content = None

    def _language_clicked(self, url):
        if url.scheme() == "language" and url.path() in ("source", "target"):
            self.language_requested.emit(url.path())

    def set_content(self, text, translation, source, target):
        content = (text, translation, source, target, config.color_foreground, config.color_highlight_word)
        if content == self._content:
            return
        position = ReadingPosition(self) if self._content and text == self._content[0] else None
        parts = [f'<style>p {{margin:6px 0;}} a {{color:{config.color_highlight_word};text-decoration:none;}}'
                 f'body {{color:{config.color_foreground};}} hr {{margin:12px 0;}}</style>']
        for role, label, value in (("source", source, text), ("target", target, translation)):
            if role == "target":
                parts.append('<hr>')
            parts.append(f'<p><a name="scroll-section-{role}"></a>'
                         f'<a href="language:{role}">{escape(label)}</a></p>'
                         f'<p>{escape(value).replace(chr(10), "<br>")}</p>')
        self.setHtml(''.join(parts))
        if position is not None:
            position.restore(self)
        self._content = content
