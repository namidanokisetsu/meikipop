# meikipop-turkish setup

## Windows installer

Run `meikipop-turkish-2.0.4-windows-x64-setup.exe` from `dist/` or the
**Turkish Windows installer** workflow artifact. It installs for the current
user at `%LOCALAPPDATA%\Programs\meikipop-turkish`, with a Start menu shortcut,
optional desktop shortcut and uninstaller. No Python installation is needed.
Japanese keeps its own executable, shortcuts and settings. Upgrades use the same
Turkish installation directory; uninstall preserves your dictionaries and settings.

First launch opens Settings if TDK is missing. In **Dictionaries**, install TDK,
Stanza models and OCR models. Wiktionary and KeNet are optional. Setup needs a
network connection; normal lookup works offline afterward. Buttons never install
Python packages. Lookup pauses during setup, and closing Settings does not cancel
it. Wait for setup to finish before quitting.

**Install / update Wiktionary** fetches the current Turkish-to-English pack from
[yomidevs/wiktionary-to-yomitan](https://github.com/yomidevs/wiktionary-to-yomitan).
Its current download feed is hosted on Hugging Face. The app imports Yomitan
structured content into an indexed SQLite pack and records the revision and
SHA-256. It does not bundle a one-time Wiktionary snapshot or download during
lookup. TDK and KeNet use their checked-in source locks.

Reorder **TDK**, **Wiktionary** and **KeNet** by dragging or using **Move up/down**,
then Save. Order changes whole source sections; senses are kept separate.
**Roll back** restores the previous verified installation of that asset. Failed
updates leave the existing installation intact. One previous version is retained.

## Controls

Hold **Shift** over a word for local OCR. Clicking a preview, token or pin icon
keeps the result open. Pinned results stay in place and suspend scans. Click
outside, press **Escape**, or use the close button to dismiss. Empty OCR hits
hide the popup. Tray left-click pauses/resumes; the tray menu has clipboard,
search, settings and quit.

Text inputs are off by default. Enable automatic clipboard lookup, dragged
selections or double-click capture separately in Settings. Shortcut presets:

| Action | Preset |
| --- | --- |
| Clipboard | Ctrl+Alt+L |
| Search | Ctrl+Alt+D |
| Selected text | Ctrl+Alt+S |

Each shortcut has its own enable box and key recorder. Selection capture is
Windows-only, waits for modifiers to be released, and restores the previous
clipboard formats. Focus changes and timeouts cancel capture. Source applications
must support copying selected text; image-only text still needs OCR.

Copied and selected text opens a pinned popup. Typed search and clickable tokens,
suggestions and related expressions use the same lookup. Inside definitions and examples, select text by dragging or double-clicking,
use the selected-text shortcut, or hold the scan key over a word. These all use
the same lookup and Back history without reading or replacing the clipboard. Back history is limited
to 32 entries and cleared on dismissal. Clipboard input is limited to 2,000
characters. Clipboard contents, lookup history and screenshots are not logged or
uploaded. KeNet expands independently; **Show more** reveals longer definitions.

The optional **Pronunciation button** uses a Turkish system speech voice. Install
one through Windows Settings if none is available. It does not use the Japanese
audio database or download pronunciation files.

## Build a Windows installer

Use Windows x64, Python 3.13, `uv`, and Inno Setup 6. From this checkout:

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r packaging/requirements-turkish.txt
uv pip install --python .venv/Scripts/python.exe --no-deps -e .
.\Build-Turkish.ps1
```

The script builds a PyInstaller directory bundle and compiles the installer,
then writes `dist/*-setup.exe.sha256`. It finds Inno Setup in the standard
per-user or Program Files installation. Override with `-Python <python.exe>`
and `-ISCC <ISCC.exe>`. `-SkipBundle` recompiles only the installer from an
existing bundle. This build includes the local inference libraries, so it is
larger than the Japanese executable. Downloaded models and dictionaries are
not included. A bundled console helper runs setup without opening a console.

The GitHub Actions **Turkish Windows installer** workflow supports manual runs
and `turkish-v*` tags. It uploads the installer and checksum as artifacts; it
does not publish a GitHub release. Existing Japanese workflows are unchanged.

For a lightweight build check, without model inference:

```powershell
.\dist\meikipop-turkish\meikipop-turkish-cli.exe --self-check
```

The installer is unsigned. Hands-on clean-machine installation, input/focus,
mixed-DPI, voice availability and OCR acceptance remain with the user.

## Run from source and manage data

After installing the build requirements above, use [Start-Turkish.cmd](../Start-Turkish.cmd)
or `.\.venv\Scripts\meikipop-turkish.exe`. For clipboard-only development,
install PyQt6, pynput, platformdirs and the pinned Stanza/Torch packages instead
of the OCR/build dependencies, followed by `--no-deps -e .`.

```powershell
.\.venv\Scripts\meikipop.exe build-turkish-dict
.\.venv\Scripts\meikipop.exe setup-turkish-model
.\.venv\Scripts\meikipop.exe setup-turkish-ocr
.\.venv\Scripts\python.exe -m meikipop.scripts.turkish setup-turkish-wiktionary
.\.venv\Scripts\meikipop.exe setup-turkish-wordnet
```

Packaged commands use
`meikipop-turkish-cli.exe --setup <command>`. Setup commands support `--rollback`.
Close the Turkish app before CLI updates. Use dedicated asset directories for
`--output` or `--model-dir`; managed directories are replaced as a unit.

Data remains under `%LOCALAPPDATA%\meikipop\languages\tr` for compatibility:
TDK `packs/tr-tdk/poc-1`, Wiktionary `packs/tr-wiktionary/1`, KeNet
`packs/tr-kenet/1`, Stanza `stanza/1.14.0`, and OCR `paddle/3.7.0`.
`asset.json` records installed-file checksums; a sibling `.previous` directory
holds the rollback version. Turkish QSettings retain the `Meikipop/Turkish`
namespace. These locations do not overwrite Japanese dictionary/configuration.

Missing Stanza models fall back to exact lookup. `--analyzer exact` explicitly
selects it; `--dictionary` and `--model-dir` override runtime paths. Stanza uses
IMST tokenize/MWT and CharLM POS/lemma models. Paddle uses local PP-OCRv6 small
models, CPU inference, cached recognition and independent pointer hit-testing.
Background preparation uses the Settings scan interval. Rescan after changing
source content; cached boxes are retained during an active preview.

## Validation

The full fixture suite passed 99 tests; the later in-popup lookup additions
passed the focused 28-test GUI suite. Run it once when changing implementation:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

`smoke_turkish` and `smoke_turkish_ocr` remain available for user-run actual-model
checks; they were not rerun for this release. See the
[support plan](TURKISH_SUPPORT_PLAN.md) for acceptance boundaries.
