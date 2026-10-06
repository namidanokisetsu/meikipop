"""Reorder local recording sources and the system voice without syntax entry."""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QHBoxLayout, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout, QWidget
from meikipop.audio.sources import source_label
from meikipop.audio.worker import AudioRequest, AudioWorker


class AudioSources(QWidget):
    changed = pyqtSignal()
    sources_ready = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.worker = None
        self.path = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.items = QListWidget()
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.items.setMaximumHeight(130)
        self.items.setToolTip("Sources are tried from top to bottom")
        layout.addWidget(self.items)
        arrows = QVBoxLayout()
        for label, delta in (("↑", -1), ("↓", 1)):
            button = QToolButton()
            button.setText(label)
            button.setToolTip("Move source up" if delta < 0 else "Move source down")
            button.clicked.connect(lambda _, step=delta: self.move(step))
            arrows.addWidget(button)
        arrows.addStretch()
        layout.addLayout(arrows)
        self.items.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self.changed.emit))
        self.sources_ready.connect(self.received)

    def order(self):
        return [self.items.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.items.count())]

    def load(self, sources, path):
        self.items.clear()
        for source in sources:
            self.add(source)
        self.items.setCurrentRow(0)
        if path and path != self.path:
            self.path = path
            if self.worker is None:
                self.worker = AudioWorker(lambda _: None, self.report_status, sources_callback=self.sources_ready.emit)
                self.worker.start()
            self.worker.submit(AudioRequest(0, None, path, ()))
        elif not path:
            self.path = ""

    def report_status(self, text):
        if not text.startswith("Audio database ready"):
            self.failed.emit(text)

    def add(self, source, index=None):
        item = QListWidgetItem(source_label(source))
        item.setData(Qt.ItemDataRole.UserRole, source)
        self.items.insertItem(self.items.count() if index is None else index, item)

    def received(self, path, sources):
        if path != self.path:
            return
        order = self.order()
        position = order.index("database") if "database" in order else len(order)
        for source in sources:
            if "db:" + source not in order:
                self.add("db:" + source, position)
                position += 1

    def move(self, delta):
        row = self.items.currentRow()
        target = row + delta
        if row >= 0 and 0 <= target < self.items.count():
            self.items.insertItem(target, self.items.takeItem(row))
            self.items.setCurrentRow(target)
            self.changed.emit()

    def shutdown(self):
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=1)
            self.worker = None
        self.path = ""
