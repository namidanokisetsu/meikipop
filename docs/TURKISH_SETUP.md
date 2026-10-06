Updated: 2026-10-06

# Shared popup setup

## Launch

Use [Start-Meikipop.cmd](../Start-Meikipop.cmd) on Windows or
[Start-Meikipop.command](../Start-Meikipop.command) on macOS. The Windows launcher
prefers the checkout's `.venv-desktop` (the tested Python 3.12 desktop environment)
and falls back to `.venv`; the macOS launcher uses `.venv`.
After an editable installation, `meikipop`,
`meikipop search`, and `meikipop-search` open the same shared popup.
`python -m meikipop.scripts.quick_lookup --no-ocr` runs dictionary search alone.
The tray menu opens Search and Settings, switches the language profile, or quits.

The original Japanese app remains available as `meikipop legacy-japanese`.
Its original OCR settings and dictionary tools are described in the
[upstream guide](https://github.com/rtr46/meikipop#readme).
`meikipop-turkish` and [Start-Turkish.cmd](../Start-Turkish.cmd) retain the
separate Turkish client and its existing settings.

## Dictionaries and controls

Open **Settings → Dictionaries → Import ZIPs** and select local Yomitan archives.
Definition, forms, frequency and kanji packs are indexed on disk without
replacing `dictionary.pkl`. Enable packs and move them up or down; changes save immediately.
Choose a recommended pack and press **Install**, or select an installed pack and press
**Remove**. Removal deletes all revisions of that dictionary so an older copy cannot reappear.
Cancellation keeps completed imports and discards the unfinished pack.
Archive language metadata takes precedence; for a legacy archive without it,
the selected profile supplies its language.

Choose a language profile from the tray's right-click menu or the top of Settings.
**Add language…** offers languages with a verified dictionary download or managed
translation support. Importing a dictionary also makes its source language available.
Each profile owns its dictionary list, OCR provider, translation pair/model,
appearance and audio preferences. Lookup detects the input side of that pair
and uses only that profile's dictionaries. Japanese deconjugation and Turkish accent recovery have
dedicated handling. Other languages use exact entries, readings and imported
forms; importing a dictionary does not provide a universal morphology model.
Imported Turkish forms retain the dictionary's grammar labels, including alternative analyses.
Reimport an older forms pack to restore labels discarded by earlier versions; existing dictionary preferences are preserved.

Typed search opens beside the tray with keyboard focus. Enter searches immediately.
Explicit sentences go straight to translation; words try dictionaries first and
translate automatically when no entry matches. Hover OCR stays dictionary-only.
OCR translations show the original sentence, a divider, then the translation. Typed translations
show only the translation below the input. Translate and audio
sit at the top right; Back and a compact nested-lookup trail sit at the bottom left,
with Copy and Close at the right. Back restores the previous result and sentence context.
Dictionary sections have independent previews and expansion controls. Pin with the scan gesture
to keep and resize results. Imported frequency, inflection and kanji information uses compact labels.
Frequency defaults to one harmonic-mean rank across enabled rank dictionaries, taking
the best matching rank per dictionary. **Dictionaries → Combine frequency ranks**
switches between the combined number and individual labels. Counts and nonnumeric
bands are excluded from the mean.
The copy button previews its sentence on hover; other popup hover labels are hidden.
Kanji always use compact cards with meanings and readings, without a separate label or details toggle.

The top controls are Translate, Read sentence, then Read word. In pinned OCR results they
sit alongside the heading; language switching stays in the tray and Settings.
Sentence reading uses system TTS even when a Japanese word-audio database is configured.
Right-click Read word to choose a pronunciation source. **Audio → Source priority**
orders recordings and System voice, including TTS first. Each language can use its
own local `android.db` recordings database; recordings are not bundled, and Turkish
recordings require a compatible Turkish database. Missing recordings fall through
the selected order. Sentence reading always uses an installed system voice.
**Settings → Audio → Autoplay** saves immediately per profile: Off, On lookup, or When pinned.
When pinned keeps OCR hover previews silent and plays when expanded. Typed lookups never autoplay audio.
Automatic selection lookups honor On lookup autoplay.
Each pronunciation autoplays at most once during a held scan shortcut; manual audio can repeat.
**Settings → Appearance** offers black Cyan and Lime, plus Light and Custom. Presets are opaque
with contrasting text and accents. Changes apply immediately; Custom remembers its own colors
when switching presets. Appearance remains independent per language profile.
Japanese definition readings appear above their text. Headwords keep the full word
and bracketed reading by default; **Appearance → Headword reading → Furigana**
switches the heading to an above-text reading too.
Furigana uses the selected font, sits close to the text and defaults to muted gray
at 50% size. **Appearance → Furigana size (%)** adjusts Japanese readings.

**Settings → Translation** contains horizontal **From** and **To** language strips. Both default
to **Automatic** within the profile's translation pair; manual selections override
translation direction without changing the OCR/dictionary profile.

**Copy sentence**, or **Ctrl+Shift+C** on Windows / **Cmd+Shift+C** on macOS,
copies the OCR sentence while the popup is active. The copy icon's tooltip
shows what will be copied. It is the scanned context, not the
dictionary lemma. Manual lookup copies the entered text; Back restores the
saved context. A scan cannot recover text outside the captured screen region.
Pin a scan preview to focus the popup for its keyboard shortcut. The pinned
**Translate sentence** action translates that same scanned context locally.

**Settings → Shortcuts** configures one text-lookup shortcut and optional automatic selection.
Search defaults to Ctrl+Shift+D (Cmd+Shift+D on macOS): it copies selected
text, preserving the clipboard, or uses the clipboard if nothing is selected. Sentences
translate automatically; the prefilled input remains selected for immediate typing.
Press the shortcut again to close the popup. Ordinary settings save immediately;
downloads, imports and removals require their action buttons.
Automatic lookup on double-click or drag selection is disabled by default and configured per profile.
These previews leave keyboard focus in the original app. Selected-text lookup preserves the clipboard.
Copy sentence changes the clipboard only when invoked.

The provisioned local library uses the full Turkdict pack and Jitendex
(2026-10-03), plus KANJIDIC and Jiten metadata packs. These large data files are
outside Git. Additional local Yomitan packs can be added through the same UI.

### Optional lemma fallback

Exact entries and imported forms remain first. **Settings → Dictionaries → Lemma
fallback** enables installed Stanza models for the selected non-Japanese profile.
Japanese keeps its bundled rules. Models run in lookup workers, with original OCR
sentence context where available; results are labeled as lemma matches.

Install the optional dependencies and explicitly set up each supported language
in the environment used to launch Meikipop, for example:

```powershell
.venv-desktop/Scripts/python -m pip install -e ".[morphology]"
.venv-desktop/Scripts/python -m meikipop.scripts.setup_morphology tr
```

Replace `tr` for another Stanza language. Setup downloads language-specific models;
runtime never downloads them. Missing models leave exact/form lookup available and
report a setup error on a lemma miss. Turn the option off and on after setup to retry.
Neural analysis is optional and can add latency on misses; isolated words can be
ambiguous. The default workflow needs no NLP models.

## Screen lookup

Set a screen lookup key or mouse shortcut in **Settings → Shortcuts**, then hold it over text; the default
activation is Shift. The preview stays beside the word until a different result appears. While
holding the scan key, left-click anywhere to pin the current result and expand
its dictionaries, or press **C**. **Shortcuts → Pin preview** records another key
or disables keyboard pinning per profile. Pinning stops following; a click outside or a fresh scan elsewhere dismisses it. Release
hides an unpinned preview after a short grace period. Close or Escape dismisses
the current scan until the trigger is released.
A held scan shortcut outside the focused text-search window resumes OCR, including
after Ctrl+Shift+D. Typing inside Search keeps its focus.

Clear both screen lookup shortcuts to disable OCR; there is no additional toggle.
**Settings → Shortcuts → Pin with mouse** selects left click, middle click, or popup-only pinning.
Windows consumes the configured outside pin click while a scan preview is ready;
on macOS and Linux it also reaches the underlying app. Other clicks are unchanged.
**Appearance → Compact preview** is on by default; turn it off for full definitions immediately.
Scanning always requires a held trigger. Automatic hover scanning has been removed;
old saved hover preferences are ignored. OCR runs separately from dictionary search
and retains visible sentence context.

Each profile shows one OCR selector. Windows defaults remain
**MeikiOCR (CPU)** for Japanese and **PaddleOCR** for Turkish; macOS defaults to
**Apple Vision**. **Chrome Screen AI (local)** is an optional alternative for
either language. Changing the selection invalidates pending scans and uses a
separate recognition cache. Selecting a provider never downloads a model.

For Chrome Screen AI, use the Google component link in **Settings → OCR**
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
The result's tooltip identifies its selected model. Translation can still make errors;
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

## Language coverage

The profile picker includes only the languages below, plus languages from imported
dictionaries. Coverage was checked on 2026-10-06 against the
[Wiktionary release catalogue](https://yomidevs.github.io/wiktionary-to-yomitan/download/),
[Jitendex](https://jitendex.org/pages/downloads.html),
[Hy-MT2 publisher language list](https://huggingface.co/tencent/Hy-MT2-7B#supported-languages), and
[Stanza 1.14 resources](https://raw.githubusercontent.com/stanfordnlp/stanza-resources/main/resources_1.14.0.json).
The catalogue establishes availability, not equal dictionary depth or measured translation quality.

- **Dictionary** means an explicit recommended download exists; Wiktionary packs use English definitions.
  Every imported language supports exact entries, readings and supplied forms. Japanese adds bundled
  deconjugation; Turkish adds accent recovery. Romaji/fuzzy input has not been changed in this update.
- **Translation** means the managed Hy-MT2 models list the language. Models must be installed.
  A dash requires a separately configured server whose language support the user verifies.
- **OCR** lists the established desktop defaults. A dash means text lookup by default;
  other profiles can opt into Paddle, Screen AI or macOS Vision, but provider/platform coverage
  and accuracy need separate verification. Adding a profile does not install or validate an OCR model.
- **Morphology**: Rules are bundled for Japanese. Stanza is optional, off by default,
  and requires explicit language-specific setup. A dash means no verified compatible package here.
  Merely having a package does not establish accuracy on isolated words.
- **Audio** depends on installed system voices or user-provided recordings for that language.
  TTS and recordings have independent priority; no voice coverage is implied by this table.

| Language | Code | Dictionary | Translation | OCR | Morphology |
| --- | --- | --- | --- | --- | --- |
| Afrikaans | `af` | Wiktionary | ? | ? | Stanza |
| Albanian | `sq` | Wiktionary | ? | ? | Stanza |
| Ancient Greek | `grc` | Wiktionary | ? | ? | Stanza |
| Armenian | `hy` | Wiktionary | ? | ? | Stanza |
| Aromanian | `rup` | Wiktionary | ? | ? | ? |
| Assamese | `as` | Wiktionary | ? | ? | ? |
| Assyrian Neo-Aramaic | `aii` | Wiktionary | ? | ? | ? |
| Asturian | `ast` | Wiktionary | ? | ? | ? |
| Azerbaijani | `az` | Wiktionary | ? | ? | ? |
| Bangla | `bn` | Wiktionary | Hy-MT2 | ? | ? |
| Bashkir | `ba` | Wiktionary | ? | ? | ? |
| Basque | `eu` | Wiktionary | ? | ? | Stanza |
| Belarusian | `be` | Wiktionary | ? | ? | Stanza |
| Bulgarian | `bg` | Wiktionary | ? | ? | Stanza |
| Burmese | `my` | Wiktionary | Hy-MT2 | ? | ? |
| Cantonese | `yue` | Wiktionary | Hy-MT2 | ? | ? |
| Catalan | `ca` | Wiktionary | ? | ? | Stanza |
| Cebuano | `ceb` | Wiktionary | ? | ? | ? |
| Central Bikol | `bcl` | Wiktionary | ? | ? | ? |
| Church Slavic | `cu` | Wiktionary | ? | ? | Stanza |
| Cimbrian | `cim` | Wiktionary | ? | ? | ? |
| Classical Syriac | `syc` | Wiktionary | ? | ? | ? |
| Coptic | `cop` | Wiktionary | ? | ? | Stanza |
| Cornish | `kw` | Wiktionary | ? | ? | ? |
| Crimean Tatar | `crh` | Wiktionary | ? | ? | ? |
| Czech | `cs` | Wiktionary | Hy-MT2 | ? | Stanza |
| Danish | `da` | Wiktionary | ? | ? | Stanza |
| Deutsch | `de` | Wiktionary | Hy-MT2 | ? | Stanza |
| Egyptian | `egy` | Wiktionary | ? | ? | ? |
| Egyptian Arabic | `arz` | Wiktionary | ? | ? | ? |
| English | `en` | Wiktionary | Hy-MT2 | ? | Stanza |
| Español | `es` | Wiktionary | Hy-MT2 | ? | Stanza |
| Esperanto | `eo` | Wiktionary | ? | ? | ? |
| Estonian | `et` | Wiktionary | ? | ? | Stanza |
| Faroese | `fo` | Wiktionary | ? | ? | ? |
| Filipino | `fil` | ? | Hy-MT2 | ? | ? |
| Finnish | `fi` | Wiktionary | ? | ? | Stanza |
| Français | `fr` | Wiktionary | Hy-MT2 | ? | Stanza |
| Galician | `gl` | Wiktionary | ? | ? | Stanza |
| Georgian | `ka` | Wiktionary | ? | ? | Stanza |
| Gothic | `got` | Wiktionary | ? | ? | Stanza |
| Greek | `el` | Wiktionary | ? | ? | Stanza |
| Gujarati | `gu` | Wiktionary | Hy-MT2 | ? | ? |
| Gulf Arabic | `afb` | Wiktionary | ? | ? | ? |
| Hawaiian | `haw` | Wiktionary | ? | ? | ? |
| Hebrew | `he` | Wiktionary | Hy-MT2 | ? | Stanza |
| Hindi | `hi` | Wiktionary | Hy-MT2 | ? | Stanza |
| Hungarian | `hu` | Wiktionary | ? | ? | Stanza |
| Icelandic | `is` | Wiktionary | ? | ? | Stanza |
| Ido | `io` | Wiktionary | ? | ? | ? |
| Indonesian | `id` | Wiktionary | Hy-MT2 | ? | Stanza |
| Ingrian | `izh` | Wiktionary | ? | ? | ? |
| Interlingua | `ia` | Wiktionary | ? | ? | ? |
| Irish | `ga` | Wiktionary | ? | ? | Stanza |
| Italiano | `it` | Wiktionary | Hy-MT2 | ? | Stanza |
| Javanese | `jv` | Wiktionary | ? | ? | ? |
| Kannada | `kn` | Wiktionary | ? | ? | ? |
| Kashubian | `csb` | Wiktionary | ? | ? | ? |
| Kazakh | `kk` | Wiktionary | Hy-MT2 | ? | Stanza |
| Khiamniungan Naga | `kix` | Wiktionary | ? | ? | ? |
| Khmer | `km` | Wiktionary | Hy-MT2 | ? | ? |
| Kyrgyz | `ky` | Wiktionary | ? | ? | Stanza |
| Ladin | `lld` | Wiktionary | ? | ? | ? |
| Lao | `lo` | Wiktionary | ? | ? | ? |
| Latin | `la` | Wiktionary | ? | ? | Stanza |
| Latvian | `lv` | Wiktionary | ? | ? | Stanza |
| Laz | `lzz` | Wiktionary | ? | ? | ? |
| Lithuanian | `lt` | Wiktionary | ? | ? | Stanza |
| Livonian | `liv` | Wiktionary | ? | ? | ? |
| Lower Sorbian | `dsb` | Wiktionary | ? | ? | ? |
| Luxembourgish | `lb` | Wiktionary | ? | ? | ? |
| Macedonian | `mk` | Wiktionary | ? | ? | ? |
| Malagasy | `mg` | Wiktionary | ? | ? | ? |
| Malay | `ms` | Wiktionary | Hy-MT2 | ? | ? |
| Malayalam | `ml` | Wiktionary | ? | ? | ? |
| Maltese | `mt` | Wiktionary | ? | ? | ? |
| Mandarin Chinese | `cmn` | Wiktionary | ? | ? | ? |
| Manx | `gv` | Wiktionary | ? | ? | Stanza |
| Marathi | `mr` | Wiktionary | Hy-MT2 | ? | Stanza |
| Middle Dutch | `dum` | Wiktionary | ? | ? | ? |
| Middle English | `enm` | Wiktionary | ? | ? | ? |
| Middle French | `frm` | Wiktionary | ? | ? | ? |
| Mongolian | `mn` | Wiktionary | Hy-MT2 | ? | ? |
| Māori | `mi` | Wiktionary | ? | ? | ? |
| Navajo | `nv` | Wiktionary | ? | ? | ? |
| Nederlands | `nl` | Wiktionary | Hy-MT2 | ? | Stanza |
| Norman | `nrf` | Wiktionary | ? | ? | ? |
| North Levantine Arabic | `apc` | Wiktionary | ? | ? | ? |
| Northern Kurdish | `kmr` | Wiktionary | ? | ? | Stanza |
| Northern Sami | `se` | Wiktionary | ? | ? | ? |
| Norwegian | `no` | Wiktionary | ? | ? | ? |
| Norwegian Bokmål | `nb` | Wiktionary | ? | ? | Stanza |
| Norwegian Nynorsk | `nn` | Wiktionary | ? | ? | Stanza |
| Occitan | `oc` | Wiktionary | ? | ? | ? |
| Odia | `or` | Wiktionary | ? | ? | Stanza |
| Old Armenian | `xcl` | Wiktionary | ? | ? | Stanza |
| Old Czech | `zlw-ocs` | Wiktionary | ? | ? | ? |
| Old English | `ang` | Wiktionary | ? | ? | Stanza |
| Old French | `fro` | Wiktionary | ? | ? | Stanza |
| Old High German | `goh` | Wiktionary | ? | ? | ? |
| Old Irish | `sga` | Wiktionary | ? | ? | ? |
| Old Norse | `non` | Wiktionary | ? | ? | ? |
| Old Polish | `zlw-opl` | Wiktionary | ? | ? | ? |
| Ottoman Turkish | `ota` | Wiktionary | ? | ? | Stanza |
| Pali | `pi` | Wiktionary | ? | ? | ? |
| Pannonian Rusyn | `rsk` | Wiktionary | ? | ? | ? |
| Persian | `fa` | Wiktionary | Hy-MT2 | ? | Stanza |
| Plautdietsch | `pdt` | Wiktionary | ? | ? | ? |
| Polski | `pl` | Wiktionary | Hy-MT2 | ? | Stanza |
| Português | `pt` | Wiktionary | Hy-MT2 | ? | Stanza |
| Proto-Finnic | `urj-fin-pro` | Wiktionary | ? | ? | ? |
| Proto-Germanic | `gem-pro` | Wiktionary | ? | ? | ? |
| Proto-Slavic | `sla-pro` | Wiktionary | ? | ? | ? |
| Proto-West Germanic | `gmw-pro` | Wiktionary | ? | ? | ? |
| Punjabi | `pa` | Wiktionary | ? | ? | ? |
| Romanian | `ro` | Wiktionary | ? | ? | Stanza |
| Sanskrit | `sa` | Wiktionary | ? | ? | Stanza |
| Scots | `sco` | Wiktionary | ? | ? | ? |
| Scottish Gaelic | `gd` | Wiktionary | ? | ? | Stanza |
| Serbo-Croatian | `sh` | Wiktionary | ? | ? | ? |
| Sicilian | `scn` | Wiktionary | ? | ? | ? |
| Slovak | `sk` | Wiktionary | ? | ? | Stanza |
| Slovenian | `sl` | Wiktionary | ? | ? | Stanza |
| South Levantine Arabic | `ajp` | Wiktionary | ? | ? | ? |
| Sundanese | `su` | Wiktionary | ? | ? | ? |
| Swahili | `sw` | Wiktionary | ? | ? | ? |
| Swedish | `sv` | Wiktionary | ? | ? | Stanza |
| Tagalog | `tl` | Wiktionary | Hy-MT2 | ? | ? |
| Tajik | `tg` | Wiktionary | ? | ? | ? |
| Tamil | `ta` | Wiktionary | Hy-MT2 | ? | Stanza |
| Telugu | `te` | Wiktionary | Hy-MT2 | ? | ? |
| Thai | `th` | Wiktionary | Hy-MT2 | ? | ? |
| Tibetan | `bo` | Wiktionary | Hy-MT2 | ? | ? |
| Türkçe | `tr` | Wiktionary | Hy-MT2 | Paddle / Vision | Stanza |
| Urdu | `ur` | Wiktionary | Hy-MT2 | ? | Stanza |
| Uyghur | `ug` | Wiktionary | Hy-MT2 | ? | Stanza |
| Uzbek | `uz` | Wiktionary | ? | ? | ? |
| Venetian | `vec` | Wiktionary | ? | ? | ? |
| Vietnamese | `vi` | Wiktionary | Hy-MT2 | ? | ? |
| Volapük | `vo` | Wiktionary | ? | ? | ? |
| Votic | `vot` | Wiktionary | ? | ? | ? |
| Welsh | `cy` | Wiktionary | ? | ? | Stanza |
| West Circassian | `ady` | Wiktionary | ? | ? | ? |
| Western Frisian | `fy` | Wiktionary | ? | ? | ? |
| Yakut | `sah` | Wiktionary | ? | ? | ? |
| Yiddish | `yi` | Wiktionary | ? | ? | ? |
| Yoruba | `yo` | Wiktionary | ? | ? | ? |
| Zulu | `zu` | Wiktionary | ? | ? | ? |
| Русский | `ru` | Wiktionary | Hy-MT2 | ? | Stanza |
| Українська | `uk` | Wiktionary | Hy-MT2 | ? | Stanza |
| العربية | `ar` | Wiktionary | Hy-MT2 | ? | Stanza |
| 中文 | `zh` | Wiktionary | Hy-MT2 | ? | ? |
| 中文（台灣） | `zh-tw` | ? | Hy-MT2 | ? | ? |
| 中文（繁體） | `zh-hant` | ? | Hy-MT2 | ? | Stanza |
| 中文（香港） | `zh-hk` | ? | Hy-MT2 | ? | ? |
| 日本語 | `ja` | Jitendex | Hy-MT2 | MeikiOCR / Vision | Rules |
| 한국어 | `ko` | Wiktionary | Hy-MT2 | ? | Stanza |
