# Development

See the [user guide](USER_GUIDE.md) for everyday use and
[AGENTS.md](../AGENTS.md) for repository conventions. The shared desktop app is
the main entrypoint; the original Japanese and Turkish clients remain available
for compatibility.

## Run from source

Use Python 3.12 for the desktop dependencies. On Windows:

```powershell
py -3.12 -m venv .venv-desktop
.\.venv-desktop\Scripts\python -m pip install -e .
.\Start-Meikipop.cmd
```

On macOS, create `.venv`, install with `python -m pip install -e .`, and use
[Start-Meikipop.command](../Start-Meikipop.command). Grant screen/input
permissions to the launching app or terminal. `meikipop`, `meikipop search`
and `meikipop-search` open the shared popup;
`python -m meikipop.scripts.quick_lookup --no-ocr` starts dictionary search alone.
Use Settings for explicit dictionary, OCR and model downloads.
The Windows source launcher uses the installed app's settings and data. Quit
the running tray app first; single-instance forwarding otherwise opens that copy.

## Architecture and constraints

Paths below are relative to `src/meikipop/`.

| Area | Main modules | Contract |
| --- | --- | --- |
| Dictionary library | `dictionary/library.py`, `dictionary/search.py` | Indexed local Yomitan packs; atomic imports, explicit ordering and removal; cache invalidation follows library revisions. |
| Language handling | `language/profiles.py`, `language/support.py`, `language/*_analyzer.py` | Preserve text offsets and dictionary-supported alternatives. Keep language-specific analysis separate. |
| Results and settings | `gui/quick_lookup.py`, `gui/dictionary_manager.py` | Shared renderer; retain source labels, independent expansion, selection and Back. |
| Installed data | `data_assets.py`, `gui/data_manager.py` | Worker inventory and sizes; shared models precede per-language downloads. Reuse setup jobs and dictionary removal; never delete linked external data. |
| Screen lookup | `gui/unified_ocr.py`, `gui/lookup_session.py`, `ocr/` | Capture/OCR and lookup run off the UI thread. Reject stale results; pinning freezes the current result. |
| Translation | `dictionary/translation.py` | Explicit model setup; lazy local inference, cancellation and loopback-only custom servers. |

Japanese uses bundled deconjugation rules. Its headword/reading groups rank by
installed frequency ranks, kana preference and deconjugation cost. The result
limit applies to ranked groups, retaining their source records and dictionary order.
Full dictionary matches precede prefix scanning; shared search and OCR use the
existing maximum lookup length for that scan, including it in cache identity.
Manual Japanese search adds offline romkan2 reading candidates without changing
the input or OCR lookup. Fully converted readings must match the whole query;
deconjugation and ranking reuse Japanese lookup. English results retain precedence
and ambiguous romaji readings are appended. Phrase checks still require exact
headwords; explicit English-to-Japanese translation uses the existing translator.
Turkish uses Zeyrek 0.1.3, accent
recovery and precomputed lexicon rankings; exact entries and imported forms
retain precedence. Full morpheme paths remain attached to their analyses.
Turkish lookup never starts Stanza. Other supported languages can install an
optional Stanza fallback; Russian and Persian also have bounded spelling
recovery. Imports stay lazy and runtime analysis stays offline.
Activating Turkish prepares a shared analyzer in the background; parsing is
serialized on lookup workers. Missing definitions retain analyses separately
from dictionary entries. Disclosure edits batch layout updates, and Paddle
keeps stable per-language scan callbacks so unchanged pixels reuse OCR.
Disclosure preserves the scroll offset; streaming text retains its text anchor.
Japanese headword and compact-card kanji links share one detail pane below the
dictionary viewport. Selection replaces its contents without rebuilding the
dictionary document. A compact vertical splitter remembers the kanji height share.
Without a saved split, its position fits the rendered glyph block and pane header,
subject to available space. Opening and closing kanji never resize the popup.
Lookup prepares kanji data for every returned headword in result order.
Sticky headings retain the ruby and pitch object renderers and forward links
without navigating their own document.
Snap scrolling keeps its section clipping during progress-bar dragging and maps
the pointer to the nearest reading stop without changing selection.
Wheel notches and arrows move by measured text lines within a section; page
stops use those same line boundaries. Viewport clipping excludes partial text
lines at the sticky heading and bottom edge while retaining oversized content.
Sticky heading height follows its laid-out fragment and source block, including
after width changes; it does not reserve extra padding over the first body line.
Kanji summaries merge exact duplicate values across available sources, retain
source attribution and show conflicting stroke counts separately. More appends
source-specific reference fields without rebuilding the summary. Unstructured
dictionary text stays verbatim; Anki exports retain complete source records.
Automatic popup fitting stays separate from the user's chosen reading size.
Pinning batches content and layout changes and completes fitting before repainting.
Nested document updates leave inherited paint suppression to the parent window.
Preview defaults to one definition without grammar labels; pinned results have no definition cutoff.
Dictionary display preferences only control whether a section starts collapsed.
Popup actions share the first visible sentence or headword line, reserving their
measured width. Button visibility and sentence size are saved per profile.
Multiple headword/reading groups have their own audio and Anki controls anchored
to cached heading blocks. Anki exports and saved-note state belong to that group;
sentence actions and automatic pronunciation retain their existing scope.
Translation uses a separate reading surface and the existing worker; returning
keeps the dictionary document, selection and scroll intact. Sentence links use
the full captured context, never the compact display text. Preview clicks only
pin; their mouse release never activates links exposed by the pinned layout.
Lookup autoplay runs on new lookup results, never on translation completion,
history restoration or rendering. Pin autoplay follows its separate preference.
Windows OCR popups over a fullscreen source expand without activation and reject
mouse activation, keeping the source foreground and its taskbar hidden. The
existing Windows input hook routes unmodified arrows, Page Up/Down and Home/End
and configured popup actions to the pinned popup only while its source remains
foreground; matching releases are consumed even after dismissal. Other keyboard
input stays with the source.
Manual search retains normal focus behavior. Borderless fullscreen uses the same
native monitor-bounds check. Side buttons page while over the popup and can be
disabled per profile.
The text lookup shortcut opens selected text or a blank search input, without
falling back to clipboard contents. Foreground changes still cancel capture.
Unhandled native popup events return `(False, 0)` directly. Calling PyQt's base
`nativeEvent` can crash Windows handle creation; a hidden native-window fixture
covers creation, capture exclusion, focus tracking and mouse activation.
Settings groups lookup and popup bindings in Shortcuts, reusing the key recorder
and existing Anki shortcut storage. Saved bindings and disabled actions survive
profile switches. Popup actions yield to text fields, and native action repeats
are suppressed while navigation keys retain repeat scrolling. Escape retains
the existing dismissal path.
New keyboard holds do not start OCR while a popup is pinned, so modifier-based
popup actions cannot replace the result before their primary key arrives.

Keep OCR usable on its own. Non-OCR lookup actions and text shortcuts remain
independently configurable. Reuse shared rendering and input components;
preserve Japanese behavior when adding another language. Model weights,
dictionary packs, generated assets and environments stay outside Git.
Settings save screen, pin and text shortcuts independently. OCR component
validation only gates provider setup; rejected choices restore the saved controls.
Setup jobs share one control list for disabling and restoring their inputs.
Cursor-leave dismissal is an app-wide opt-in, including pinned popups; geometry,
active selection, menus and Settings prevent unintended dismissal.
Data removal validates owned paths before deletion. Removing a language deletes
its packs, Stanza data and Japanese font, while shared OCR/translation data stays.
Paddle's shared download retains its existing `languages/tr/paddle` storage path.
Mapped files remain visible as pending removals and are collected on a startup worker.
Model changes invalidate OCR caches on their worker; dictionary refresh drops only
Stanza analyzers whose models were removed. Runtime-only translation setup preserves
installed models. Automatic translation reverses the pair when a saved target
matches the detected source; explicit manual directions retain validation.

Anki's popup action snapshots the lookup and saves once on a worker, including
glossary conversion and mapped media preparation. Native Anki duplicate checks
precede preparation, with prevent/allow policies and deck, deck-tree, selected-deck
or collection scopes per profile. Selected decks are checked in one request and
always include the destination; the final save retains Anki's native scope guard.
Only mapped glossaries, furigana and pitch are prepared; screenshots use fast,
lossless PNG encoding. `glossary-first` uses the first
entry, `glossary` uses every returned entry, and `popup-selection-text` remains
separate. Hover scanning retains the active monitor's full capture for Anki while
OCR uses only the selected area, with both images taken from the same frame.
The hover scan area persists globally with its screen geometry and scale;
restore it only on a matching display. Hover scanning starts disabled.
Automatic popup hides keep hover scanning active inside the area; explicit
dismissal pauses it until the pointer leaves and returns.
Completion only marks the submitted lookup as saved; its checkmark
opens the saved note in Anki's browser. Sentence furigana uses exact dictionary
headwords only, without deconjugation or full result preparation. Card glossaries
are left-aligned with compact source labels and native HTML ruby; popup rendering
stays separate.
Existing-note indicators use batched native `dupe:` searches and exact deck IDs,
including original decks for filtered cards. Checks are worker-bound and keyed by
lookup revision, headword groups and settings; stale results never mark new words.
Unavailable Anki leaves mining usable. Allowing duplicates keeps the add action.
`kanji-details` uses the captured Japanese lookup data in headword order and shares
the full kanji content renderer, with card HTML independent of popup links and fonts.

**Do not add LLM explanation, rewriting, aggregation or reranking to dictionary
lookup.** The [experiment record](LLM_EXPERIMENTS.md) documents the measured
benefits, failures and decision that integration is unjustified. Explicit
sentence translation is a separate feature.

Language availability lives in [support.py](../src/meikipop/language/support.py)
and the translation model registry. Settings uses those definitions; avoid
maintaining a second exhaustive language table in documentation.

## Validation

After implementation changes, run the fixture suite once with the project
environment:

```sh
python -m unittest discover -s tests
```

Use small fixtures for lookup, rendering, cancellation and import changes.
Real-model checks are for analysis changes or specific failures, not routine
documentation work. OCR accuracy, global input, exclusive fullscreen, display
scaling and clean-machine installation still need platform acceptance.
`MEIKIPOP_TIMING=1` enables stage timings, including Anki preparation and requests,
without logging text, pixels or paths.

## OCR providers

The shared desktop selects providers explicitly in
`gui/unified_ocr.py` (`ScanWorker.provider`), with language coverage in
`language/support.py`. Adding a provider also requires its Settings/setup
handling; dropping a directory into `ocr/providers/` does not register it here.
Keep recognition local, model setup explicit and initialization worker-bound.

The legacy Japanese client discovers `OcrProvider` subclasses from packages in
`src/meikipop/ocr/providers/`. Copy the `dummy/` package, retain `__init__.py`
and `provider.py`, supply a unique `NAME`, and implement
`scan(PIL.Image.Image) -> Optional[List[Paragraph]]`. Return `[]` for no text or
`None` for failure. Select it through that client's tray OCR menu.

Both paths use [ocr/interface.py](../src/meikipop/ocr/interface.py):
`Paragraph(full_text, words, box, is_vertical)` contains
`Word(text, separator, box, source_start=None)` records. Preserve the original
text and offsets. Boxes use normalized center x/y, width and height relative
to the input image: a pixel box `(x, y, w, h)` in an image `(W, H)` becomes
`((x + w/2)/W, (y + h/2)/H, w/W, h/H)`. Supply actual writing orientation;
a tall box alone does not establish vertical text.

### Optional Paddle ONNX export

Ordinary Paddle setup uses the native runtime. An optional ONNX export needs
a separate Python 3.12 conversion environment; keep the desktop on Paddle 3.2.2.
Install the OCR models first with `meikipop setup-turkish-ocr`, then:

```powershell
py -3.12 -m venv .venv-ocr-export
.\.venv-ocr-export\Scripts\python -m pip install paddlepaddle==3.1.1 paddle2onnx==2.1.0 onnx==1.17.0
.\.venv-ocr-export\Scripts\python -m pip install --no-deps -e .
.\.venv-ocr-export\Scripts\python -m meikipop.scripts.export_turkish_ocr --source-dir "$env:USERPROFILE\.paddlex\official_models" --output build\turkish-onnx
.\.venv-desktop\Scripts\python -m meikipop.scripts.turkish setup-turkish-ocr --onnx-dir build\turkish-onnx
```

Setup verifies source/export hashes and loads both models before activation.
Normal setup restores native Paddle; `--rollback` restores the previous asset
installation. Conversion dependencies are not needed at runtime.

## Packaging and compatibility

Desktop releases contain the Windows setup EXE and two macOS DMGs, for Apple
silicon and Intel. Bundles include Python and inference libraries; user
dictionaries and model weights are downloaded separately. Windows upgrades
preserve settings/data; uninstall offers removal, also available unattended
through `/REMOVEUSERDATA=1`.

macOS releases reuse one self-signed identity; PR builds are ad-hoc signed.
Create the release identity with OpenSSL 3 and
`bash packaging/create-macos-signing.sh /absolute/private/backup-directory`.
Store base64-encoded `signing.p12` as `MACOS_SIGNING_P12` and `password.txt`
contents as `MACOS_SIGNING_PASSWORD` in repository Actions secrets. Back up
both outside Git and reuse them across releases and architectures. Apple
notarization and Windows publisher signing still require release credentials.
Permission retention across macOS updates needs hands-on verification.

`meikipop legacy-japanese` retains the original Japanese app;
`meikipop-turkish` and [Start-Turkish.cmd](../Start-Turkish.cmd) retain the
separate Turkish client. Its TDK/Wiktionary/KeNet assets, optional Stanza,
`languages/tr` data and `Meikipop/Turkish` settings remain separate from shared
Yomitan packs and `Meikipop/QuickLookup`. Legacy setup commands remain in
`meikipop.scripts.turkish`; use its help for individual asset commands and
close that client before asset updates.

## Upstream work

Japanese rules were inherited from upstream Meikipop's
[Nazeka rules](https://github.com/wareya/nazeka/blob/master/dict/deconjugator.json).
Turkish analyzer fixes/context preferences and Persian spelling recovery were
adapted from [Anki Miner](https://github.com/0xzerolight/anki_miner/tree/808b5208bf93d919b3f18ea3aba66db5fd7fd0ea/anki_miner/languages).
Shared word/sentence policies were independently implemented with its registry
design as a reference. Pitch, input and Anki integration drew on
[Chibipop](https://github.com/stellarie/chibipop). Anki duplicate scopes and
preparation ordering follow [Mangatan](https://github.com/1Selxo/Mangatan/tree/6022576909b2cbc9a97286822f801d316b30371b/lib/services/mining).
The Screen AI adapter follows
[Meikikai's native bridge](https://github.com/hectahertz/meikikai/tree/50efb401/src/meikikai/ocr/providers/chrome_screen_ai).
Licenses and attributions ship in `src/meikipop/resources/licenses/`.
