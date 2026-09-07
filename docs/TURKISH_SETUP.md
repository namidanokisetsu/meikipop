# Turkish desktop MVP setup

Turkish runs as a Meikipop reading popup with TDK definitions, Stanza analysis, KeNet
synonyms/semantic links, local PaddleOCR, clickable sentence tokens and examples.
It starts without Japanese dictionary or OCR setup. See the
[support plan](TURKISH_SUPPORT_PLAN.md) for implementation status and remaining scope.

## Install from source

Use Python 3.13 for the pinned NLP packages. This minimal Windows environment
supports Turkish clipboard mode and the tests:

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe "stanza==1.14.0" "torch==2.8.0" PyQt6 pynput platformdirs
uv pip install --python .venv/Scripts/python.exe --no-deps -e .
.\.venv\Scripts\meikipop.exe build-turkish-dict
.\.venv\Scripts\meikipop.exe setup-turkish-model
.\.venv\Scripts\meikipop.exe turkish-clipboard
```

For an existing full development installation, `pip install -e ".[turkish]"`
adds the pinned NLP extra. Install the normal project dependencies to run Japanese OCR.

Dictionary setup downloads the TDK snapshot pinned in
[`sources.json`](../src/meikipop/resources/turkish/sources.json). Model setup
downloads Stanza 1.14.0 IMST tokenize/MWT and CharLM POS/lemma models with their
required character language models and embeddings. Existing no-CharLM
installations must rerun `setup-turkish-model` once for the new lemma weights.
Runtime lookup disables model downloads and works offline after setup.

## Use the app

Double-click [Start-Turkish.cmd](../Start-Turkish.cmd), or run
`.\.venv\Scripts\meikipop.exe turkish-clipboard`. The launcher uses this checkout's
environment and opens no console. It starts in the tray, without a search window.
Only one Turkish instance runs at a time. Quit an older running copy before launching
updated source code.

Text shortcuts, automatic clipboard lookup and double-click capture are **off by default**.
Enable only the inputs you want in Settings. Older default-on Turkish text settings
reset once on upgrade. Manual **Look up clipboard** and **Search?** remain in the menus.
With automatic lookup enabled, copying text opens a pinned popup beside the pointer.
Try `D?n kitaplar?mdan birini okudum.` and click `okudum`.
The whole copied phrase is looked up first, otherwise the first word is selected.

Hold **Shift** with the pointer over a word to scan locally. Move to another
word while holding it to scan again. Move into the popup after releasing Shift to read it; a 350 ms grace period lets you cross the gap. Click a word or **Pin** to keep it open. Copied lookups pin immediately. Pinned results stay in place and suspend background scans until dismissed.
Click outside, press **Escape**, or use **×** to dismiss. On Windows, Escape is intercepted only while this popup is visible, including its key-up event, so it does not also exit a video. Left-click the tray icon to pause or resume; use its menu to quit.

Press **Ctrl+Alt+D** or choose **Search…** from the tray or **···** menu for a compact search field beside the tray. Type a word and press Enter; results use the same dictionary surface. Clipboard and search shortcuts are separately configurable in Settings (click a recorder, press the keys, and check its enable box) or through `--hotkey` and `--search-hotkey`. Click tokens,
suggestions, related expressions or WordNet members to navigate; **←** goes back.
Expand **WordNet** for its independent sense groups and typed semantic links.
WordNet definitions appear immediately when a linked word has no TDK entry.

Settings are in the tray and **···** menu. The default appearance inherits the original
Meikipop font, colors, opacity and positioning. The popup grows with its definitions
and scrolls at its maximum size. Settings persist clipboard and selection lookup, background OCR interval, keyboard/mouse activation, separate search/clipboard shortcuts, original Meikipop theme presets, font, colors, opacity, placement, size and examples. Turkish settings do not write Japanese configuration. Fonts are checked for Turkish glyph coverage.
Installation buttons download TDK, Stanza, WordNet or OCR models explicitly. Lookup
pauses during installation so Windows can replace the open data files, then resumes
automatically with fresh models and caches. Failed installs show their error in Settings;
closing Settings does not interrupt setup. Wait for installation to finish before quitting.
Install the OCR Python extra
below before using the OCR model button. No pip command runs from the GUI.

On Windows, enable **Look up double-clicked text** in Settings to capture selectable text. This uses a short Ctrl+C capture, waits for a fresh clipboard change, and restores the previous clipboard formats. Held modifiers, focus changes and timeouts cancel the attempt. Applications must support copying the selected text; image-only text still needs OCR.

Clipboard lookup is limited to 2,000 characters. Duplicate notifications,
empty/oversized payloads and copies while Meikipop owns focus are ignored.
Enabling monitoring does not read pre-existing content. The 32-entry Back history
is in memory and cleared on dismissal; clipboard text and screen images are not
logged or uploaded. Inference and dictionary lookup run off the Qt thread.
With background preparation enabled, OCR runs before activation, as in original
Meikipop. Hovering nearby words reuses recognition if the captured pixels are unchanged.
A recent prepared result can appear immediately on activation. While a preview is open,
pointer movement reuses its captured text, as in original Meikipop; release the scan key
and scan again after scrolling or changing the source. Model loading and new
or changing screen content still require inference; cached-hover speed is not a promise
about cold startup or a changing game scene.

Override the shortcut using pynput syntax:

```powershell
.\.venv\Scripts\meikipop.exe turkish-clipboard --hotkey "<ctrl>+<alt>+k"
```

Failed lookups can offer **Did you mean?** links, for example with `cocuk`,
`cocugu`, `kisi`, or `kitpa`. Suggestions are bounded, dictionary-validated
guesses; they do not silently replace the original text. The plan records their limits.

## Data locations and fallback

Under the application's data directory (normally `%LOCALAPPDATA%\meikipop`
on Windows), the TDK pack is at `languages/tr/packs/tr-tdk/poc-1/` and models
are at `languages/tr/stanza/1.14.0/`. Source downloads use `paths.cache_dir`.
Keep downloads, model weights, generated packs, and `.venv` out of Git.

Pass `--dictionary <database>` and `--model-dir <directory>` to override runtime
locations. Missing or incompatible models visibly fall back to exact lookup;
`--analyzer exact` explicitly selects lookup without Stanza. A TDK pack is required.
Close the Turkish app before rebuilding its installed dictionary from the CLI. The Settings
installer releases its own dictionary handles automatically.

The dictionary builder accepts `--source <locked-v12-file>` and `--output <directory>`.
With both supplied it requires only the standard library, including under
`python -S -m meikipop.scripts.build_turkish_dictionary` with `src` on PYTHONPATH.
Default application paths additionally require `platformdirs`. The builder
validates the source checksum and SQLite integrity; pack metadata and
`manifest.json` record source/build identity and source anomalies.

## Verify and diagnose

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m meikipop.scripts.smoke_turkish
.\.venv\Scripts\meikipop.exe lookup-turkish "Bunu hemen fark etti." --target 3
.\.venv\Scripts\meikipop.exe lookup-turkish "cocugu" --debug
```

Unit tests use small fixtures and offscreen Qt with mocked keyboard/clipboard
access. The separate smoke script requires the installed full TDK pack and real
Stanza models; it blocks socket connections during initialization and lookup.
These checks do not replace manual desktop focus/shortcut or packaging acceptance.

On this Windows desktop, separate-app Ctrl+C → pinned popup → global Escape
passed. Real screen capture with the global Shift listener → Paddle word box →
Stanza → TDK/KeNet → click pin → Shift release also passed. The unit suite has
86 checks, including content sizing, pin stability, installer recovery and OCR cache
invalidation. TDK and Stanza installation followed by lookup also passed through the
actual console-free `pythonw` path. Multi-monitor placement has negative-coordinate coverage;
mixed-DPI hardware, browser/PDF combinations and a clean-machine executable
remain acceptance work. This is a usable source-environment MVP, not an installer.

CLI lookup and smoke reports emit UTF-8 JSON, including when redirected on Windows.
`--debug` adds raw Stanza tokens, all expanded Words, lemma/POS/features, and
attempted dictionary routes. Normal CLI output omits those diagnostics; exact
mode has no raw Stanza analysis. No diagnostic files or clipboard history are saved.

## Local PaddleOCR and WordNet setup

The Turkish OCR extra pins current PaddleOCR 3.7.0, PaddleX 3.7.2 and
PaddlePaddle 3.3.1. Install it in the project environment:

```powershell
uv pip install --python .venv/Scripts/python.exe paddleocr==3.7.0 paddlex==3.7.2 paddlepaddle==3.3.1
.\.venv\Scripts\meikipop.exe setup-turkish-wordnet
.\.venv\Scripts\meikipop.exe setup-turkish-ocr
.\.venv\Scripts\python.exe -m meikipop.scripts.smoke_turkish_ocr
```

A full pip development install can use `pip install -e ".[turkish,turkish-ocr]"`.
The existing lightweight clipboard install remains supported without OCR dependencies.
OCR setup downloads PP-OCRv6 small detection/recognition weights explicitly.
Runtime uses local CPU inference only, with no remote fallback or model downloads.
Models live at `languages/tr/paddle/3.7.0/`; their local manifest records SHA-256
checksums. WordNet lives at `languages/tr/packs/tr-kenet/1/wordnet.sqlite3`.
KeNet source revision, checksum and GPL-3.0 attribution are in the pack metadata
and the checked-in `resources/turkish/wordnet.json` source lock.

The OCR smoke uses Windows Arial to generate a small Turkish fixture and blocks
network connections during real model initialization, recognition, and word-box lookup.
It is separate from the fast fixture-based unit suite.

## Japanese text input

The Japanese build on `feature/japanese-clipboard` keeps the original dictionary,
deconjugation, popup, OCR and audio. Its Windows executable is installed at
`%LOCALAPPDATA%\Programs\meikipop\meikipop.exe` using the existing shortcuts.

Open **Settings ? Text Lookup** to assign clipboard, search and selected-text
shortcuts. Click a recorder and press the desired keys. Check its box to enable it.
Presets: Ctrl+Alt+L for clipboard, Ctrl+Alt+D for search and Ctrl+Alt+S for selection.
All start unchecked; unchecking preserves the recorded combination. Duplicate enabled
bindings are rejected; changes apply on Save. Enable **Look up double-clicked text**
to look up words by double-clicking them in copyable Windows applications.
Selected-text capture waits for key release and restores previous clipboard formats.

- **Look up copied text automatically** in the tray: optional automatic lookup.

Click to dismiss the Japanese text popup. Selection timeouts and focus changes
cancel capture without looking up old clipboard content. These additions reuse the
existing Japanese lookup worker and renderer; the Turkish branch includes them too.

The standard Japanese dictionary builder combines JMdict English with KANJIDIC2,
kanji decomposition and frequency data. There is no dictionary import UI.
`import-yomitan-dict-html` in a source environment converts one or more term ZIPs
into a single replacement pickle; use `-o <new-file.pkl>` to avoid overwriting the
working dictionary. Term/monolingual/grammar/name banks are convertible, with
limited HTML support. Standalone frequency ZIPs do not rank other imported packs;
pitch and kanji banks are unsupported. Conversion currently leaves kanji entries
empty. More terms increase startup memory/loading and may add duplicate results;
ordinary lookup uses an in-memory index. The installed dictionary is unchanged.
