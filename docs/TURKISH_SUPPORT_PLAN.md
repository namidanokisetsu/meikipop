# Turkish support: Stanza, TDK, and desktop text lookup

Status: implementation plan; no application changes yet.
Written: 2026-09-06.
Branch: `feature/turkish-support`.
Base: `feature/native-input-audio` at `666b479`.
Worktree: `../meikipop-turkish` beside the existing checkout.

## 1. Product scope and decisions

Build a useful Turkish reading tool with accurate lemma lookup, Turkish definitions from TDK, examples, and optional English definitions from Wiktionary. Try Stanza first without conducting an analyzer benchmark or training models. Support different analyzers through one small internal interface, but implement only Stanza and exact lookup initially. A second substantive analyzer can be added later without changing input, dictionary storage, or UI.

The first supported target for the new desktop interactions is Windows. Keep Japanese working. Do not expand this project into a generic NLP platform, dictionary marketplace, or browser extension.

Decisions:

- Default Turkish analyzer: pinned Stanza with its standard Turkish package. Do not load BERT or compare models in this iteration.
- Main dictionary: `ogun/guncel-turkce-sozluk`, v12 SQLite snapshot.
- Runtime dictionary: a compact, indexed SQLite database prepared by our importer. No Turkish pickle, MongoDB server, custom binary format, or enumeration of inflected forms.
- English: optional separate pack made from Kaikki's English-Wiktionary Turkish entries, after the TDK flow works.
- Audio: optional offline TDK recording pack using the existing `android.db` reader schema; validate live recording access before building the full pack.
- Input: existing OCR, explicit clipboard lookup, optional automatic clipboard lookup, and a Windows selected-text shortcut.
- UI: whole-word lookup, numbered senses, usage/POS labels, examples, and a persistent mode for copied text and longer definitions.
- No linguistic benchmarking, model training, automatic translation of TDK definitions, or full suffix explanations in this iteration. Functional checks and manual try-out remain necessary.

## 2. Git organization and maintenance

Use the new worktree for the plan and subsequent implementation. The original checkout stays on `feature/native-input-audio`. Branching from its current HEAD deliberately includes native input and audio fixes; branching directly from upstream would lose them.

Keep this one feature branch for the first usable version. Make reviewable commits by implementation step below; do not create permanent per-language branches. After acceptance, merge into the fork's maintained development branch. If opening a PR before the input branch is merged, use `feature/native-input-audio` as the base so its commits do not obscure the Turkish diff; retarget when appropriate.

For future upstream maintenance, fetch `upstream` and integrate tested upstream changes into the fork's maintained branch, then into this feature branch as needed. Do not rewrite shared branch history or mechanically rebase a released build. Japanese fixes and shared input/UI improvements should remain understandable independently of Turkish data.

Track importer code, schema, source locks, workflow, small fixtures, and this plan in Git. Keep downloaded dictionaries, model weights, databases, generated packs, and virtual environments out of Git. No submodules or Git LFS needed. Do not push or publish as part of writing this plan.

## 3. Source data and what precompilation means

The inspected v12 SQLite artifact contains 99,236 entry rows, 98,159 distinct headword strings, 133,037 sense rows, 45,392 example rows, and 16,666 rows in the idiom/proverb table. These counts overlap. Twenty-five entry rows have no associated sense rows. Treat these as properties of the inspected snapshot, not permanent expected totals.

The artifact is about 29 MB. Its file history last changed on 2024-03-29. The repository's scheduled job updates autocomplete data, not the full definitions database. Check the actual dictionary artifact when deciding whether to update; recent repository activity alone is misleading.

Maintain `resources/turkish/sources.json` with the resolved TDK commit, artifact path, SHA-256, and our importer/schema version. Resolve the full commit and checksum during the first importer implementation. Record the optional Wiktionary dump date, extraction identity, URL and SHA-256 separately. Preserve source attribution and identities as useful data metadata; no additional approval process is part of this plan.

Proposed command:

```text
meikipop build-turkish-dict --output <directory>
```

It uses the checked-in source lock by default and downloads into `paths.cache_dir`. An explicit maintainer update command resolves a new snapshot and updates the lock. Normal application startup never scrapes TDK or fetches GitHub HEAD.

Precompilation consists of:

1. Read the locked source SQLite database; validate its schema and basic integrity.
2. Join headwords, ordered senses, sense labels, examples/authors and phrase relationships.
3. Preserve original spelling and text. Generate NFC and Turkish-aware lowercase search keys separately (`I` to `ı`, `İ` to `i`). Preserve meaningful diacritics; do not fold all Turkish text to ASCII.
4. Build dictionary-convention aliases for verbs: POS-confirmed infinitives such as `yazmak` also get a stem lookup alias `yaz`. Keep aliases separate from literal headwords so the noun `yaz` remains distinguishable. Do not strip `mak/mek` from arbitrary words.
5. Retain multiple entries with the same spelling and ordered senses. Preserve lexical derivatives and multiword headwords.
6. Report malformed/missing records rather than silently dropping them. Omit definitionless rows from visible results unless a valid cross-reference resolves them; record counts in the build report.
7. Write normalized content in stable order, create search indexes, run SQLite integrity and relation checks, and package the output.

Use the Python standard library for the TDK importer. Running it should not require installing PyQt, OCR, Torch or Stanza. Byte-for-byte reproducibility requires a pinned build environment; record it and hash the resulting artifact. Stable source ordering alone is not a promise of identical SQLite bytes across versions.

### Small runtime schema

Use a small number of tables:

- `entries`: stable source-qualified ID, display headword, normalized key, source ID, definition language, ordered senses JSON, optional pronunciation/origin text.
- `lookup_keys`: normalized key, entry ID, key kind (`headword`, `verb_stem`, `variant`), optional POS; indexed by key.
- `relations`: entry ID, related entry ID where resolvable, display phrase, relation kind.
- `metadata`: pack/schema version and source/build identity.

Each sense JSON object contains its text, original order, POS, usage/domain labels, and example text with optional author. The app fetches a few entries at a time; it does not need to query every individual example through relational joins. Use parameterized queries and escape source text when rendering HTML.

Do not use SQLite's default `NOCASE` or `lower()` for Turkish matching. Normalize query keys with the same Python function used by the builder. Distinguish source IDs even when spelling is identical.

## 4. Distribution and refresh policy

Publish dictionary assets separately from executables in the fork's GitHub Releases. Start with a manual `workflow_dispatch` workflow, independent of the current Japanese dictionary workflow. Do not copy its delete-and-recreate release behavior.

Each immutable release contains a zip with `dictionary.sqlite3` and `manifest.json`. The manifest includes pack ID/version, schema version, supported app version, source revisions/checksums, counts, and database checksum. A small release index records the zip URL and SHA-256. Use a TDK pack ID such as `tr-tdk` and a separate optional `tr-en-wiktionary` pack.

Store installed versions beneath `paths.data_dir/languages/tr/`, for example:

```text
languages/tr/
  packs/tr-tdk/<version>/dictionary.sqlite3
  packs/tr-tdk/<version>/manifest.json
  packs/tr-en-wiktionary/<version>/...
  stanza/<model-version>/...
```

On choosing Turkish, provide a setup action with download progress for TDK and the Stanza model. English definitions are a separate checkbox/download. Installation verifies downloads and schema before selecting the new pack. Build/extract into a temporary directory with bounded paths, then activate only after success. Close old database handles before switching on Windows. Keep the previous usable pack for rollback; failed updates leave it selected.

Initially, use an explicit **Check for dictionary updates** action. Check source artifacts monthly as maintainer housekeeping and publish only when their content changes or the importer changes. There is no need for weekly user downloads of an unchanged 2024 snapshot. An automated monthly check can later open a source-lock update PR if manual checking becomes a burden; it is not required for version one. Scheduled GitHub workflows need to live on the default branch when introduced.

Pin Stanza engine and model resources together. NLP model updates are separate from dictionary refreshes; do not silently combine a new engine with old incompatible weights.

For source installs, add a `turkish` optional dependency extra with tested Stanza/Torch constraints and lazy imports. For a first Windows binary, make a separate Turkish-enabled build containing the tested Python NLP dependencies, with model/data downloads outside the executable. Extend the existing PyInstaller build/spec rather than adding a packaged Python sidecar or invoking pip from the running executable. Verify packaging on a clean Windows machine. Expect a materially larger distribution because of Torch; record actual size during packaging, not as a benchmark project.

## 5. Analyzer and lookup organization

Introduce a small internal `Analyzer` protocol:

```text
analyze(text) -> tokens with original start/end offsets, lemma and optional POS
identity -> engine/model version used for cache keys
```

Use Python character offsets consistently inside the application. Preserve original text and offsets when generating normalized lookup keys. Keep source tokens intact when Stanza expands a multiword token internally; do not invent separately selectable source spans for expansions.

Implement `StanzaAnalyzer` and `ExactAnalyzer`. A simple registry/config setting is enough for future analyzers; no plugin discovery, external service contract, ensemble or automatic analyzer chooser. Exact mode is a usable fallback and is labeled as such, never silently presented as Stanza results.

Stanza runs in the existing background lookup processing path, initialized once when needed. Load only `tokenize,mwt,pos,lemma` for the pinned Turkish default package. No dependency parser, NER or BERT needed initially. Disable inference-time downloads; missing resources show setup status and permit exact lookup.

Analyze complete OCR lines or copied sentences once and cache the token results. Cache identity includes text, language and analyzer/model identity. Dictionary result cache additionally includes enabled pack versions. Bound caches and clear/switch them when settings change. Model loading and inference must not block the Qt GUI thread.

Lookup order:

1. Get the full target token, its context and any explicit selected phrase.
2. Retrieve literal and normalized headword matches plus Stanza lemma matches.
3. Apply verb-stem aliases with POS evidence; preserve real lexical headwords.
4. Prefer whole-token/phrase matches with compatible POS. Keep a useful literal alternative when ambiguity remains; do not fabricate confidence percentages.
5. Retrieve TDK senses and optional English entries, keeping source sections separate.

For a selected multiword string, try the whole dictionary phrase first. If absent, show the sentence with clickable tokens. For ordinary token lookup, also try a bounded local phrase window (up to five tokens containing the target), using surface forms and the analyzed verb lemma to reach entries such as `fark etmek` from `fark etti`. Do not enumerate arbitrary lemma combinations or claim exhaustive idiom handling.

Represent one input request with text, optional target span, source (`ocr`, `selection`, `clipboard`), display mode and a monotonically increasing request ID. Keep activation ID for hold visibility. Newer input invalidates stale result delivery; background OCR must not replace a pinned text lookup. This extends current generation checks rather than creating a second independent pipeline.

## 6. System-wide text input

Yes: text lookup can operate across desktop apps without browser integration, provided the source app exposes copyable text. It cannot retrieve a selection from every game, canvas or protected window. OCR remains the route for those surfaces.

### Explicit clipboard lookup

Add a configurable global action, suggested default `Ctrl+Alt+L`, which reads current clipboard text and opens a persistent lookup. Read Unicode plain text through `QClipboard` on the Qt thread. This is the first text-input implementation because it is simple and dependable on Windows.

### Automatic clipboard lookup

Add **Look up copied text automatically**, off by default, with a visible tray toggle. Observe `QClipboard.dataChanged` on Windows. A short copied word opens its entry; a sentence opens a token-selectable context strip. Do not infer a target from the current mouse position when the copied text supplies no target span.

Coalesce duplicate clipboard events, ignore non-text/empty content and app-owned copy events, and skip large payloads (initial limit: 2,000 characters). Explicit lookup of an oversized selection can show a concise size message; automatic monitoring should stay quiet. Enabling monitoring must not immediately process pre-existing clipboard content. Do not write copied text into logs or keep clipboard history. Duplicate suppression must not prevent an explicit shortcut from looking up the same word again.

### Selected text + shortcut

Suggested configurable default: `Ctrl+Alt+D`. On Windows, wait until the trigger modifiers are released, keep the source window focused, send one Copy command, then wait asynchronously for a fresh clipboard sequence/change with a bounded timeout. Do not clear the clipboard or insert a sentinel. Copying the same text is valid if a fresh clipboard sequence confirms it; unchanged sequence on timeout must not look up stale text.

Coordinate this capture with clipboard monitoring so one action produces one popup. Ignore injected events in activation dispatch. Abort if the foreground source window changes during capture. Do not release keys the user is physically holding, steal focus before Copy completes, or request elevation to control elevated apps.

For simplicity, the selected-text shortcut leaves the copied selection on the clipboard, just as manual Copy would. No automatic clipboard restoration: it can overwrite a newer user copy and fails to preserve some rich clipboard formats. Explain this briefly in the setting help text. If the app does not support Copy, show a small failure message suggesting OCR or manual copy. Do not silently capture the screen instead.

Shortcuts must be configurable and checked for collisions with existing activation bindings. Text actions should suppress overlapping OCR activation for that action rather than starting both pipelines. Selection-only actions must not be bound to bare Shift. Do not globally intercept ordinary Ctrl+C.

Windows is the acceptance target. macOS uses Cmd+C and permission-dependent input, but Qt background clipboard notifications have platform caveats; do not advertise parity before testing. X11 offers a separate primary selection; Wayland global input/capture depends on the compositor. Keep platform-specific capture in a small module and expose supported actions only. No accessibility/UI Automation framework in the first iteration.

## 7. Popup contents and interaction

Use one result presentation with two lifetimes:

- **Peek:** OCR hold-to-show keeps the existing behavior. Show a compact first result, short source-specific definition preview, and at most one example. Releasing hides it.
- **Persistent:** clipboard/selection actions remain open until dismissed or replaced by a newer explicit lookup. A configurable pin action during OCR peek enters this mode. The popup stays at its opening position instead of following the pointer, supports scrolling and text selection, and is not hidden when the lookup shortcut is released.

Persistent mode opens without taking focus from the source app. Clicking it allows interaction. Provide a close button; Escape dismisses when focused, and the explicit lookup action can reopen/replace it. Do not swallow Escape globally. A new deliberate OCR activation may replace it, but background scans and mouse movement may not.

The current `QLabel` rendering and hold visibility logic need a targeted change. Use a read-only `QTextBrowser` (or equivalent existing Qt rich-text widget) for persistent content, internal entry links and scrolling. No embedded web browser or frontend framework. Keep navigation internal and avoid moving the popup while the user interacts. The current popup holds `screen_lock` while visible; persistent mode must not retain that lock indefinitely or freeze background capture. Audit and narrow that lock's lifetime as part of this change.

Default Turkish display:

```text
kitap                         noun
kitaplarımdan → kitap

TDK · Türkçe
1. [definition]
   [example sentence] — [author, when present]
2. [next sense]

Wiktionary · English           [only when installed/enabled]
1. [English gloss]

Related expressions           [collapsed when present]
```

- Show canonical headword, and original surface only when different.
- Show POS and useful usage/domain labels (figurative, colloquial, etc.) near their senses.
- Preserve source sense ordering. Default to the first three senses and one example per visible sense, with **Show more** in persistent mode. Keep this fixed initially rather than exposing many numeric settings.
- Examples are optional per the existing examples preference; no invented examples or translations.
- Keep TDK and English sections separate. Their sense numbers are not aligned, and an English gloss must not masquerade as a translation of the adjacent TDK sentence.
- Offer a simple definition-language preference: Turkish, English, or Both; Both keeps TDK first. If the requested English entry is absent, allow an explicit Turkish fallback and indicate it rather than hiding a valid TDK result.
- Related idioms/compounds are clickable where resolvable. Origin/pronunciation metadata can live behind details; no kanji, kana readings or Japanese frequency badges on Turkish entries.
- Route Turkish entries to the Turkish audio pack, never to the Japanese pronunciation database. Show a speaker action where a recording is available; optional autoplay retains the user's preference.
- For copied sentences, show the source sentence above results with clickable original token spans. A single selected word has no surrounding sentence context; the UI and implementation must not pretend otherwise.

## 8. Offline word audio

### What exists and what still needs verification

The inspected `ogun/guncel-turkce-sozluk` repository tree has no WAV/MP3 collection, and its v12 SQLite schema has no audio BLOB or sound-code table. The `telaffuz` field is pronunciation text, not recorded sound. The text dictionary download alone therefore does not supply offline playback.

TDK supplies recordings separately. The inspected current `clydeofficial/tdk-sozluk` client reads `seskod` from the current dictionary response and constructs `https://api.sozluk.gov.tr/ses/<code>.wav`. Older clients use `sozluk.gov.tr` and spelling-service `seskodu` fields. These are implementation clues, not a verified stable API contract. On 2026-09-06, direct requests to both the old host and `api.sozluk.gov.tr` closed the connection without a response from this environment. No live WAV or overall recording coverage was verified.

Before bulk acquisition, verify the official website's current requests for a handful of actual words, download their recordings and confirm the bytes decode and pronounce the expected headwords. Do not assume `madde_id` is a sound code, guess numeric WAV filenames, or assume every dictionary entry has a recording. If access remains unavailable, keep audio optional and support importing a separately acquired verified recording manifest/folder. Text lookup can still ship; do not claim the audio pack is complete.

### Reuse the existing audio database contract

Yes, a Turkish counterpart to `android.db` can be built. That filename is not an Android-specific runtime requirement: our `audio/repository.py` reads ordinary SQLite tables. Preserve the schema it already expects:

```sql
CREATE TABLE entries (
  id INTEGER PRIMARY KEY,
  expression TEXT NOT NULL,
  reading TEXT,
  source TEXT NOT NULL,
  speaker TEXT,
  display TEXT,
  file TEXT NOT NULL
);
CREATE TABLE android (
  id INTEGER PRIMARY KEY,
  file TEXT NOT NULL,
  source TEXT NOT NULL,
  data BLOB NOT NULL
);
CREATE INDEX entries_expression_reading ON entries(expression, reading);
CREATE UNIQUE INDEX android_file_source ON android(file, source);
```

Use canonical dictionary headwords for `expression`, empty `reading`, `tdk` for source, and the actual sound-code filename for `file`. Deduplicate recordings by sound code/checksum so several entry mappings can share one BLOB. Preserve multiple pronunciations when metadata distinguishes them; do not assign a pronunciation to a particular homograph sense without evidence. Store retrieval/source/checksum/mapping details in a build manifest or small additional metadata table, not in the UI.

Runtime code already handles empty readings and WAV filenames and streams BLOB bytes through QBuffer/QMediaPlayer. Reuse that reader and worker. Adjust language-specific database selection and playback request handling rather than adding a Local Audio Server dependency. The pack can be named `tdk-audio.sqlite3`; compatibility is the table contract, not the basename. This promises compatibility with Meikipop's reader, not every external tool that calls its file `android.db`.

### Acquisition, storage and distribution

Add a separate build-time command such as `meikipop build-turkish-audio --output <directory>`. Read distinct headwords from the pinned TDK dictionary, resolve confirmed word-to-sound mappings, and fetch each unique recording once. Save progress after each batch so interrupted builds resume. Use low bounded concurrency, timeouts and backoff; record missing recordings separately from transient request failures. Do not retry the entire dictionary on every run or make network requests while hovering.

Keep original WAV bytes for the first working pack. Verify container headers, nonempty duration and successful decoding; an HTTP 200 HTML error page is not audio. Measure actual pack size after a small acquisition sample. If size warrants compression, convert once during the build into a broadly supported format and confirm QMediaPlayer playback in the packaged Windows app before adopting it. No speculative size/coverage promise and no automatic TTS substitution for TDK recordings.

Publish `tr-tdk-audio` as a separate versioned optional release asset, with checksums, count of playable files, covered headwords, missing mappings and build/source identity. If the real size exceeds release asset limits, split the download archive into bounded parts and reconstruct/verify one database on installation; do not add sharding until necessary. Store it under `languages/tr/audio/<version>/tdk-audio.sqlite3`. Japanese audio remains at its own configured location.

Dictionary and audio packs update independently. A text-pack update does not force redownloading existing audio. When building an audio update, reuse cached recordings and fetch new/changed mappings; manual refresh can revalidate existing URLs. Record known snapshot mismatches rather than claiming newer online audio metadata perfectly matches the 2024 dictionary.

### Playback and acceptance

- Persistent popup: speaker action beside the canonical headword, replayable on demand even when autoplay is disabled. No recording means no misleading enabled speaker. Distinguish “audio pack not installed” from “no recording for this word” in settings/help.
- Peek: optional existing autoplay; a pin/replay action can reuse the same clip. No detailed suffix or sentence audio is implied.
- An inflected lookup plays the selected dictionary lemma, e.g. `kitaplarımdan` plays `kitap`; the speaker belongs beside that lemma. Do not imply it is a recording of the inflected surface.
- Extend current playback checks: `audio/playback.py` currently requires a held active activation and autoplay enabled. Manual replay and persistent text lookup need explicit playback intent plus current request ID; obsolete lookup results must not play. Do not bypass the checks globally or make clipboard audio depend on holding an OCR key.
- Keep existing output-device, volume, worker and buffer lifecycle behavior. Cancel queued stale audio on language/word changes. Missing/corrupt audio never blocks definitions.
- Add small schema/mapping tests and manually verify a few real recorded words, replay with autoplay off, switching Japanese/Turkish, rapid result replacement, and playback after disabling the network. These are functional checks, not an analyzer or pronunciation benchmark.

## 9. OCR integration

Implement text lookup before spending effort on OCR. Then adapt existing multilingual providers for Turkish:

- First route: existing Google Lens provider, with Japanese-only line filtering removed for Turkish and word separators preserved. This reuses the app's current remote backend; no new cloud API setup.
- Preserve spaces and line boundaries; store reliable offsets from each recognized word into paragraph text.
- Turkish hover selects the entire recognized token, wherever the cursor lands within it. Preserve a complete line of context for Stanza. Do not use Japanese prefix scanning or the current 25-character truncation for Turkish words.
- Keep proper-name apostrophe forms together. Bypass Japanese-only furigana assumptions for Turkish.
- Language/provider settings must not leave Turkish pointed silently at the Japanese MeikiOCR model. Explain/select a compatible provider when enabling Turkish.
- A dedicated local PaddleOCR Latin provider is a later optional step, not a prerequisite for trying Stanza + TDK. This is functional scope control, not an OCR benchmark.

Make screen-region selection and OCR initialization lazy enough that clipboard-only use does not prompt for a scan region or download Japanese OCR models/dictionaries. Existing Japanese installations retain their normal setup path.

## 10. Implementation sequence and likely files

1. **TDK importer and store.** Add `scripts/build_turkish_dictionary.py`, `dictionary/turkish_store.py`, source lock and tiny fixtures. Extend CLI/path handling. Produce and query one local pack before UI changes.
2. **Stanza route.** Add `language/analyzer.py` and `language/stanza_analyzer.py`, exact fallback, optional dependencies/model setup, structured token/lookup result data. Adapt `dictionary/lookup.py` and `pipeline.py` without rewriting Japanese deconjugation.
3. **Clipboard lookup and persistent popup.** Add `gui/text_input.py`; modify `gui/input.py`, `gui/popup.py`, `main.py`, settings and tray. Implement explicit clipboard first, automatic clipboard second, then Windows selection capture. Resolve focus, lock lifetime and stale-result behavior here.
4. **Turkish OCR.** Update `ocr/interface.py`, `ocr/hit_scan.py`, provider filtering/separators and postprocessing; preserve original token offsets and lazy startup.
5. **Optional English pack.** Add a Kaikki importer using its recommended raw English-Wiktionary extraction filtered to Turkish. Keep glosses, POS, sense labels and available examples; preserve form-of links rather than treating them as independent definitions. Use a locked snapshot and the same schema. No mixing Turkish-Wiktionary Turkish glosses into the English source accidentally.
6. **Offline audio.** Verify live sound mappings/recordings, add a resumable audio builder, produce the optional compatible database, and adapt `audio/playback.py`, audio settings and popup speaker actions. Reuse `audio/repository.py` and `audio/worker.py`. Audio acquisition remains independent of the text pack.
7. **Packaging and documentation.** Add a separate Turkish dictionary workflow and Turkish-enabled Windows build, download/update UI, README instructions and manual checks. Leave generated artifacts outside Git.

Milestone: TDK + Stanza + explicit clipboard + persistent examples popup is the first version to try. Automatic copy lookup, selection shortcut and OCR follow in the same branch. Optional English data can ship after that without blocking Turkish definitions.

## 11. Verification without a benchmark project

Run the existing test suite with the repository's supported runner (`python -m unittest discover -s tests` after checking existing test conventions). Add focused tests only for behavior that could otherwise regress:

- Import preserves multiple senses, labels, authors, homographs, phrase relations and verb aliases; Turkish dotted/dotless I stays distinct.
- Missing-model status permits exact lookup; Stanza results map to original source spans and stale requests cannot replace newer content.
- Clipboard deduplication/self-copy suppression, selection-copy timeout, and release of input modifiers cannot trigger duplicate or stale lookup.
- Persistent visibility survives shortcut release, does not retain the screen lock, and background OCR cannot overwrite it. Existing Japanese hold and audio tests pass.
- Interrupted/bad pack installation retains the working pack; opening a new pack invalidates dictionary caches.

Use a tiny hand-inspected dictionary fixture for unit tests and manual actual-model smoke checks, not a checked-in full TDK copy or network-dependent test suite. Manually try `kitaplarımdan`, `gözlükçüler`, an inflected verb, `Ankara'ya`, and `fark etti` in context. These are smoke cases, not statistical accuracy claims.

Manual Windows acceptance:

1. Select/copy in Notepad, a browser and a PDF reader with selectable text; explicit lookup shows the expected lemma and TDK definitions.
2. Turn on automatic clipboard lookup; one copy produces one persistent popup, including sentence token selection. Turn it off and verify normal copying no longer opens popups.
3. Use selection shortcut with existing clipboard text and with no selection; no stale clipboard result appears on failure, and focus stays in the source app until interaction with the popup.
4. Read/scroll examples and switch tokens without the popup following the pointer or disappearing on key release.
5. Try a Turkish OCR line using Lens and a Japanese OCR line using the existing Japanese setup.
6. Restart offline after setup; text analysis and definitions work without downloads. Test absent/corrupt model and failed dictionary update separately.
7. Run the packaged Turkish-enabled app on Windows without Python installed. Clipboard-only mode starts without OCR setup.

No throughput study, analyzer tournament, corpus collection, model training or performance dashboard is required to accept this iteration.

## References and inspected evidence

- [TDK source repository](https://github.com/ogun/guncel-turkce-sozluk)
- [v12 database history](https://github.com/ogun/guncel-turkce-sozluk/commits/master/sozluk/v12/v12.gts.sqlite3.db)
- [Autocomplete-only update workflow](https://github.com/ogun/guncel-turkce-sozluk/blob/master/.github/workflows/download-autocomplete-json.yml)
- [Stanza releases](https://github.com/stanfordnlp/stanza/releases) and [1.14 model resource manifest](https://raw.githubusercontent.com/stanfordnlp/stanza-resources/main/resources_1.14.0.json)
- [Kaikki Turkish overview](https://kaikki.org/dictionary/Turkish/index.html) and [recommended raw downloads](https://kaikki.org/dictionary/rawdata.html)
- [Qt clipboard behavior and platform notes](https://doc.qt.io/qt-6/qclipboard.html)
- [Windows SendInput behavior and integrity restrictions](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [TDK client sound mapping](https://github.com/clydeofficial/tdk-sozluk/blob/main/src/features/ses.js), [sound URL construction](https://github.com/clydeofficial/tdk-sozluk/blob/main/src/utils/normalize.js), and [service hosts](https://github.com/clydeofficial/tdk-sozluk/blob/main/src/core/constants.js). Client code was inspected; live service access was not confirmed.

Local evidence: `dictionary/customdict.py` and `lookup.py` use Japanese pickle data and runtime deconjugation; `ocr/hit_scan.py` returns a substring from the cursor; providers currently discard Japanese-free lines or separators; `gui/input.py` and `pipeline.py` already carry activation generations; `gui/popup.py` ties visibility and a screen lock to activation; `main.py` initializes OCR/capture eagerly. These are the integration points this plan addresses.
