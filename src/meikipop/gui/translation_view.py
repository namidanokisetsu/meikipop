"""A separate reading surface for the source sentence and its translation."""
from html import escape

from PyQt6.QtCore import QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWidget

from meikipop.config.config import config
from meikipop.gui.ruby import RubyBrowser
from meikipop.gui.section_scroll import ReadingPosition
from meikipop.gui.popup_style import surface_colors
from meikipop.gui.action_icons import action_icon


class TranslationView(RubyBrowser):
    def __init__(self):
        super().__init__(selection_lookup=False)
        self.setOpenLinks(False)
        self.setAccessibleName("Translation")
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
        if self.loading_timer.isActive() == busy:
            return
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

    def set_content(self, translation, message="", stale=False):
        muted = surface_colors(config.color_background, config.color_foreground)["muted"]
        foreground = muted if stale else config.color_foreground
        content = (translation, message, foreground, muted)
        if content == self._content:
            return
        position = ReadingPosition(self) if self._content else None
        parts = [f'<style>p {{margin:0;}} body {{color:{foreground};}}</style>']
        parts.append(f'<p>{escape(translation).replace(chr(10), "<br>")}</p>')
        if message:
            parts.append(f'<p>{escape(message).replace(chr(10), "<br>")}</p>')
        self.setHtml(''.join(parts))
        if position is not None:
            position.restore(self)
        self._content = content
        self.loading.setStyleSheet(f"color:{muted};background:transparent;border:none;")
        self._position_loading()


class SourceEditor(QTextEdit):
    submitted = pyqtSignal()
    composition_changed = pyqtSignal(bool)
    selecting = False
    composing = False

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(False)
        self.setPlaceholderText("Text to translate")
        self.setAccessibleName("Translation source")

    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        self.composition_changed.emit(self.composing)
        super().inputMethodEvent(event)

    def selected_text(self):
        return self.textCursor().selectedText().replace("\u2029", "\n").strip()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.submitted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class TranslationPanel(QWidget):
    source_changed = pyqtSignal(str)
    translate_requested = pyqtSignal()
    language_requested = pyqtSignal(str)
    swap_requested = pyqtSignal()
    copied = pyqtSignal()

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self.stale_output = ""
        self.source = SourceEditor()
        self.output = TranslationView()
        self.source_label, self.target_label = QToolButton(), QToolButton()
        self.source_label.setToolTip("Source language")
        self.target_label.setToolTip("Target language")
        self.source_label.clicked.connect(lambda: self.language_requested.emit("source"))
        self.target_label.clicked.connect(lambda: self.language_requested.emit("target"))
        self.copy_source = self._button("copy", "Copy input", lambda: self._copy(self.source.toPlainText()))
        self.copy_output = self._button("copy", "Copy output", self._copy_output)
        self.swap = self._button("swap", "Swap languages", self.swap_requested.emit)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(2)
        for editor, label, buttons in ((self.source, self.source_label, (self.copy_source,)),
                                        (self.output, self.target_label, (self.copy_output,))):
            pane = QWidget()
            layout = QVBoxLayout(pane)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(label)
            if editor is self.source:
                row.addWidget(self.swap)
            row.addStretch()
            for button in buttons:
                row.addWidget(button)
            layout.addLayout(row)
            layout.addWidget(editor, 1)
            self.splitter.addWidget(pane)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.splitterMoved.connect(self._save_split)
        self._restore_split()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self.source.textChanged.connect(lambda: self.source_changed.emit(self.source.toPlainText()))
        self.source.submitted.connect(self.translate_requested)
        self.translation = ""
        self.busy = False

    def _button(self, icon, tooltip, callback):
        button = QToolButton()
        button.setIcon(action_icon(icon, config.color_foreground))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.clicked.connect(callback)
        return button

    def _copy_output(self):
        self._copy(self.translation)

    def _copy(self, text):
        if text:
            QApplication.clipboard().setText(text)
            self.copied.emit()

    def set_content(self, text, translation, source, target, message=""):
        if self.source.toPlainText().strip() != text.strip():
            with QSignalBlocker(self.source):
                self.source.setPlainText(text)
        self.translation = translation
        self.copy_source.setEnabled(bool(text))
        self.copy_output.setEnabled(bool(translation))
        self.swap.setEnabled(source != "Automatic" and source != target)
        self.source_label.setText(source + " \u25be")
        self.target_label.setText(target + " \u25be")
        colors = surface_colors(config.color_background, config.color_foreground)
        muted = colors["muted"]
        for label in (self.source_label, self.target_label):
            label.setStyleSheet(f"QToolButton {{color:{muted};font-size:{max(10, round(config.font_size_sentence * .8))}px;"
                                f"border:1px solid {colors['border']};border-radius:3px;padding:1px 4px;}}"
                                f"QToolButton:hover {{background:{colors['hover']};}}")
        self.output.set_content(translation or self.stale_output, message, stale=not translation and bool(self.stale_output))

    def _split_key(self):
        return "translation_split/" + self.splitter.orientation().name

    def _save_split(self, *_):
        if self.settings is not None:
            self.settings.setValue(self._split_key(), self.splitter.sizes())

    def _restore_split(self):
        sizes = self.settings.value(self._split_key(), [1, 1]) if self.settings is not None else [1, 1]
        try:
            sizes = [int(value) for value in sizes]
            if len(sizes) == 2 and all(value > 0 for value in sizes):
                self.splitter.setSizes(sizes)
        except (TypeError, ValueError):
            pass

    def set_side_by_side(self, enabled):
        orientation = Qt.Orientation.Horizontal if enabled else Qt.Orientation.Vertical
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            self._restore_split()

    def set_busy(self, busy):
        self.busy = busy
        self.output.set_busy(busy)
