"""Local PaddleOCR 3.7: explicit setup, offline inference, real word boxes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from meikipop.ocr.scan_cache import ScanCache
from meikipop.pipeline import REUSE_LAST_VALUE

MODELS = {"det": "PP-OCRv6_small_det", "rec": "PP-OCRv6_small_rec"}


def model_root():
    from meikipop.utils.paths import paths
    return Path(paths.data_dir) / "languages/tr/paddle/3.7.0"


def prepare_environment():
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


def setup_ocr(root=None):
    prepare_environment()
    from paddlex.inference.utils.official_models import official_models
    root = Path(root or model_root())
    root.parent.mkdir(parents=True, exist_ok=True)
    # Activate a new immutable directory only after both downloads are complete.
    with tempfile.TemporaryDirectory(dir=root.parent) as temporary:
        stage = Path(temporary) / "models"
        stage.mkdir()
        for name in MODELS.values():
            shutil.copytree(official_models[name], stage / name)
        hashes = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in stage.rglob("*") if p.is_file()}
        if not hashes:
            raise ValueError("OCR model download is empty")
        (stage / "manifest.json").write_text(json.dumps({"models": MODELS, "files": hashes}, indent=2), encoding="utf-8")
        validate_models(stage)
        if root.exists():
            previous = Path(temporary) / "previous"
            root.replace(previous)
            try:
                stage.replace(root)
            except OSError:
                previous.replace(root)
                raise
        else:
            stage.replace(root)
    return str(root)


def validate_models(root):
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest["models"] != MODELS or not manifest["files"]:
            raise ValueError("Incompatible OCR models")
        for name in MODELS.values():
            for file in ("inference.json", "inference.pdiparams", "inference.yml"):
                if f"{name}/{file}" not in manifest["files"]:
                    raise ValueError("Incomplete OCR models")
        for relative, digest in manifest["files"].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Damaged OCR models")
    except (OSError, KeyError, ValueError) as error:
        raise RuntimeError("Local OCR models missing or damaged. Run meikipop setup-turkish-ocr.") from error


class LocalOCR:
    def __init__(self):
        root = model_root()
        validate_models(root)
        prepare_environment()
        from paddleocr import PaddleOCR
        self.engine = PaddleOCR(
            text_detection_model_name=MODELS["det"], text_detection_model_dir=str(root / MODELS["det"]),
            text_recognition_model_name=MODELS["rec"], text_recognition_model_dir=str(root / MODELS["rec"]),
            use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
            return_word_box=True, device="cpu", enable_mkldnn=False, cpu_threads=4,
        )
        self.scan_cache = ScanCache()

    def recognize(self, pixels):
        return list(self.engine.predict(pixels))

    def lookup_point(self, pixels, point):
        results = self.scan_cache.result if pixels is REUSE_LAST_VALUE else self.scan_cache.scan(pixels, self.recognize)
        for result in results or ():
            hit = hit_word(result, point)
            if hit:
                return hit
        return None


def hit_word(result, point):
    """Return complete line and source offset for the actual box under the pointer."""
    x, y = point
    for text, words, boxes in zip(result.get("rec_texts", []), result.get("text_word", []), result.get("text_word_boxes", [])):
        offset = 0
        for word, box in zip(words, boxes):
            start = text.find(word, offset)
            if start < 0:
                continue
            offset = start + len(word)
            left, top, right, bottom = box
            if left <= x <= right and top <= y <= bottom:
                return text, start
    return None
