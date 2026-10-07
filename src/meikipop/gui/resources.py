"""Resource readiness and explicit downloads in one settings tab."""
import json
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


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
        layout = QVBoxLayout(self)
        self.indicators, self.downloads, self.uses = {}, {}, {}
        self.active = QLabel()
        self.active.setWordWrap(True)
        layout.addWidget(self.active)
        layout.addWidget(QLabel("Dictionaries"))
        row = QHBoxLayout()
        self.dictionary = QComboBox()
        self.dictionary.currentIndexChanged.connect(self.refresh_dictionary_state)
        row.addWidget(self.dictionary, 1)
        self.dictionary_install = QPushButton("Download dictionary")
        self.dictionary_install.clicked.connect(lambda: owner.begin_operation([], recommended=self.dictionary.currentData()))
        row.addWidget(self.dictionary_install)
        layout.addLayout(row)
        layout.addWidget(self.indicator("dictionary"))
        layout.addWidget(QLabel("Screen recognition"))
        row = QHBoxLayout()
        self.ocr = QComboBox()
        self.ocr.currentIndexChanged.connect(self.select_ocr)
        row.addWidget(self.ocr, 1)
        self.ocr_install = QPushButton()
        self.ocr_install.clicked.connect(lambda: owner.begin_operation([], ocr=self.ocr.currentData()))
        row.addWidget(self.ocr_install)
        layout.addLayout(row)
        layout.addWidget(self.indicator("ocr"))
        row = QHBoxLayout()
        self.base_forms = QLabel("Base forms")
        row.addWidget(self.base_forms)
        row.addWidget(self.indicator("morphology"), 1)
        self.base_install = QPushButton("Download Stanza")
        self.base_install.clicked.connect(lambda: owner.begin_operation([], morphology=owner.profile.currentData()))
        row.addWidget(self.base_install)
        layout.addLayout(row)
        layout.addWidget(QLabel("Translation models (shared by all profiles)"))
        for name, label, size in (("lightweight", "Hy-MT2 1.8B", "1.9 GB"), ("quality", "Hy-MT2 7B", "8 GB")):
            row = QHBoxLayout()
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(self.indicator(name))
            row.addLayout(column, 1)
            use = QPushButton("Use")
            use.clicked.connect(lambda checked=False, name=name: self.select_translation(name))
            self.uses[name] = use
            row.addWidget(use)
            download = QPushButton(f"Download {size}")
            download.clicked.connect(lambda checked=False, name=name: owner.begin_operation([], profile=name))
            self.downloads[name] = download
            row.addWidget(download)
            layout.addLayout(row)
        layout.addStretch()
        self.refresh()

    def indicator(self, name):
        label = QLabel()
        self.indicators[name] = label
        return label

    def state(self, name, ready, text):
        label = self.indicators[name]
        label.setText(("\u25cf " if ready else "\u25cb ") + text)
        label.setStyleSheet("color:#80D69B;" if ready else "color:#AAAAAA;")

    def select_ocr(self):
        provider = self.owner.current_ocr_control()
        provider.setCurrentIndex(provider.findData(self.ocr.currentData()))

    def select_translation(self, name):
        self.owner.translation_mode.setCurrentIndex(self.owner.translation_mode.findData(name))
        self.refresh()

    def refresh(self):
        owner = self.owner
        code = owner.profile.currentData()
        if not code:
            return
        busy = owner.operation is not None
        self.active.setText(f"OCR: {owner.current_ocr_control().currentText()}\nTranslation: {owner.translation_mode.currentText()}")
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
        with QSignalBlocker(self.ocr):
            self.ocr.clear()
            for index in range(provider.count()):
                self.ocr.addItem(provider.itemText(index), provider.itemData(index))
                self.ocr.model().item(index).setEnabled(provider.model().item(index).isEnabled())
            self.ocr.setCurrentIndex(provider.currentIndex())
        ready = ocr_ready(provider.currentData(), owner.screenai_directory.text())
        self.state("ocr", ready, "Installed and selected" if ready else "Selected, download needed")
        self.ocr_install.setText("Download " + provider.currentText().split(" (")[0])
        self.ocr_install.setEnabled(not busy and not ready and provider.currentData() != "vision")
        self.ocr.setEnabled(not busy)
        from meikipop.language.stanza_analyzer import model_status
        from meikipop.language.support import STANZA_LANGUAGES
        supported = code in STANZA_LANGUAGES and code != "ja"
        ready = code == "ja" or supported and model_status(code) == "Installed"
        self.state("morphology", ready, "Built-in Japanese rules" if code == "ja" else
                   "Installed and used" if ready else "Not installed" if supported else "Unavailable")
        self.base_install.setEnabled(supported and not ready and not busy)
        for name in self.downloads:
            ready = translation_ready(name)
            selected = owner.translation_mode.currentData() == name
            self.state(name, ready, "Installed, used by this profile" if ready and selected else
                       "Installed" if ready else "Selected, download needed" if selected else "Not installed")
            self.uses[name].setText("Using" if selected else "Use")
            self.uses[name].setEnabled(ready and not selected and not busy)
            self.downloads[name].setEnabled(not ready and not busy)

    def refresh_dictionary_state(self):
        dictionary = self.dictionary.currentData()
        packs = getattr(self, "dictionary_packs", [])
        ready = dictionary is not None and any(meta["title"].startswith(dictionary.pack_title or dictionary.title) for meta in packs)
        self.state("dictionary", ready, "Installed" if ready else "Not installed" if dictionary is not None else "No recommended download")
        self.dictionary_install.setText("Update dictionary" if ready else "Download dictionary")
