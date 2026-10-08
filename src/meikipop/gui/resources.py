"""Resource readiness and explicit downloads beside each feature."""
import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


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
        self.downloads, self.model_rows = {}, {}

        self.dictionary_section = QWidget(self)
        layout = QVBoxLayout(self.dictionary_section)
        layout.setContentsMargins(0, 0, 0, 0)
        self.dictionary_install = QPushButton("Download recommended dictionaries")
        self.dictionary_install.setFlat(True)
        self.dictionary_install.clicked.connect(self.install_dictionaries)
        layout.addWidget(self.dictionary_install, alignment=Qt.AlignmentFlag.AlignLeft)
        self.base_install = QPushButton("Download word-form support")
        self.base_install.setFlat(True)
        self.base_install.setToolTip("Recognize inflected words using an optional offline model")
        self.base_install.clicked.connect(lambda: owner.begin_operation([], morphology=owner.profile.currentData()))
        layout.addWidget(self.base_install, alignment=Qt.AlignmentFlag.AlignLeft)

        self.ocr_section = QWidget(self)
        layout = QHBoxLayout(self.ocr_section)
        layout.setContentsMargins(0, 0, 0, 0)
        self.ocr_install = QPushButton()
        self.ocr_install.clicked.connect(lambda: owner.begin_operation([], ocr=owner.current_ocr_control().currentData()))
        layout.addWidget(self.ocr_install)
        layout.addStretch()

        self.translation_section = QWidget(self)
        layout = QVBoxLayout(self.translation_section)
        layout.setContentsMargins(0, 0, 0, 0)
        for name in ("lightweight", "quality"):
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            download = QPushButton("Download model")
            download.setToolTip("Installed models are shared by all languages")
            download.clicked.connect(lambda checked=False, name=name: owner.begin_operation([], profile=name))
            self.downloads[name] = download
            self.model_rows[name] = widget
            row.addWidget(download)
            row.addStretch()
            layout.addWidget(widget)
        self.refresh()

    def install_dictionaries(self):
        if self.missing_dictionaries:
            self.owner.begin_operation([], recommended=self.missing_dictionaries)

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
        finally:
            library.close()
        from meikipop.dictionary.catalog import recommendations
        dictionaries = recommendations(code)
        self.missing_dictionaries = tuple(item for item in dictionaries if not any(item.matches(meta) for meta in packs))
        self.dictionary_install.setVisible(bool(self.missing_dictionaries))
        self.dictionary_install.setEnabled(bool(self.missing_dictionaries) and not busy)
        self.dictionary_install.setToolTip("\n".join(item.title for item in self.missing_dictionaries))
        owner.combine_frequencies.setVisible(sum(int(meta.get("frequencies", 0)) > 0 for meta in packs if meta["enabled"]) > 1)
        has_packs = bool(packs)
        owner.packs.setVisible(has_packs)
        for control in (owner.up, owner.down, owner.remove_button):
            control.setVisible(has_packs)
        provider = owner.current_ocr_control()
        ready = ocr_ready(provider.currentData(), owner.screenai_directory.text())
        self.ocr_install.setText("Download " + provider.currentText().split(" (")[0])
        self.ocr_section.setVisible(not ready and provider.currentData() != "screenai")
        self.ocr_install.setVisible(not ready)
        self.ocr_install.setEnabled(not busy and provider.currentData() != "vision")
        from meikipop.language.stanza_analyzer import model_status
        from meikipop.language.support import STANZA_LANGUAGES
        supported = code in STANZA_LANGUAGES and code != "ja"
        ready = supported and model_status(code) == "Installed"
        self.base_install.setVisible(supported and not ready)
        self.dictionary_section.setVisible(bool(self.missing_dictionaries) or supported and not ready)
        self.base_install.setEnabled(not busy)
        for name in self.downloads:
            ready = translation_ready(name)
            selected = owner.translation_mode.currentData() == name
            self.model_rows[name].setVisible(selected and not ready)
            self.downloads[name].setVisible(not ready)
            self.downloads[name].setEnabled(not ready and not busy)
