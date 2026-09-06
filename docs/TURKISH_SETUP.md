# Turkish text lookup setup

Turkish currently runs as a separate clipboard window with TDK definitions,
Stanza analysis, clickable sentence tokens, examples, and related expressions.
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

## Use the clipboard window

Copy Turkish text in another application and press **Ctrl+Alt+L**, or click
**Look up clipboard** in the window or tray. Try `Dün kitaplarımdan birini okudum.`
and click `okudum`; try `Bunu hemen fark etti.` and click `etti` for `fark etmek`.
The whole copied phrase is looked up first, otherwise the first word is selected.

The window stays open after shortcut release. **Close** or Escape while focused
dismisses it; use the tray menu to exit. Repeating an explicit lookup works.
Clipboard text is read only on request, limited to 2,000 characters, and is not
logged. Model loading and lookup run off the Qt thread.

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
Close Turkish mode before rebuilding its installed dictionary.

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

CLI lookup and smoke reports emit UTF-8 JSON, including when redirected on Windows.
`--debug` adds raw Stanza tokens, all expanded Words, lemma/POS/features, and
attempted dictionary routes. Normal CLI output omits those diagnostics; exact
mode has no raw Stanza analysis. No diagnostic files or clipboard history are saved.
