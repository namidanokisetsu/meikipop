"""Explicitly export installed Turkish OCR models in an isolated conversion environment.

Run with Paddle 3.1.1 and Paddle2ONNX 2.1.0; neither is imported during lookup.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from meikipop.ocr.turkish_paddle import MODELS, PADDLE_FILES, file_hash


def export_models(source, output):
    import paddle
    import paddle2onnx

    versions = {"paddle": paddle.__version__, "paddle2onnx": paddle2onnx.__version__, "opset": 19}
    if versions["paddle"] != "3.1.1" or versions["paddle2onnx"] != "2.1.0":
        raise RuntimeError("Use an isolated environment with paddlepaddle==3.1.1 and paddle2onnx==2.1.0")
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError("Choose a new export directory")
    source_files = {f"{name}/{filename}": file_hash(source / name / filename)
                    for name in MODELS.values() for filename in PADDLE_FILES}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary) / "export"
        stage.mkdir()
        files = {}
        for name in MODELS.values():
            target = stage / name
            target.mkdir()
            shutil.copyfile(source / name / "inference.yml", target / "inference.yml")
            paddle2onnx.export(str(source / name / "inference.json"),
                              str(source / name / "inference.pdiparams"),
                              save_file=str(target / "inference.onnx"), opset_version=19,
                              enable_onnx_checker=True, optimize_tool=None)
            files[f"{name}/inference.onnx"] = file_hash(target / "inference.onnx")
        info = dict(schema=1, models=MODELS, source_files=source_files, files=files, exporter=versions)
        (stage / "export.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        stage.replace(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="Directory containing both installed Paddle model folders")
    parser.add_argument("--output", type=Path, required=True, help="New export directory")
    args = parser.parse_args(argv)
    print(export_models(args.source_dir, args.output))


if __name__ == "__main__":
    main()
