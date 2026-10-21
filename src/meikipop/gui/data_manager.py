"""Shared and per-language downloads, inspected on a worker."""
import threading

from PyQt6.QtCore import QObject, QSignalBlocker, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from meikipop.data_assets import inventory
from meikipop.gui.settings_section import SettingsSection


def size_label(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024


class InventoryTask(QObject):
    finished = pyqtSignal(object, str)

    def __init__(self, directory, profiles, screenai, parent):
        super().__init__(parent)
        self.arguments = directory, profiles, screenai
        self.thread = threading.Thread(target=self.run, name="data-inventory", daemon=True)

    def run(self):
        try:
            directory, profiles, screenai = self.arguments
            assets, error = inventory(directory, profiles, screenai=screenai), ""
        except Exception as exception:
            assets, error = (), str(exception)
        try:
            self.finished.emit(assets, error)
        except RuntimeError:
            pass


class DataPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self._task, self._pending = None, False
        self.rows, self.sections = {}, {}
        self.import_buttons = {}
        self.body = QVBoxLayout(self)
        header = QHBoxLayout()
        self.total = QLabel()
        header.addWidget(self.total, 1)
        self.reload = QPushButton("Refresh")
        self.reload.clicked.connect(self.refresh)
        header.addWidget(self.reload)
        self.body.addLayout(header)
        self.body.addWidget(QLabel("Shared models"))
        self.shared = QVBoxLayout()
        self.body.addLayout(self.shared)
        self.body.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        if self._task is not None:
            self._pending = True
            return
        from meikipop.language.profiles import configured_profiles
        self.reload.setEnabled(False)
        self._task = InventoryTask(self.owner.directory, configured_profiles(self.owner.settings),
                                   self.owner.screenai_directory.text(), self)
        self._task.finished.connect(self._finished)
        self._task.thread.start()

    def set_busy(self, busy):
        for button in self.import_buttons.values():
            button.setEnabled(not busy)
        for row in self.rows.values():
            row.enabled.setEnabled(not busy)
            row.remove.setEnabled(not busy)
            row.download.setEnabled(not busy)

    def _finished(self, assets, error):
        task, self._task = self._task, None
        task.deleteLater()
        self.reload.setEnabled(True)
        if self._pending:
            self._pending = False
            self.refresh()
            return
        if error:
            self.owner.status.setText(error)
        else:
            self._update(assets)

    def _update(self, assets):
        from meikipop.gui.quick_lookup import language_name
        scroll = self.owner.data_tab.verticalScrollBar()
        position = scroll.value()
        keys = {asset.key for asset in assets}
        for key in set(self.rows) - keys:
            row = self.rows.pop(key)
            row.container.removeWidget(row)
            row.hide()
            row.deleteLater()
        from meikipop.language.profiles import configured_profiles
        languages = sorted({asset.language for asset in assets if asset.language} | set(configured_profiles(self.owner.settings)))
        for code in set(self.sections) - set(languages):
            section = self.sections.pop(code)[0]
            self.body.removeWidget(section)
            section.hide()
            section.deleteLater()
            self.import_buttons.pop(code, None)
        for code in languages:
            if code not in self.sections:
                content = QWidget()
                layout = QVBoxLayout(content)
                layout.setContentsMargins(0, 0, 0, 0)
                section = SettingsSection(language_name(code), content)
                self.sections[code] = section, layout
                button = QPushButton("Import dictionaries…")
                button.setFlat(True)
                button.clicked.connect(lambda checked=False, code=code: self.owner.choose_dictionaries(language=code))
                layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
                self.import_buttons[code] = button
                section.toggle.setChecked(code == self.owner.profile.currentData())
                self.body.insertWidget(self.body.count() - 1, section)
        for asset in assets:
            if asset.key not in self.rows:
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                row.title, row.status = QLabel(), QLabel()
                row.title.setTextFormat(Qt.TextFormat.PlainText)
                row.enabled = QCheckBox()
                row.enabled.setToolTip("Enable dictionary")
                row.title.setWordWrap(True)
                layout.addWidget(row.enabled)
                layout.addWidget(row.title, 1)
                layout.addWidget(row.status)
                row.open, row.download, row.remove = QPushButton("Open"), QPushButton("Download"), QPushButton("Remove")
                for button in (row.open, row.download, row.remove):
                    layout.addWidget(button)
                self.rows[asset.key] = row
                target = self.sections[asset.language][1] if asset.language else self.shared
                target.addWidget(row)
                row.container = target
                row.enabled.toggled.connect(lambda enabled, row=row: self._enable(row.asset, enabled))
                row.open.clicked.connect(lambda checked=False, row=row: self._open(row.asset))
                row.download.clicked.connect(lambda checked=False, row=row: self._download(row.asset))
                row.remove.clicked.connect(lambda checked=False, row=row: self._remove(row.asset))
            row = self.rows[asset.key]
            row.asset = asset
            row.title.setText(asset.title)
            row.title.setToolTip("\n".join(map(str, asset.paths)))
            row.enabled.setVisible(asset.kind == "dictionary")
            with QSignalBlocker(row.enabled):
                row.enabled.setChecked(asset.status == "Enabled")
            row.status.setText(size_label(asset.size) if asset.kind == "dictionary" else
                               asset.status + (" · " + size_label(asset.size) if asset.size else ""))
            present = asset.size > 0 or asset.status in {"Enabled", "Disabled", "Linked"}
            row.open.setVisible(present and bool(asset.paths))
            row.remove.setVisible(present and asset.removable)
            row.download.setText("Repair" if present else "Download")
            row.download.setVisible((not present or asset.status == "Incomplete")
                                    and asset.kind in {"translation", "runtime", "ocr", "morphology", "fonts", "recommended"})
        self.total.setText(size_label(sum(asset.size for asset in assets)) + " used")
        self.set_busy(self.owner.operation is not None)
        self.layout().activate()
        scroll.setValue(position)

    def _open(self, asset):
        path = next((path for path in asset.paths if path.exists()), None)
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))

    def _download(self, asset):
        if asset.kind == "recommended":
            self.owner.begin_operation([], recommended=asset.value)
            return
        parameter = {"translation": "profile", "runtime": "profile", "morphology": "morphology", "ocr": "ocr", "fonts": "fonts"}[asset.kind]
        self.owner.begin_operation([], **{parameter: True if asset.kind == "fonts" else asset.value})

    def _remove(self, asset):
        if QMessageBox.question(self, "Remove data", f"Remove {asset.title}?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.owner.begin_operation([], asset=asset.key)

    def _enable(self, asset, enabled):
        if asset.kind == "dictionary":
            for index in range(self.owner.packs.count()):
                item = self.owner.packs.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == asset.value:
                    item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                    break
