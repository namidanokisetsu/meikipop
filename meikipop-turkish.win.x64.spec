# Build a directory bundle: model libraries should not unpack on every launch.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / "src/meikipop/resources"), "meikipop/resources"),
         (str(root / "LICENSE"), "licenses/meikipop")]
binaries, hiddenimports = [], ["PyQt6.QtTextToSpeech"]
for package in ("stanza", "paddle", "paddleocr", "paddlex", "imagesize", "mss"):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for distribution in ("meikipop", "torch", "paddlepaddle", "paddleocr", "paddlex", "stanza",
                     "imagesize", "opencv-contrib-python", "pyclipper", "pypdfium2",
                     "python-bidi", "shapely"):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(root / "src/meikipop/scripts/turkish_desktop.py")],
    pathex=[str(root / "src")], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "tensorflow", "jax", "IPython", "pytest", "meikiocr"],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
options = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
               icon=str(root / "src/meikipop/resources/icon.ico"))
exe = EXE(pyz, a.scripts, [], name="meikipop-turkish", console=False, **options)
cli = EXE(pyz, a.scripts, [], name="meikipop-turkish-cli", console=True, **options)
coll = COLLECT(exe, cli, a.binaries, a.datas, strip=False, upx=False, name="meikipop-turkish")
