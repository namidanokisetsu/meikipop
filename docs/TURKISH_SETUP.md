Updated: 2026-10-05

# Shared popup setup

## Launch

Use [Start-Meikipop.cmd](../Start-Meikipop.cmd) on Windows or
[Start-Meikipop.command](../Start-Meikipop.command) on macOS. The Windows launcher
prefers the checkout's `.venv-desktop` (the tested Python 3.12 desktop environment)
and falls back to `.venv`; the macOS launcher uses `.venv`.
After an editable installation, `meikipop`,
`meikipop search`, and `meikipop-search` open the same shared popup.
`python -m meikipop.scripts.quick_lookup --no-ocr` runs dictionary search alone.
The tray menu opens Search, Setup, or Quit.

The original Japanese app remains available as `meikipop legacy-japanese`.
Its original OCR settings and dictionary tools are described in the
[upstream guide](https://github.com/rtr46/meikipop#readme).
`meikipop-turkish` and [Start-Turkish.cmd](../Start-Turkish.cmd) retain the
separate Turkish client and its existing settings.

## Dictionaries and controls

Open **Setup → Dictionaries → Import ZIPs** and select local Yomitan archives.
Definition, forms, frequency and kanji packs are indexed on disk without
replacing `dictionary.pkl`. Enable packs and move them up or down, then Apply.
Cancellation keeps completed imports and discards the unfinished pack.
Archive language metadata takes precedence; for a legacy archive without it,
choose its language or type a language code before importing.

Choose **Auto**, Japanese, Turkish, English, or another installed language.
The arrow selector chooses the dictionary searched by English input. Auto
detection uses scripts and dictionary evidence; choose a language explicitly
for ambiguous words. Japanese deconjugation and Turkish accent recovery have
dedicated handling. Other languages use exact entries, readings and imported
forms; importing a dictionary does not provide a universal morphology model.

Typing searches after a short debounce; Enter searches immediately. **Translate**
explicitly runs the local translation model. Dictionary sections have independent
previews and expansion controls. Scroll long results, **Pin** to keep and resize
them, and use Back or Escape. Imported frequency, inflection and kanji information
is shown with its source. Kanji details, including components and examples when
present, depend on the actual pack; missing information is not invented.

**Copy sentence**, or **Ctrl+Shift+C** on Windows / **Cmd+Shift+C** on macOS,
copies the visible OCR sentence while the popup is active. The sentence preview
and tooltip show what will be copied. It is the scanned context, not the
dictionary lemma. A manual lookup or mode change clears it; Back restores the
saved context. A scan cannot recover text outside the captured screen region.
Pin a scan preview to focus the popup for its keyboard shortcut. The pinned
**Translate sentence** action translates that same scanned context locally.

**Setup → Shortcut** records an independently enabled search shortcut. Presets
are Ctrl+Alt+D and Cmd+Option+D. General installs leave it disabled; the current
workspace enables the user's requested search shortcut. The legacy clients keep
their separate opt-in clipboard, selection and search controls. Search does not
monitor the clipboard or upload text automatically. Copy sentence changes the
clipboard only when invoked.

The provisioned local library uses the full Turkdict pack and Jitendex
(2026-10-03), plus KANJIDIC and Jiten metadata packs. These large data files are
outside Git. Additional local Yomitan packs can be added through the same UI.

## Screen lookup

Enable **Scan**, then hold the configured scan key over text; the default
activation is Shift or middle mouse. The preview follows the pointer. While
holding the scan key, left-click anywhere to pin the current result and expand
its dictionaries and kanji details. Pinning stops following and scanning; release
hides an unpinned preview after a short grace period. Close or Escape dismisses
the current scan until the trigger is released.

**Setup → Screen lookup** selects left click, middle click, or popup-only pinning.
Windows consumes the configured outside pin click while a scan preview is ready;
on macOS and Linux it also reaches the underlying app. Other clicks are unchanged.
**Compact preview** is on by default; turn it off for full definitions immediately.
**Scan automatically on hover** is off by default. When enabled, scanning waits
for a short pause over text and preserves pinned results. After dismissing an
automatic preview, move the pointer to resume. OCR runs separately from dictionary
search and retains visible sentence context.

The Japanese and Turkish OCR selectors are independent. Windows defaults remain
**MeikiOCR (CPU)** for Japanese and **PaddleOCR** for Turkish; macOS defaults to
**Apple Vision**. **Chrome Screen AI (local)** is an optional alternative for
either language. Changing the selection invalidates pending scans and uses a
separate recognition cache. Selecting a provider never downloads a model.

For Chrome Screen AI, use the Google component link in **Setup → Screen lookup**
or the [official Chromium package directory](https://chrome-infra-packages.appspot.com/p/chromium/third_party/screen-ai).
Download the package matching the operating system and Python CPU architecture,
extract the complete archive, and choose its folder with **Browse**. Keep the
native library and model files together in `resources/`. Installed components
under the app's `screen_ai` directory, the legacy `~/.config/screen_ai` directory,
and supported Chrome profile locations are discovered automatically. Restart
Meikipop after replacing a component already loaded in the process. Google's
macOS component uses `libchromescreenai.so` despite being a macOS binary; the
adapter follows the [Meikikai native bridge](https://github.com/hectahertz/meikikai/tree/50efb401/src/meikikai/ocr/providers/chrome_screen_ai).
macOS native loading still needs verification on actual macOS hardware.

- **Windows Japanese:** install `meikiocr>=0.3.5`. Its local recognizer supplies
  text boxes for Japanese lookup. Model setup is explicit and separate from
  ordinary typed lookup.
- **Windows Turkish:** use Python 3.12 and install the optional `[turkish-ocr]`
  dependencies, then run `meikipop setup-turkish-ocr` in that environment.
  The dependency group aligns OpenCV packages at 4.10.0.84. PaddleOCR 3.7 uses
  local PP-OCRv6 small detection and recognition models with word boxes,
  CPU inference, four threads and oneDNN acceleration with Paddle 3.2.2. Paddle
  3.3.1 failed locally in the optimized CPU path, matching the reported
  [oneDNN conversion regression](https://github.com/PaddlePaddle/Paddle/issues/77340).
  These models are installed
  and a Turkish screenshot check passed here. The small configuration favors
  interactive latency; a medium-model check was slower on the same sample with
  the same recognized text. That comparison does not establish accuracy across
  fonts, languages or screen content. The adapter rejoins Turkish accent
  fragments and preserves nearby wrapped lines for sentence copying.
  Indexed Turkdict lookup does not require Stanza or Paddle.
- **macOS:** the unified popup uses native Apple Vision for OCR. Available
  recognition languages depend on the installed macOS version. Grant Screen
  Recording and Input Monitoring/Accessibility permissions to the terminal or
  app that launches Meikipop. Unsupported OCR languages produce an actionable
  message; their typed dictionary lookup remains available.

The new shared scan path uses local recognition. The legacy Japanese client
still offers its original providers, including explicitly selected remote OCR.
macOS packaging and CI have been prepared, but a macOS build and hardware check
have not been run in this Windows workspace.

## Local translation

Choose a model in **Setup → Translation** and use **Download selected model**
once. **Quality** uses Tencent's [Hy-MT2-7B Q8_0](https://huggingface.co/tencent/Hy-MT2-7B-GGUF)
(about 8 GB of weights); **Lightweight** uses
[Hy-MT2-1.8B Q8_0](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF) (about 2 GB).
Both support Japanese, Turkish and English in one model. Quality is the default;
changing models is explicit and there is no automatic fallback.

Setup downloads the selected official GGUF and a pinned
[llama.cpp runtime](https://github.com/ggml-org/llama.cpp/releases), checks their
hashes and records source metadata in the app's `translation/installation.json`.
Equivalent commands, using Meikipop's Python environment:

```sh
python -m meikipop.scripts.translation_server --install quality
python -m meikipop.scripts.translation_server --install lightweight
```

**Translate** starts only the installed selected model, off the UI thread, at
`http://127.0.0.1:8766/v1`. Windows uses the CUDA runtime for the selected NVIDIA
GPU; Apple Silicon uses Metal. The server frees model memory after an idle
minute and reloads it when needed. The app stops only its own server when
exiting. CPU execution is possible
but may be slower. Weight size excludes runtime and context memory, so close
other GPU-heavy applications if necessary.

**Custom local server** accepts a local chat-completions endpoint and model
alias. It is never started or downloaded by the app. Requests use numeric
loopback addresses, bypass proxies and reject redirects. No text goes to a
cloud translation service. Search and translation do not download anything;
neither Torch nor the older Argos/CTranslate2 backend is required or offered.
The result identifies its selected model. Translation can still make errors;
the selected model's published benchmarks do not establish accuracy for every
language pair or passage.

## Optional Turkish OCR export

The same Paddle models can run through PaddleX's ONNX Runtime engine. On this
Windows machine, a 1200×480 Turkish fixture took about 75 ms per warm scan with
ONNX Runtime, versus 115 ms with Paddle 3.2.2/oneDNN and 568 ms with the previous
unoptimized setup. Text, word fragments and word coordinates matched exactly
on that fixture; this is not an accuracy benchmark across screen content.

Ordinary OCR setup uses native Paddle. For the optional export, first run
`meikipop setup-turkish-ocr`, then use a separate Python 3.12 conversion environment
from the checkout. Keep the desktop environment on Paddle 3.2.2; the Windows
converter requires the tested Paddle 3.1.1/Paddle2ONNX 2.1.0 combination:

```powershell
py -3.12 -m venv .venv-ocr-export
.\.venv-ocr-export\Scripts\python -m pip install paddlepaddle==3.1.1 paddle2onnx==2.1.0 onnx==1.17.0
.\.venv-ocr-export\Scripts\python -m pip install --no-deps -e .
.\.venv-ocr-export\Scripts\python -m meikipop.scripts.export_turkish_ocr --source-dir "$env:USERPROFILE\.paddlex\official_models" --output build\turkish-onnx
.\.venv-desktop\Scripts\python -m meikipop.scripts.turkish setup-turkish-ocr --onnx-dir build\turkish-onnx
```

The export records hashes of both original models and both ONNX files. Setup
checks those hashes against the staged native models, opens both models with
the installed runtime, and activates the complete installation atomically.
Runtime lookup downloads nothing and uses ONNX only when both files are in its
verified manifest. Normal setup restores native Paddle; `--rollback` restores
the previous complete asset installation. Windows already installs ONNX Runtime
with Meikipop. The conversion packages are not runtime dependencies.

## Legacy Turkish client

The separate `meikipop-turkish` client retains TDK, Wiktionary, KeNet, optional
Stanza analysis, Windows selection capture and system-voice pronunciation.
Its Settings page and CLI asset commands remain available:

```sh
meikipop build-turkish-dict
meikipop setup-turkish-model
meikipop setup-turkish-ocr
python -m meikipop.scripts.turkish setup-turkish-wiktionary
meikipop setup-turkish-wordnet
```

Legacy asset commands support `--rollback`. Close that client before CLI asset
updates. Its existing `languages/tr` data and `Meikipop/Turkish` settings remain
separate from shared Yomitan packs and `Meikipop/QuickLookup` preferences.
`Build-Turkish.ps1` and the Turkish Windows installer workflow still build the
separate client; the unified launchers do not replace that installed app.

## Validation

Run the project fixture suite once after implementation changes:

```sh
python -m unittest discover -s tests
```

Focused tests cover stale-result rejection, input/pinning/history, source
rendering, import cancellation, offline inference and archive validation.
Hands-on OCR accuracy, global keys, display scaling and clean-machine packaging
remain platform acceptance work. See the [support plan](TURKISH_SUPPORT_PLAN.md).
