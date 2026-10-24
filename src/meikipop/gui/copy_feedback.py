"""Quiet copy confirmation anchored to the popup's content bounds."""
from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtWidgets import QLabel

from meikipop.config.config import config
from meikipop.gui.popup_style import surface_colors


class CopyFeedback(QLabel):
    def __init__(self, parent):
        super().__init__("Copied", parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.hide)
        parent.installEventFilter(self)
        self.hide()

    def show_confirmation(self):
        colors = surface_colors(config.color_background, config.color_foreground)
        self.setStyleSheet(f"background:{config.color_background};color:{config.color_foreground};"
                          f"border:1px solid {colors['border']};border-radius:4px;padding:4px 8px;")
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self.timer.start()

    def _place(self):
        bounds = self.parentWidget().layout().contentsRect()
        self.move(bounds.center().x() - self.width() // 2, bounds.bottom() - self.height() + 1)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        elif event.type() == QEvent.Type.Hide:
            self.timer.stop()
            self.hide()
        return False
