"""Shared desktop app; runtimes are bundled, user dictionaries/models are not."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / "src/meikipop/resources"), "meikipop/resources"),
         (str(root / "src/meikipop/scripts/deconjugator.json"), "meikipop/scripts"),
         (str(root / "LICENSE"), "licenses/meikipop")]
binaries, hiddenimports = [], ["PyQt6.QtTextToSpeech", "pynput.keyboard._win32", "pynput.mouse._win32"]
for package in ("stanza", "paddle", "paddleocr", "paddlex", "imagesize", "mss", "meikiocr"):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for distribution in ("meikipop", "stanza", "torch", "paddlepaddle", "paddleocr", "paddlex"):
    datas += copy_metadata(distribution, recursive=True)

a = Analysis([str(root / "src/meikipop/scripts/quick_lookup.py")],
             pathex=[str(root / "src")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, runtime_hooks=[str(root / "packaging/runtime.py")],
             excludes=["tkinter", "tensorflow", "jax", "IPython", "pytest"], optimize=0)
pyz = PYZ(a.pure)
options = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
               icon=str(root / "src/meikipop/resources/icon.ico"))
exe = EXE(pyz, a.scripts, [], name="Meikipop", console=False, **options)
cli = EXE(pyz, a.scripts, [], name="Meikipop-cli", console=True, **options)
coll = COLLECT(exe, cli, a.binaries, a.datas, strip=False, upx=False, name="Meikipop")
