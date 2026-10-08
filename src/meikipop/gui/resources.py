"""Resource readiness and explicit downloads beside each feature."""
import json
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def ocr_ready(provider, component_directory=""):
    if provider == "vision":
        import sys
        return sys.platform == "darwin"
    if provider == "screenai":
        from meikipop.ocr.providers.screenai.component import find_component_directory
        try:
            return bool(find_component_directory(component_directory or None))
        except RuntimeError:
            return False
    if provider == "paddle":
        from meikipop.ocr.turkish_paddle import MODELS, PADDLE_FILES, model_root
        root = model_root()
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            return manifest.get("models") == MODELS and all(
                (root / name / filename).is_file() and (root / name / filename).stat().st_size > 0
                for name in MODELS.values() for filename in PADDLE_FILES)
        except (OSError, ValueError):
            return False
    if provider == "meikiocr":
        from huggingface_hub import try_to_load_from_cache
        models = (("rtr46/meiki.text.detect.v0", "meiki.text.detect.v0.1.960x544.onnx"),
                  ("rtr46/meiki.txt.recognition.v0", "meiki.text.rec.v0.960x32.onnx"),
                  ("rtr46/meiki.txt.recognition.v0", "meiki.text.rec.v0.vertical.32x480.onnx"))
        try:
            files = [try_to_load_from_cache(repo, filename) for repo, filename in models]
            return all(isinstance(file, str) and Path(file).is_file() and Path(file).stat().st_size > 0 for file in files)
        except (OSError, ValueError):
            return False
    return False


def translation_ready(profile):
    try:
        from meikipop.scripts.translation_server import _installed_paths
        _installed_paths(profile, None)
        return True
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


class ResourcesPanel(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.hide()
        self.indicators, self.downloads, self.model_rows = {}, {}, {}

        self.dictionary_section = QWidget(self)
        layout = QVBoxLayout(self.dictionary_section)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.dictionary = QComboBox()
        self.dictionary.setAccessibleName("Recommended dictionary")
        self.dictionary.currentIndexChanged.connect(self.refresh_dictionary_state)
        row.addWidget(self.dictionary, 1)
        self.dictionary_install = QPushButton("Download dictionary")
        self.dictionary_install.clicked.connect(lambda: owner.begin_operation([], recommended=self.dictionary.currentData()))
        row.addWidget(self.dictionary_install)
        layout.addLayout(row)
        layout.addWidget(self.indicator("dictionary"))
        row = QHBoxLayout()
        row.addWidget(self.indicator("morphology"), 1)
        self.base_install = QPushButton("Download base forms")
        self.base_install.clicked.connect(lambda: owner.begin_operation([], morphology=owner.profile.currentData()))
        row.addWidget(self.base_install)
        layout.addLayout(row)

        self.ocr_section = QWidget(self)
        layout = QHBoxLayout(self.ocr_section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.indicator("ocr"), 1)
        self.ocr_install = QPushButton()
        self.ocr_install.clicked.connect(lambda: owner.begin_operation([], ocr=owner.current_ocr_control().currentData()))
        layout.addWidget(self.ocr_install)

        self.translation_section = QWidget(self)
        layout = QVBoxLayout(self.translation_section)
        layout.setContentsMargins(0, 0, 0, 0)
        for name, size in (("lightweight", "1.9 GB"), ("quality", "8 GB")):
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(self.indicator(name), 1)
            download = QPushButton(f"Download {size}")
            download.setToolTip("Installed models are shared by all languages")
            download.clicked.connect(lambda checked=False, name=name: owner.begin_operation([], profile=name))
            self.downloads[name] = download
            self.model_rows[name] = widget
            row.addWidget(download)
            layout.addWidget(widget)
        self.refresh()

    def indicator(self, name):
        label = QLabel()
        self.indicators[name] = label
        return label

    def state(self, name, ready, text):
        label = self.indicators[name]
        label.setText(("\u25cf " if ready else "\u25cb ") + text)

    def refresh(self):
        owner = self.owner
        code = owner.profile.currentData()
        if not code:
            return
        busy = owner.operation is not None
        from meikipop.dictionary.library import Library
        library = Library(owner.directory)
        try:
            packs = [meta for path, meta, db in library.packs if meta['language'] == code]
            self.dictionary_packs = packs
        finally:
            library.close()
        with QSignalBlocker(self.dictionary):
            self.dictionary.clear()
            for index in range(owner.recommended.count()):
                self.dictionary.addItem(owner.recommended.itemText(index), owner.recommended.itemData(index))
        self.refresh_dictionary_state()
        self.dictionary_install.setEnabled(self.dictionary.currentData() is not None and not busy)
        provider = owner.current_ocr_control()
        ready = ocr_ready(provider.currentData(), owner.screenai_directory.text())
        self.state("ocr", ready, "Ready" if ready else "Download needed")
        self.ocr_install.setText("Download " + provider.currentText().split(" (")[0])
        self.ocr_install.setVisible(not ready)
        self.ocr_install.setEnabled(not busy and provider.currentData() != "vision")
        from meikipop.language.stanza_analyzer import model_status
        from meikipop.language.support import STANZA_LANGUAGES
        supported = code in STANZA_LANGUAGES and code != "ja"
        ready = code == "ja" or supported and model_status(code) == "Installed"
        self.state("morphology", ready, "Base forms: built in" if code == "ja" else
                   "Base forms: ready" if ready else "Base forms: download needed" if supported else "Base forms: unavailable")
        self.base_install.setVisible(supported and not ready)
        self.base_install.setEnabled(not busy)
        for name in self.downloads:
            ready = translation_ready(name)
            selected = owner.translation_mode.currentData() == name
            self.state(name, ready, "Installed, used by this profile" if ready and selected else
                       "Installed" if ready else "Selected, download needed" if selected else "Not installed")
            self.model_rows[name].setVisible(selected)
            self.downloads[name].setVisible(not ready)
            self.downloads[name].setEnabled(not ready and not busy)

    def refresh_dictionary_state(self):
        dictionary = self.dictionary.currentData()
        packs = getattr(self, "dictionary_packs", [])
        ready = dictionary is not None and any(meta["title"].startswith(dictionary.pack_title or dictionary.title) for meta in packs)
        self.state("dictionary", ready, "Installed" if ready else "Not installed" if dictionary is not None else "No recommended download")
        self.dictionary_install.setText("Update dictionary" if ready else "Download dictionary")
