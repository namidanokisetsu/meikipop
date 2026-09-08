"""Stage complete assets and retain one verified previous installation."""
import hashlib
import json
from pathlib import Path
import tempfile
import sqlite3


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_manifest(root, kind):
    files = {p.relative_to(root).as_posix(): checksum(p) for p in root.rglob("*") if p.is_file()}
    if not files:
        raise ValueError("Empty asset installation")
    (root / "asset.json").write_text(json.dumps(dict(schema=1, kind=kind, files=files), indent=2), encoding="utf-8")


def validate(root):
    info = json.loads((root / "asset.json").read_text(encoding="utf-8"))
    if info.get("schema") != 1 or not info.get("files"):
        raise ValueError("Unsupported asset manifest")
    for name, digest in info["files"].items():
        file = (root / name).resolve()
        if not file.is_relative_to(root.resolve()) or checksum(file) != digest:
            raise ValueError("Asset checksum mismatch")


def activate(stage, target):
    previous = target.with_name(target.name + ".previous")
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        retired = Path(temporary) / "retired"
        if previous.exists():
            previous.replace(retired)
        try:
            if target.exists():
                target.replace(previous)
            try:
                stage.replace(target)
            except OSError:
                if previous.exists():
                    previous.replace(target)
                raise
        except OSError:
            if retired.exists():
                retired.replace(previous)
            raise


def setup_asset(kind, source=None, output=None, model_dir=None, rollback=False):
    from meikipop.dictionary.turkish_store import default_dictionary_path
    from meikipop.dictionary.turkish_wordnet import default_wordnet_path, setup_wordnet
    from meikipop.dictionary.turkish_wiktionary import default_wiktionary_path, setup_wiktionary
    from meikipop.language.stanza_analyzer import default_model_dir, setup_models
    from meikipop.ocr.turkish_paddle import model_root, setup_ocr
    targets = {"dictionary": default_dictionary_path().parent, "wordnet": default_wordnet_path().parent,
               "wiktionary": default_wiktionary_path().parent, "model": default_model_dir(), "ocr": model_root()}
    target = Path(model_dir if kind == "model" and model_dir else output or targets[kind]).resolve()
    if target == target.parent or target in (Path.home().resolve(), Path.cwd().resolve()):
        raise ValueError("Choose a dedicated asset directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    if rollback:
        previous = target.with_name(target.name + ".previous")
        validate(previous)
        with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
            stage = Path(temporary) / "restore"
            previous.replace(stage)
            try:
                activate(stage, target)
            except Exception:
                if stage.exists():
                    stage.replace(previous)
                raise
        return str(target)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        stage = Path(temporary) / "asset"
        stage.mkdir()
        if kind == "dictionary":
            from meikipop.scripts.build_turkish_dictionary import main
            main(["--output", str(stage), *(["--source", str(source)] if source else [])])
        elif kind == "wordnet":
            setup_wordnet(source, stage / "wordnet.sqlite3")
        elif kind == "wiktionary":
            info = setup_wiktionary(source, stage / "dictionary.sqlite3")
            current = target / "dictionary.sqlite3"
            if current.exists():
                db = sqlite3.connect(current.as_uri() + "?mode=ro", uri=True)
                try:
                    row = db.execute("SELECT value FROM metadata WHERE key='source_sha256'").fetchone()
                    if row and json.loads(row[0]) == info["source_sha256"]:
                        return str(target)
                except sqlite3.Error:
                    pass
                finally:
                    db.close()
        elif kind == "model":
            setup_models(stage)
        elif kind == "ocr":
            setup_ocr(stage)
        write_manifest(stage, kind)
        # Legacy assets have no common manifest; preserve them for rollback too.
        if target.exists() and not (target / "asset.json").exists():
            write_manifest(target, kind)
        activate(stage, target)
    return str(target)
