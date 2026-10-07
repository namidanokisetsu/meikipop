Updated: 2026-10-07

# Shared popup setup

## Launch

For normal installation, download the Windows setup EXE or macOS DMG from the
[latest release](https://github.com/namidanokisetsu/meikipop/releases/latest).
A new installation starts with Japanese only. Adding a language profile offers its
recommended downloads once, in one optional checklist. **Later** dismisses it permanently;
all downloads remain available in Settings. Every item is optional, including Jitendex.
Translation defaults unchecked, with Lightweight or Quality choices. There is no separate setup menu.
**Settings / Resources** lists all dictionary, OCR, base-form and translation downloads.
Green indicators report available files; the current OCR and translation selections appear
at the top. **Use** selects an installed translation model for the current profile.
Translation weights and the Paddle OCR model are shared across profiles, with one copy
per model. Base-form models and dictionaries belong to their respective languages. Installed
base-form models are used automatically. Translation detects the input language
within the displayed language pair; manual direction, streaming and keep-warm
controls are under Advanced. Installed local models start when translation is requested.
Deleting a dictionary removes its ready indicator. Dictionaries keeps import, removal,
priority and enable controls; OCR and Translation keep configuration controls.


On macOS, allow **Input Monitoring** for global shortcuts, **Accessibility** for
copying selected text from other apps, and **Screen Recording** for OCR in
System Settings → Privacy & Security, then reopen Meikipop. Shortcuts can be
recorded and saved before permission is granted. Command and Control are separate;
re-record an older shortcut if it used the wrong modifier. Packaged diagnostics
are in `~/Library/Caches/meikipop/meikipop.log` and `meikipop-runtime.log`.
The DMGs are ad-hoc signed, without Apple notarization. Apple Vision replaces the
Windows OCR engines; global pin clicks also reach the underlying app on macOS.
After an update, macOS can retain permissions for the old signature. If a switch
is on but access still fails, remove Meikipop from that list and add the installed
app again, then reopen it.

For a source checkout:

Use [Start-Meikipop.cmd](../Start-Meikipop.cmd) on Windows or
[Start-Meikipop.command](../Start-Meikipop.command) on macOS. The Windows launcher
prefers the checkout's `.venv-desktop` (the Python 3.12 desktop environment)
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
Definition, forms, frequency, Japanese pitch and kanji packs are indexed on disk without
replacing `dictionary.pkl`. Enable packs and move them up or down; changes save immediately.
Download recommended packs in **Resources**, or select an installed pack in Dictionaries
and press **Remove**. Removal deletes all revisions of that dictionary so an older copy cannot reappear.
Cancellation keeps completed imports and discards the unfinished pack.
Imports run in a separate process; closing Settings leaves them running. CRC
mismatches are warnings when the JSON and dictionary entries remain valid.
Archive language metadata takes precedence; for a legacy archive without it,
the selected profile supplies its language.

Choose a language profile from the tray's right-click menu or the top of Settings.
**Add language…** offers languages with a recommended dictionary download or managed
translation support. Importing a dictionary also makes its source language available.
Each profile owns its dictionary list, OCR provider, translation pair/model,
appearance and audio preferences. Lookup detects the input side of that pair
and uses only that profile's dictionaries. Japanese deconjugation and Turkish accent recovery have
dedicated handling. Other languages use exact entries, readings and imported
forms; importing a dictionary does not provide a universal morphology model.
Imported Turkish forms retain the dictionary's grammar labels, including alternative analyses.
Reimport an older forms pack to restore labels discarded by earlier versions; existing dictionary preferences are preserved.

Typed search opens on the tray's screen with keyboard focus. Enter searches immediately.
Sentence lookups translate automatically, including Japanese input without punctuation
when the dictionary matches only its beginning. Translation after other incomplete
dictionary matches remains an optional setting in **Translation**, off in new profiles.
Translate remains available explicitly.
Hover OCR stays dictionary-only.
OCR translations show the original sentence, a divider, then the translation. Typed translations
show only the translation below the input. Translate and audio
sit at the top right; Back and a compact nested-lookup trail sit at the bottom left,
with Copy and Close at the right. Back restores the previous result and sentence context.
Dictionary sections have independent previews and expansion controls. **Appearance → Snap scrolling**
optionally steps between dictionary blocks, paging through long blocks with overlap.
It defaults off for each language; the scrollbar remains freely draggable. Left-click a preview
or use the scan gesture to freeze and resize it. Above-text previews expand upward;
other previews grow down when space allows, switching upward near the bottom edge. Escape, outside click, Close, or a new
scan leave the result. Entering a preview pauses its dismissal grace; leaving rearms it.
Search also supports edge and corner resizing. Imported frequency, inflection and kanji information uses compact labels.
Frequency defaults to one harmonic-mean rank across enabled rank dictionaries, taking
the best matching rank per dictionary. **Dictionaries → Combine frequency ranks**
switches between the combined number and individual labels. Counts and nonnumeric
bands are excluded from the mean.
Import a Yomitan pitch dictionary with the Japanese profile selected. **Dictionaries →
Pitch accent** controls its display: overlines mark high morae, ꜜ marks a drop,
and brackets show the supplied accent number or H/L pattern. Sources and alternative
accents remain separate. Reimport an older mixed pack to add previously skipped pitch data.
The copy button previews its sentence on hover; action icons have short tooltips.
Dictionary-internal tooltips remain hidden.
Kanji always use compact cards with meanings and readings, without a separate label or details toggle.

## Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) in Anki and keep Anki open.
In **Settings → Anki**, enable the integration and press **Reload decks and fields**.
Choose a deck and note type. Fields match by name, ignoring case and separators,
with aliases and conservative spelling matches. Saved mappings stay intact; **Match fields**
replaces them with new suggestions. Map the first field to **Word**;
**Definition**, **Reading**, **Sentence**, **Dictionary**, **Frequency**, **Pitch accent**
and **Language** are available for the others. Set the optional API key only if your
AnkiConnect configuration requires one. Each language profile keeps its own choices.

Use the round **+** in the popup to choose the entry and review its definition and
sentence, then press **Add**. Selected popup text becomes the initial definition.
The optional recorded shortcut works while the popup has focus and defaults off.
Duplicate checks use the first field, chosen deck and note type, excluding child decks.
Existing notes are never updated. If Anki does not confirm a save, check Anki before
retrying; the app does not retry writes automatically.
The Anki button sits at the bottom left. Kikitori Reading fields map automatically,
including sentence furigana, editable translation, picture and pitch positions.
Furigana uses installed Japanese dictionaries; unknown or inflected readings stay plain.
OCR exports reuse the captured screen, without the popup. Frozen scans use the full display;
live scans use the recognized region. Uncheck **Include screenshot** to omit it.
The currently loaded word recording is attached when it matches the selected word.
System speech is not recorded; Kikitori Reading retains its native TTS fallback.

The top controls are Translate, Read sentence, then Read word. In pinned OCR results they
sit alongside the heading; language switching stays in the tray and Settings.
Sentence reading uses system TTS even when a Japanese word-audio database is configured.
**Audio → Source priority** enables and orders Online pronunciations, System voice, and
Local recordings with checkboxes, dragging, or arrow buttons. Enabled sources run top to
bottom; System voice is first by default. Saved source choices are retained.
Online uses Wiktionary and Lingua Libre recordings on Wikimedia Commons. It sends the word
and language, caches recordings and misses in memory, and requires no account; coverage
depends on contributed recordings. Database controls appear when local sources are enabled;
`android.db` is the supported Local Audio Server format, not an Android requirement.
Right-click Read word to choose a source or open the current recording's attribution page.
Sentence reading always uses an installed system voice.
**Settings → Audio → Autoplay** saves immediately per profile: Off, On lookup, or When pinned.
When pinned keeps OCR hover previews silent and plays when expanded. Typed lookups never autoplay audio.
Automatic selection lookups honor On lookup autoplay.
Each pronunciation autoplays at most once during a held scan shortcut; manual audio can repeat.
**Settings → Appearance** defaults to Green: black at 80% opacity, soft green accents
and pale text. Monochrome Dark, Light and Custom remain available.
Background opacity uses 0-100% and is available for every theme. Changes apply immediately; Custom starts with the profile's saved
colors and remembers them when switching presets. Removed dark presets migrate to
Monochrome Dark, keeping saved colors in Custom. Appearance remains independent per profile.
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
Pinned OCR results show the original sentence in compact text above the entry.
**Settings → Appearance → Show sentence when pinned** toggles it per profile;
it defaults on and does not change what Copy sentence copies.
Dictionary sections labeled **More** stay collapsed when pinned; click their label
to open or close them independently. Back restores opened sections.

**Settings → Shortcuts** configures one text-lookup shortcut and optional automatic selection.
Search defaults to Ctrl+Shift+D (Cmd+Shift+D on macOS): it copies selected
text, preserving the clipboard, or uses the clipboard if nothing is selected. The prefilled
input remains selected for immediate typing and follows the profile's translation options.
Select a word within typed or pasted input and press Enter, use the lookup shortcut,
or choose **Look up** in its context menu. The full input stays in place and supplies
sentence context for optional lemma lookup, translation, audio, Copy sentence and Back.
Inside results, select text and choose **Look up** in its context menu or use the existing
lookup shortcut. Otherwise that shortcut closes the popup. **Look up selection inside results**
is separate from global selection watching: new profiles default it off, existing profiles
retain automatic lookup. Native selection and copying remain available. Ordinary settings save immediately;
downloads, imports and removals require their action buttons.
Automatic lookup on double-click or drag selection is disabled by default and configured per profile.
These previews leave keyboard focus in the original app. Selected-text lookup preserves the clipboard.
Copy sentence closes the popup; copying selected text keeps it open.

The provisioned local library uses the full Turkdict pack and Jitendex
(2026-10-03), plus KANJIDIC and Jiten metadata packs. These large data files are
outside Git. Additional local Yomitan packs can be added through the same UI.

### Optional lemma fallback

Exact entries and imported forms remain first. Russian also tries е/ё spelling
variants after a miss, using the installed dictionary and forms without a model.
**Settings → Dictionaries → Find base forms** enables optional Stanza models for
the selected non-Japanese profile. **Install model** installs its dependencies and
language model in the Python desktop installation; the checkbox alone never downloads.
The adjacent status distinguishes missing support from missing models.
Japanese keeps its bundled rules. Models run in lookup workers, with original OCR
sentence context where available; results are labeled as lemma matches.

Models live with app data at `languages/<code>/stanza/1.14.0` (under
`%LOCALAPPDATA%/meikipop` on Windows), separate from dictionary ZIPs and translation
models. The status tooltip shows the full path. Equivalent explicit setup:

```powershell
.venv-desktop/Scripts/python -m meikipop.scripts.setup_morphology ru --install
```

Replace `ru` for another Stanza language. Setup downloads only the base-form pipeline;
runtime never downloads them. Missing models leave exact/form lookup available and
report a setup error on a lemma miss. UI setup refreshes lookup automatically;
after command-line setup, toggle the option to retry. Model downloads can be cancelled;
source installations finish an active dependency installation before stopping.
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

New language profiles inherit the current profile's screen lookup shortcuts,
including an explicitly disabled shortcut. Clear both screen lookup shortcuts to
disable OCR; there is no additional toggle.
**Settings → Shortcuts → Pin with mouse** selects left click, middle click, or popup-only pinning.
Windows consumes the configured outside pin click while a scan preview is ready;
on macOS and Linux it also reaches the underlying app. Other clicks are unchanged.
**Appearance → Compact preview** is on by default; turn it off for full definitions immediately.
Scanning always requires a held trigger. Automatic hover scanning has been removed;
old saved hover preferences are ignored. OCR runs separately from dictionary search
and retains visible sentence context.

Each profile shows one OCR selector. Windows defaults remain
**MeikiOCR (CPU)** for Japanese and **PaddleOCR** for Turkish; macOS defaults to
**Apple Vision**. PaddleOCR and **Chrome Screen AI (local)** can also be selected
in other language profiles. Languages outside the installed Paddle model's coverage,
including Russian, default to Screen AI on Windows; incompatible Paddle choices
are disabled. Indonesian uses Paddle. Changing the selection invalidates pending scans and
uses a separate recognition cache. Selecting a provider never downloads a model.

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

- **Windows Japanese:** install `meikiocr>=0.3.5`. Its local recognizer supplies
  text boxes for Japanese lookup. Model setup is explicit and separate from
  ordinary typed lookup.
- **PaddleOCR (50 languages):** use Python 3.12 and install the optional `[turkish-ocr]`
  dependencies, then run `meikipop setup-turkish-ocr` in that environment.
  The dependency group aligns OpenCV packages at 4.10.0.84. PaddleOCR 3.7 uses
  local PP-OCRv6 small detection and recognition models with word boxes,
  CPU inference, four threads and oneDNN acceleration with Paddle 3.2.2. Paddle
  3.3.1 failed locally in the optimized CPU path, matching the reported
  [oneDNN conversion regression](https://github.com/PaddlePaddle/Paddle/issues/77340).
  One shared model pair recognizes Chinese, Japanese, English and 46 Latin-script
  languages, including Turkish. The setup command retains its original Turkish
  name; its models serve every PaddleOCR profile. The adapter rejoins accent
  fragments and preserves nearby wrapped lines for sentence copying.
  Indexed Turkdict lookup does not require Stanza or Paddle.
- **macOS:** the unified popup uses native Apple Vision for OCR. Available
  recognition languages depend on the installed macOS version. Grant Screen
  Recording and Input Monitoring/Accessibility permissions to the terminal or
  app that launches Meikipop. Unsupported OCR languages produce an actionable
  message; their typed dictionary lookup remains available.

The new shared scan path uses local recognition. The legacy Japanese client
still offers its original providers, including explicitly selected remote OCR.

Screen lookup retries a clipped paragraph with a larger crop, at most twice.
Growth stays on the current display and retains nearby sentence context.
**Settings → OCR → Freeze while held** captures the current display once per hold.
Moving between words and expanding the crop reuse that screenshot. Release the scan
key to refresh; moving to another display requires a new hold. It defaults on per
profile. Turn it off for live scanning of changing subtitles.

## Local translation

Choose a model in **Settings → Translation** and use **Download selected model**
once. **Quality** uses Tencent's [Hy-MT2-7B Q8_0](https://huggingface.co/tencent/Hy-MT2-7B-GGUF)
(about 8 GB of weights); **Lightweight** uses
[Hy-MT2-1.8B Q8_0](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF) (about 2 GB).
Both support translation among 33 languages plus five regional and minority
varieties, including Traditional Chinese, Cantonese, Tibetan, Kazakh, Mongolian
and Uyghur; the [coverage table](#language-coverage) lists every profile.
Quality is the default; changing models is explicit and there is no automatic fallback.

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
GPU; Apple Silicon uses Metal. By default the server frees model memory after an idle
minute and reloads it when needed. **Keep model warm** retains that memory after intentional
use; it defaults off and never starts a model at app launch. Changes take effect on the next
translation without interrupting an active request. The app stops only its own server when
exiting. CPU execution is possible
but may be slower. Weight size excludes runtime and context memory, so close
other GPU-heavy applications if necessary.

**Custom local server** accepts a local chat-completions endpoint and model
alias. Its language coverage follows the selected model; it can provide additional
translation pairs beyond Hy-MT2. It is never started or downloaded by the app.
Requests use numeric loopback addresses, bypass proxies and reject redirects. No text goes to a
cloud translation service. Search and translation do not download anything;
neither Torch nor the older Argos/CTranslate2 backend is required or offered.
Translation arrives in small batches. The Translate icon becomes Cancel while busy;
its tooltip identifies startup and the selected model. Editing, closing, or changing
translation settings rejects late output. Automatic fallback retains useful dictionary
content on failure or cancellation. If a custom server rejects streaming, disable
**Stream translation**; the app never retries an expensive request automatically.

## Optional Turkish OCR export

The same Paddle models can run through PaddleX's ONNX Runtime engine. On this
Windows machine, a 1200×480 Turkish fixture took about 75 ms per warm scan with
ONNX Runtime, versus 115 ms with Paddle 3.2.2/oneDNN and 568 ms with the previous
unoptimized setup. Text, word fragments and word coordinates matched exactly
on that fixture; this is not an accuracy benchmark across screen content.

Ordinary OCR setup uses native Paddle. For the optional export, first run
`meikipop setup-turkish-ocr`, then use a separate Python 3.12 conversion environment
from the checkout. Keep the desktop environment on Paddle 3.2.2; the Windows
converter requires Paddle 3.1.1/Paddle2ONNX 2.1.0:

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
Optional developer traces use `MEIKIPOP_TIMING=1` or the `meikipop.timing` debug logger.
They record request/frame stages and discard reasons without text, pixels or paths;
document construction and the first applicable Qt paint are recorded separately.

## Language coverage

Profiles are available for every language below, plus languages from imported dictionaries.
Coverage follows the selected dictionaries, models and providers. Downloads are explicit;
the table describes available features whether or not their resources are already installed.

- **Recommended dictionary:** [Wiktionary](https://yomidevs.github.io/wiktionary-to-yomitan/download/)
  packs provide English definitions; Japanese offers [Jitendex](https://jitendex.org/pages/downloads.html).
  **Import** means use a local Yomitan pack. All profiles support imported definitions, readings,
  forms and frequency dictionaries, with installation, ordering and removal in Settings.
  Frequency defaults to one harmonic rank across enabled rank dictionaries.
- **Hy-MT2 translation:** both sizes share the full
  [language list](https://huggingface.co/tencent/Hy-MT2-7B#supported-languages):
  33 languages plus five regional and minority varieties. **Yes** applies in both directions.
  Custom local servers can extend coverage according to their selected model.
- **PaddleOCR:** the shared [PP-OCRv6 Small model](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html)
  supports 50 languages: Chinese (Simplified and Traditional), Japanese, English and 46 Latin-script
  languages. The table uses profile codes, including equivalent names such as Mandarin and Filipino.
  **MeikiOCR** also supports Japanese. **Chrome Screen AI** provides the languages of its installed
  component; **Apple Vision** provides the recognition languages of the installed macOS version.
  These alternatives are selectable in Settings. Paddle's separate
  [v5 models cover 106 languages](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html);
  Meikipop's installer currently supplies the v6 model pair.
- **Morphology:** Japanese uses bundled deconjugation rules; **Stanza** enables optional lemma
  fallback after installing its [language model](https://stanfordnlp.github.io/stanza/available_models.html).
  Imported forms work in every profile. Turkish also supports accent recovery.
- **Audio:** every profile offers online Wikimedia pronunciations, system TTS, and compatible
  local databases. Available recordings and installed voices determine coverage. The online
  lookup follows [Yomitan's Wikimedia source approach](https://github.com/yomidevs/yomitan/blob/master/ext/js/media/audio-downloader.js);
  it is not a live Forvo integration.

`-` means the named model has no entry for that language; it does not restrict other
providers or imported dictionaries. Script-specific entries apply to the indicated script.
Sources and model versions: PaddleOCR 3.7 / PP-OCRv6 Small, Hy-MT2, and
[Stanza 1.14 resources](https://raw.githubusercontent.com/stanfordnlp/stanza-resources/main/resources_1.14.0.json).

| Language | Code | Recommended dictionary | Hy-MT2 translation | PaddleOCR | Morphology |
| --- | --- | --- | --- | --- | --- |
| Afrikaans | `af` | Wiktionary | - | Yes | Stanza |
| Albanian | `sq` | Wiktionary | - | Yes | Stanza |
| Ancient Greek | `grc` | Wiktionary | - | - | Stanza |
| Armenian | `hy` | Wiktionary | - | - | Stanza |
| Aromanian | `rup` | Wiktionary | - | - | - |
| Assamese | `as` | Wiktionary | - | - | - |
| Assyrian Neo-Aramaic | `aii` | Wiktionary | - | - | - |
| Asturian | `ast` | Wiktionary | - | - | - |
| Azerbaijani | `az` | Wiktionary | - | Yes | - |
| Bangla | `bn` | Wiktionary | Yes | - | - |
| Bashkir | `ba` | Wiktionary | - | - | - |
| Basque | `eu` | Wiktionary | - | Yes | Stanza |
| Belarusian | `be` | Wiktionary | - | - | Stanza |
| Bulgarian | `bg` | Wiktionary | - | - | Stanza |
| Burmese | `my` | Wiktionary | Yes | - | - |
| Cantonese | `yue` | Wiktionary | Yes | - | - |
| Catalan | `ca` | Wiktionary | - | Yes | Stanza |
| Cebuano | `ceb` | Wiktionary | - | - | - |
| Central Bikol | `bcl` | Wiktionary | - | - | - |
| Church Slavic | `cu` | Wiktionary | - | - | Stanza |
| Cimbrian | `cim` | Wiktionary | - | - | - |
| Classical Syriac | `syc` | Wiktionary | - | - | - |
| Coptic | `cop` | Wiktionary | - | - | Stanza |
| Cornish | `kw` | Wiktionary | - | - | - |
| Crimean Tatar | `crh` | Wiktionary | - | - | - |
| Czech | `cs` | Wiktionary | Yes | Yes | Stanza |
| Danish | `da` | Wiktionary | - | Yes | Stanza |
| Deutsch | `de` | Wiktionary | Yes | Yes | Stanza |
| Egyptian | `egy` | Wiktionary | - | - | - |
| Egyptian Arabic | `arz` | Wiktionary | - | - | - |
| English | `en` | Wiktionary | Yes | Yes | Stanza |
| Español | `es` | Wiktionary | Yes | Yes | Stanza |
| Esperanto | `eo` | Wiktionary | - | - | - |
| Estonian | `et` | Wiktionary | - | Yes | Stanza |
| Faroese | `fo` | Wiktionary | - | - | - |
| Filipino | `fil` | Import | Yes | Yes | - |
| Finnish | `fi` | Wiktionary | - | Yes | Stanza |
| Français | `fr` | Wiktionary | Yes | Yes | Stanza |
| Galician | `gl` | Wiktionary | - | Yes | Stanza |
| Georgian | `ka` | Wiktionary | - | - | Stanza |
| Gothic | `got` | Wiktionary | - | - | Stanza |
| Greek | `el` | Wiktionary | - | - | Stanza |
| Gujarati | `gu` | Wiktionary | Yes | - | - |
| Gulf Arabic | `afb` | Wiktionary | - | - | - |
| Hawaiian | `haw` | Wiktionary | - | - | - |
| Hebrew | `he` | Wiktionary | Yes | - | Stanza |
| Hindi | `hi` | Wiktionary | Yes | - | Stanza |
| Hungarian | `hu` | Wiktionary | - | Yes | Stanza |
| Icelandic | `is` | Wiktionary | - | Yes | Stanza |
| Ido | `io` | Wiktionary | - | - | - |
| Indonesian | `id` | Wiktionary | Yes | Yes | Stanza |
| Ingrian | `izh` | Wiktionary | - | - | - |
| Interlingua | `ia` | Wiktionary | - | - | - |
| Irish | `ga` | Wiktionary | - | Yes | Stanza |
| Italiano | `it` | Wiktionary | Yes | Yes | Stanza |
| Javanese | `jv` | Wiktionary | - | - | - |
| Kannada | `kn` | Wiktionary | - | - | - |
| Kashubian | `csb` | Wiktionary | - | - | - |
| Kazakh | `kk` | Wiktionary | Yes | - | Stanza |
| Khiamniungan Naga | `kix` | Wiktionary | - | - | - |
| Khmer | `km` | Wiktionary | Yes | - | - |
| Kyrgyz | `ky` | Wiktionary | - | - | Stanza |
| Ladin | `lld` | Wiktionary | - | - | - |
| Lao | `lo` | Wiktionary | - | - | - |
| Latin | `la` | Wiktionary | - | Yes | Stanza |
| Latvian | `lv` | Wiktionary | - | Yes | Stanza |
| Laz | `lzz` | Wiktionary | - | - | - |
| Lithuanian | `lt` | Wiktionary | - | Yes | Stanza |
| Livonian | `liv` | Wiktionary | - | - | - |
| Lower Sorbian | `dsb` | Wiktionary | - | - | - |
| Luxembourgish | `lb` | Wiktionary | - | Yes | - |
| Macedonian | `mk` | Wiktionary | - | - | - |
| Malagasy | `mg` | Wiktionary | - | - | - |
| Malay | `ms` | Wiktionary | Yes | Yes | - |
| Malayalam | `ml` | Wiktionary | - | - | - |
| Maltese | `mt` | Wiktionary | - | Yes | - |
| Mandarin Chinese | `cmn` | Wiktionary | Yes | Yes | - |
| Manx | `gv` | Wiktionary | - | - | Stanza |
| Marathi | `mr` | Wiktionary | Yes | - | Stanza |
| Middle Dutch | `dum` | Wiktionary | - | - | - |
| Middle English | `enm` | Wiktionary | - | - | - |
| Middle French | `frm` | Wiktionary | - | - | - |
| Mongolian | `mn` | Wiktionary | Yes | - | - |
| Māori | `mi` | Wiktionary | - | Yes | - |
| Navajo | `nv` | Wiktionary | - | - | - |
| Nederlands | `nl` | Wiktionary | Yes | Yes | Stanza |
| Norman | `nrf` | Wiktionary | - | - | - |
| North Levantine Arabic | `apc` | Wiktionary | - | - | - |
| Northern Kurdish | `kmr` | Wiktionary | - | Yes | Stanza |
| Northern Sami | `se` | Wiktionary | - | - | Stanza |
| Norwegian | `no` | Wiktionary | - | Yes | Stanza |
| Norwegian Bokmål | `nb` | Wiktionary | - | Yes | Stanza |
| Norwegian Nynorsk | `nn` | Wiktionary | - | Yes | Stanza |
| Occitan | `oc` | Wiktionary | - | Yes | - |
| Odia | `or` | Wiktionary | - | - | Stanza |
| Old Armenian | `xcl` | Wiktionary | - | - | Stanza |
| Old Czech | `zlw-ocs` | Wiktionary | - | - | - |
| Old English | `ang` | Wiktionary | - | - | Stanza |
| Old French | `fro` | Wiktionary | - | - | Stanza |
| Old High German | `goh` | Wiktionary | - | - | - |
| Old Irish | `sga` | Wiktionary | - | - | - |
| Old Norse | `non` | Wiktionary | - | - | - |
| Old Polish | `zlw-opl` | Wiktionary | - | - | - |
| Ottoman Turkish | `ota` | Wiktionary | - | - | Stanza |
| Pali | `pi` | Wiktionary | - | - | - |
| Pannonian Rusyn | `rsk` | Wiktionary | - | - | - |
| Persian | `fa` | Wiktionary | Yes | - | Stanza |
| Plautdietsch | `pdt` | Wiktionary | - | - | - |
| Polski | `pl` | Wiktionary | Yes | Yes | Stanza |
| Português | `pt` | Wiktionary | Yes | Yes | Stanza |
| Proto-Finnic | `urj-fin-pro` | Wiktionary | - | - | - |
| Proto-Germanic | `gem-pro` | Wiktionary | - | - | - |
| Proto-Slavic | `sla-pro` | Wiktionary | - | - | - |
| Proto-West Germanic | `gmw-pro` | Wiktionary | - | - | - |
| Punjabi | `pa` | Wiktionary | - | - | - |
| Romanian | `ro` | Wiktionary | - | Yes | Stanza |
| Sanskrit | `sa` | Wiktionary | - | - | Stanza |
| Scots | `sco` | Wiktionary | - | - | - |
| Scottish Gaelic | `gd` | Wiktionary | - | - | Stanza |
| Serbo-Croatian | `sh` | Wiktionary | - | - | - |
| Sicilian | `scn` | Wiktionary | - | - | - |
| Slovak | `sk` | Wiktionary | - | Yes | Stanza |
| Slovenian | `sl` | Wiktionary | - | Yes | Stanza |
| South Levantine Arabic | `ajp` | Wiktionary | - | - | - |
| Sundanese | `su` | Wiktionary | - | - | - |
| Swahili | `sw` | Wiktionary | - | Yes | - |
| Swedish | `sv` | Wiktionary | - | Yes | Stanza |
| Tagalog | `tl` | Wiktionary | Yes | Yes | - |
| Tajik | `tg` | Wiktionary | - | - | - |
| Tamil | `ta` | Wiktionary | Yes | - | Stanza |
| Telugu | `te` | Wiktionary | Yes | - | - |
| Thai | `th` | Wiktionary | Yes | - | - |
| Tibetan | `bo` | Wiktionary | Yes | - | - |
| Türkçe | `tr` | Wiktionary | Yes | Yes | Stanza |
| Urdu | `ur` | Wiktionary | Yes | - | Stanza |
| Uyghur | `ug` | Wiktionary | Yes | - | Stanza |
| Uzbek | `uz` | Wiktionary | - | Yes | - |
| Venetian | `vec` | Wiktionary | - | - | - |
| Vietnamese | `vi` | Wiktionary | Yes | Yes | - |
| Volapük | `vo` | Wiktionary | - | - | - |
| Votic | `vot` | Wiktionary | - | - | - |
| Welsh | `cy` | Wiktionary | - | Yes | Stanza |
| West Circassian | `ady` | Wiktionary | - | - | - |
| Western Frisian | `fy` | Wiktionary | - | - | - |
| Yakut | `sah` | Wiktionary | - | - | - |
| Yiddish | `yi` | Wiktionary | - | - | - |
| Yoruba | `yo` | Wiktionary | - | - | - |
| Zulu | `zu` | Wiktionary | - | - | - |
| Русский | `ru` | Wiktionary | Yes | - | Stanza |
| Українська | `uk` | Wiktionary | Yes | - | Stanza |
| العربية | `ar` | Wiktionary | Yes | - | Stanza |
| 中文 | `zh` | Wiktionary | Yes | Yes | Stanza |
| 中文（台灣） | `zh-tw` | Import | Yes | Yes | - |
| 中文（繁體） | `zh-hant` | Import | Yes | Yes | Stanza |
| 中文（香港） | `zh-hk` | Import | Yes | Yes | - |
| 日本語 | `ja` | Jitendex | Yes | Yes | Rules |
| 한국어 | `ko` | Wiktionary | Yes | - | Stanza |
