# Turkish support: Stanza, TDK, and desktop text lookup

Status: source-environment desktop implementation, with Meikipop UI restoration, Settings installer repairs and hover-cache corrections after reader feedback. The earlier MVP completion claim did not establish UI acceptance. Updated: 2026-09-06. See [Turkish setup and verification](TURKISH_SETUP.md) for installation and launch commands.
Branch: `feature/turkish-support`.
Base: `feature/native-input-audio` at `666b479`.
Worktree: `../meikipop-turkish` beside the existing checkout.

## 1. Product scope and decisions

Build a useful Turkish reading tool with accurate lemma lookup, Turkish definitions from TDK, examples, WordNet synonyms and semantic relationships, and optional English definitions from Wiktionary. Keep Stanza as the analyzer and improve recovery from actual reading failures. The existing small analyzer interface permits a second analyzer later without changing input, dictionary storage, or UI.

The first supported target for the new desktop interactions is Windows. Keep Japanese working. Do not expand this project into a generic NLP platform, dictionary marketplace, or browser extension.

Decisions:

- Default Turkish analyzer: Stanza 1.14.0 with resources 1.14.0, IMST tokenization/MWT, and `imst_charlm` for both POS and lemmatization. Both processors now use CharLM; setup and runtime share the configuration, which is included in analyzer identity. No parser, NER, BERT, or model training.
- Main dictionary: `ogun/guncel-turkce-sozluk`, v12 SQLite snapshot.
- Semantic data: add StarlangSoftware TurkishWordNet-Py / KeNet as a separate offline pack for synonyms and related concepts. This is committed scope, not a replacement for TDK or morphology.
- Runtime dictionary: a compact, indexed SQLite database prepared by our importer. No Turkish pickle, MongoDB server, custom binary format, or enumeration of inflected forms.
- English: optional separate pack made from Kaikki's English-Wiktionary Turkish entries, after the TDK flow works.
- Audio: optional offline TDK recording pack using the existing `android.db` reader schema; validate live recording access before building the full pack.
- Input: local PaddleOCR 3.7.0, explicit clipboard lookup and automatic copy-to-pin enabled by default per the MVP request. A separate selection-capture shortcut remains future work; ordinary Ctrl+C already handles copyable selections.
- UI: preserve Meikipop's Japanese interaction conventions and use Hiku as a content/navigation reference. Turkish gets compact definitions, progressive disclosure, and explicit phrase/correction provenance.
- Recovery: Turkish-aware casing retry, dictionary-validated morphology, and bounded diacritic/edit suggestions. Preserve source text and distinguish suggestions from analyzed base forms.
- No analyzer tournament, automatic translation of TDK definitions, or full suffix explanations. Focused before/after checks on real failures remain necessary.

### Implemented and verified

- KeNet source locked to 718fd441262602db6ea1ac9e2dcf3a5142bda06d: indexed offline SQLite store with distinct synsets, member sense/group IDs, typed relations and attribution. Full import: 78,327 synsets, 110,259 members, 213,403 edges, zero missing targets. Focused fixture checks Turkish casing, ambiguous senses, navigation data, missing targets and failed-build preservation.

- Locked TDK importer, read-only SQLite store, Turkish-aware keys, POS-gated verb aliases, ordered senses/examples, and related expressions. The local pack has 99,209 visible entries; source anomalies are recorded by the build.
- Lazy Stanza/exact analyzers, explicit offline model setup, bounded context caching, and original parent-token spans for MWT expansions. The adapter currently retains only the first expanded word's lemma/POS.
- `build-turkish-dict`, `setup-turkish-model`, `lookup-turkish`, and `turkish-clipboard` commands; pinned Turkish dependency extra.
- Standalone clipboard window with Ctrl+Alt+L, clickable tokens, three-sense preview, optional examples, related-entry navigation, background lookup, and stale-request rejection. It starts without Japanese OCR setup.
- Local phrase lookup over up to five tokens. For `Bunu hemen fark etti.`, Stanza supplies `et`; the dictionary alias reaches `etmek`, and our phrase search finds `fark etmek`.
- Current verification: 49 passing unit tests and fourteen actual-model offline smoke cases, including the three casings of `benzerliği` and standalone `hayırdır`. Unit checks cover shared setup/runtime CharLM configuration, phrase provenance, casing retry alignment after Unicode composition, dictionary validation, caching, preserving existing hits, and UTF-8 CLI output with a redirected Windows stream. These do not cover unimplemented desktop integration.

### Findings from reader feedback

- `benzerliği` and `Benzerliği` produce `benzerlik` and a TDK match. With the current no-CharLM lemma model, `BENZERLİĞİ` produces the incorrect `bengerlik` and no match. Dictionary normalization correctly produces `benzerliği`; this reproduced failure is in analysis, not dictionary key casing.
- Standalone `hayırdır` produces `hayır` with the full `[0:8]` span and TDK matches. Ten varied sentences also preserved its full source span, including uppercase, punctuation, newline, and MWT cases. The reported missing final `r` remains unreproduced; retain the report and revisit when the exact failing input is available, without blocking other work.
- Phrase results now retain the original span, lookup candidate, route, and source-qualified entry ID. The clipboard entry header displays `fark etti → fark etmek` when either phrase token is selected.
- Hiku's Turkish adapter already retries ASCII diacritic variants through TRmorph and records edit costs. Reuse the approach, not its current generate-all-then-truncate implementation: candidate generation itself must be bounded.

MVP delivered: independent KeNet groups and linked semantic navigation; automatic clipboard lookup; pointer-anchored Peek/Pinned UI with global Escape; local PaddleOCR 3.7.0 / PP-OCRv6 small; persistent settings and explicit background setup; console-free source launcher. The Turkish worker serializes OCR/analysis/lookup, preserving request-generation rejection without changing Japanese workers or holding their screen lock.

Still pending: selection-copy injection, optional English/audio packs, versioned release/update installation and clean-machine Windows packaging. Do not describe these as completed. Japanese and Turkish now share popup frame/placement helpers and recognition caching; their language workers remain distinct.

### Desktop correction and reuse audit

- Reader requirement: preserve Meikipop UX/UI and add clipboard and fixed/pinned lookup. The separate toolbar/search-panel design did not satisfy this. Turkish now starts in the tray, uses the original frame, configured typography/colors/opacity and placement rules, and sizes the definition surface to its content. Search/setup are menu actions; WordNet is expandable. Pinning freezes position and blocks background replacement.
- Existing components reused: `LatestValueQueue`; the original popup styling and all four placement modes, extracted into `gui/popup_style.py`; `REUSE_LAST_VALUE` for pointer-only hits while a preview is visible; and unchanged Turkish sentence-analysis caches. Both OCR paths use `ocr/scan_cache.py` to reuse recognition on unchanged pixels. Turkish keeps a stable local capture region and prepares hidden results on the original auto-scan interval instead of rerunning recognition for each pointer movement.
- Necessary adapters: TDK/KeNet rendering, Stanza analysis and Paddle word-box offsets remain Turkish-specific. The existing MeikiOCR provider is Japanese-specific; the existing provider discovery eagerly imports providers and permits remote fallback. Turkish keeps explicit local model setup and offline inference. The shared Japanese `HitScanner` returns a character suffix for Japanese deconjugation, so it cannot directly replace Turkish whole-line/token-span lookup.
- Settings failures reproduced: Stanza progress output fails when `pythonw` supplies no stderr; replacing an open TDK database fails on Windows. Installers now run in a hidden process with output pipes after stopping the lookup worker, then restart lookup with fresh handles/caches. The real console-free TDK and Stanza install-and-lookup checks passed. Installation errors remain visible in Settings.
- The reuse audit also found a regression in the existing region selector: it called the now-instance `InputLoop.get_mouse_pos` as a static method. It now reads physical coordinates from its own mouse controller; a focused selection test covers this Japanese capture path.
- Verification: 66 focused unit checks; fourteen offline Stanza cases; offline Paddle recognition and cached-hit smoke. The fixed OCR fixture measured approximately 113 ms recognition and 0.01 ms cached word hit, excluding capture/rendering. A controlled Windows fixture with real capture/models measured 177 ms prepared activation and 8 ms for the next word; popup rendering and pinned-position checks passed. Cold initialization and changed images still cost inference time; these timings are not a universal latency claim. Broader browser/PDF, mixed-DPI hardware and packaged-release acceptance remain outstanding.

## 2. Git organization and maintenance

Feedback follow-up (2026-09-07): prioritize the independently reviewable Japanese clipboard addition on `feature/japanese-clipboard`, based on `feature/native-input-audio`. Keep one repository with separate desktop entry points and language adapters. Japanese retains its original renderer, dictionary/deconjugation, tray and settings. Turkish UI lives in `gui/turkish/`, with separate rendering and worker modules, and its own QSettings. Both use shared frame/placement helpers, activation parsing and theme presets. No generic language framework or repository split is needed for these boundaries. The dedicated `meikipop-turkish` entry point bypasses Japanese startup. Existing minimal Turkish installation remains supported without Japanese OCR dependencies. Separate packaged builds remain acceptance work.

Next order: restore Turkish controls and compact content, add typed-search shortcut, repair dismissal and optional selection capture, then reproduce lookup/OCR failures and improve conservative sense ordering. Optional English and audio packs follow reading-flow acceptance. This supersedes the earlier milestone ordering below.

Use the new worktree for the plan and subsequent implementation. The original checkout stays on `feature/native-input-audio`. Branching from its current HEAD deliberately includes native input and audio fixes; branching directly from upstream would lose them.

Keep this one feature branch for the first usable version. Make reviewable commits by implementation step below; do not create permanent per-language branches. After acceptance, merge into the fork's maintained development branch. If opening a PR before the input branch is merged, use `feature/native-input-audio` as the base so its commits do not obscure the Turkish diff; retarget when appropriate.

For future upstream maintenance, fetch `upstream` and integrate tested upstream changes into the fork's maintained branch, then into this feature branch as needed. Do not rewrite shared branch history or mechanically rebase a released build. Japanese fixes and shared input/UI improvements should remain understandable independently of Turkish data.

Track implementation, source locks, small regression fixtures, this maintained plan, and the reusable setup guide. Keep downloaded dictionaries, model weights, databases, generated packs, virtual environments, and local feedback out of Git. The slim root `AGENTS.md` records shared development conventions. Keep implementation status here and reproducible installation/usage instructions in `TURKISH_SETUP.md`; do not retain a separate PoC status report. No submodules or Git LFS needed. Do not push or publish as part of this work.

## 3. Source data and what precompilation means

The inspected v12 SQLite artifact contains 99,236 entry rows, 98,159 distinct headword strings, 133,037 sense rows, 45,392 example rows, and 16,666 rows in the idiom/proverb table. These counts overlap. Twenty-five entry rows have no associated sense rows. Treat these as properties of the inspected snapshot, not permanent expected totals.

The artifact is about 29 MB. Its file history last changed on 2024-03-29. The repository's scheduled job updates autocomplete data, not the full definitions database. Check the actual dictionary artifact when deciding whether to update; recent repository activity alone is misleading.

The existing `src/meikipop/resources/turkish/sources.json` pins the TDK source. Keep source revision, artifact path/checksum, and importer/schema identities with each build. Add separate locks for WordNet and optional Wiktionary. Preserve attribution as pack metadata.

Implemented command:

```text
meikipop build-turkish-dict --output <directory>
```

It uses the checked-in source lock by default and downloads into `paths.cache_dir`. A maintainer update command remains future work; source-lock changes are currently explicit maintenance edits. Normal application startup never scrapes TDK or fetches GitHub HEAD.

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

Local TDK/model setup exists. Release workflows, pack installation/update UI, rollback, and a Turkish-enabled executable remain to be implemented.

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

The implemented internal `Analyzer` protocol is:

```text
analyze(text) -> tokens with original start/end offsets, lemma and optional POS
identity -> engine/model version used for cache keys
```

Use Python character offsets consistently inside the application. Preserve original text and offsets when generating normalized lookup keys. Keep source tokens intact when Stanza expands a multiword token internally; do not invent separately selectable source spans for expansions.

Implement `StanzaAnalyzer` and `ExactAnalyzer`. A simple registry/config setting is enough for future analyzers; no plugin discovery, external service contract, ensemble or automatic analyzer chooser. Exact mode is a usable fallback and is labeled as such, never silently presented as Stanza results.

Stanza currently runs in the standalone clipboard worker, initialized once when needed; integration with the shared OCR pipeline is pending. Load only `tokenize,mwt,pos,lemma`, with IMST tokenize/MWT and CharLM POS/lemma. Update setup and inference configuration together, explicitly download the new lemma weights, and include processor configuration in analyzer identity. Disable inference-time downloads; missing resources show setup status and permit exact lookup.

Analyze complete OCR lines or copied sentences once and cache the token results. Cache identity includes text, language and analyzer/model identity. Dictionary result cache additionally includes enabled pack versions. Bound caches and clear/switch them when settings change. Model loading and inference must not block the Qt GUI thread.

Target lookup and recovery behavior (phrase provenance, casing retry, and initial bounded morphology/OCR suggestions are implemented):

1. Get the full target token, its context and any explicit selected phrase.
2. Retrieve literal and normalized headword matches plus Stanza lemma matches.
3. Apply verb-stem aliases with POS evidence; preserve real lexical headwords.
4. Prefer validated whole-token/phrase matches with compatible POS. Preserve literal alternatives and record each match's original source span, candidate, source, and derivation.
5. If lookup fails, retry analysis with Turkish-aware lowercase while retaining alignment to the original text. Do not globally lowercase all input or reuse offsets after a length-changing normalization without mapping them back. Check the uppercase failure again after switching lemma models.
6. If still absent, use dictionary-validated morphological candidates, then diacritic-relaxed and bounded edit-distance suggestions. A spelling-only headword index is insufficient for inflected OCR text: candidate spellings may also need analysis. Do not hard-code `benzerliği` or blindly strip suffixes.
7. Keep canonical keys diacritic-sensitive. Rank plausible OCR substitutions more cheaply than arbitrary edits; cap generated candidates, analysis retries, and returned suggestions. Preserve exact results and present recovery guesses as **Did you mean?**, never silently replacing source text.
8. Retrieve TDK definitions, WordNet semantic links, and optional English entries in distinct sections. Do not fabricate confidence percentages or imply their senses align.

Extend `lookup-turkish` with an optional analysis/debug output containing raw token text/offsets, all expanded Words, lemma/POS/features, and attempted match routes. Normal lookup remains concise and does not persist clipboard text. A separate diagnostic command is unnecessary.

For a selected multiword string, try the whole dictionary phrase first. If absent, show the sentence with clickable tokens. For ordinary token lookup, also try a bounded local phrase window (up to five tokens containing the target), using surface forms and the analyzed verb lemma to reach entries such as `fark etmek` from `fark etti`. Do not enumerate arbitrary lemma combinations or claim exhaustive idiom handling.

Represent one input request with text, optional target span, source (`ocr`, `selection`, `clipboard`), display mode and a monotonically increasing request ID. Keep activation ID for hold visibility. Newer input invalidates stale result delivery; background OCR must not replace a pinned text lookup. This extends current generation checks rather than creating a second independent pipeline.

## 6. System-wide text input

Yes: text lookup can operate across desktop apps without browser integration, provided the source app exposes copyable text. It cannot retrieve a selection from every game, canvas or protected window. OCR remains the route for those surfaces.

### Explicit clipboard lookup

Add a configurable global action, suggested default `Ctrl+Alt+L`, which reads current clipboard text and opens a persistent lookup. Read Unicode plain text through `QClipboard` on the Qt thread. This is the first text-input implementation because it is simple and dependable on Windows.

### Automatic clipboard lookup

Implemented **Look up copied text automatically**, on by default for the requested MVP, with visible tray and Settings toggles. Observe `QClipboard.dataChanged` on Windows. A short copied word opens its entry; a sentence opens a token-selectable context strip. The pointer anchors the popup, not the selected token within copied text.

Coalesce duplicate clipboard events, ignore non-text/empty content and app-owned copy events, and skip large payloads (initial limit: 2,000 characters). Explicit lookup of an oversized selection can show a concise size message; automatic monitoring should stay quiet. Enabling monitoring must not immediately process pre-existing clipboard content. Do not write copied text into logs or keep clipboard history. Duplicate suppression must not prevent an explicit shortcut from looking up the same word again.

### Selected text + shortcut

Suggested configurable default: `Ctrl+Alt+D`. On Windows, wait until the trigger modifiers are released, keep the source window focused, send one Copy command, then wait asynchronously for a fresh clipboard sequence/change with a bounded timeout. Do not clear the clipboard or insert a sentinel. Copying the same text is valid if a fresh clipboard sequence confirms it; unchanged sequence on timeout must not look up stale text.

Coordinate this capture with clipboard monitoring so one action produces one popup. Ignore injected events in activation dispatch. Abort if the foreground source window changes during capture. Do not release keys the user is physically holding, steal focus before Copy completes, or request elevation to control elevated apps.

For simplicity, the selected-text shortcut leaves the copied selection on the clipboard, just as manual Copy would. No automatic clipboard restoration: it can overwrite a newer user copy and fails to preserve some rich clipboard formats. Explain this briefly in the setting help text. If the app does not support Copy, show a small failure message suggesting OCR or manual copy. Do not silently capture the screen instead.

Shortcuts must be configurable and checked for collisions with existing activation bindings. Text actions should suppress overlapping OCR activation for that action rather than starting both pipelines. Selection-only actions must not be bound to bare Shift. Do not globally intercept ordinary Ctrl+C.

Windows is the acceptance target. macOS uses Cmd+C and permission-dependent input, but Qt background clipboard notifications have platform caveats; do not advertise parity before testing. X11 offers a separate primary selection; Wayland global input/capture depends on the compositor. Keep platform-specific capture in a small module and expose supported actions only. No accessibility/UI Automation framework in the first iteration.

## 7. Popup contents and interaction

Keep Meikipop's positioning, dismissal, pin/audio conventions, typography, and shortcuts as the foundation. The corrected Turkish `QTextBrowser` content pane uses shared popup frame/placement helpers; language-specific workers remain separate. Hiku is only a content/navigation reference, not a replacement application shell. Result provenance must be preserved in phrase and correction presentation.

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
- For phrase matches show the actual phrase, e.g. `fark etti → fark etmek`, and highlight its original span. For uncertain recovery show clickable **Did you mean?** choices separately from analyzed base forms.
- Keep model/version status and full morphology out of the normal reading hierarchy; setup status belongs in a compact status area and detailed analysis in an optional diagnostic view.
- Show POS and useful usage/domain labels (figurative, colloquial, etc.) near their senses.
- Preserve source sense ordering. Default to the first three senses and one example per visible sense, with **Show more** in persistent mode. Keep this fixed initially rather than exposing many numeric settings.
- Examples are optional per the existing examples preference; no invented examples or translations.
- Keep TDK and English sections separate. Their sense numbers are not aligned, and an English gloss must not masquerade as a translation of the adjacent TDK sentence.
- Offer a simple definition-language preference: Turkish, English, or Both; Both keeps TDK first. If the requested English entry is absent, allow an explicit Turkish fallback and indicate it rather than hiding a valid TDK result.
- Related idioms/compounds are clickable where resolvable. Origin/pronunciation metadata can live behind details; no kanji, kana readings or Japanese frequency badges on Turkish entries.
- Add a collapsed **WordNet · Synonyms / Related concepts** section with sense-grouped synonyms and named relations. Keep it distinct from TDK compounds/idioms; ambiguous headword matches must not silently attach to a particular TDK sense.
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

The local-first requirement supersedes the earlier Lens-first proposal. Turkish uses **PaddleOCR 3.7.0**, PaddleX 3.7.2 and PaddlePaddle 3.3.1 on CPU, with **PP-OCRv6 small** detection/recognition. These were the current PyPI releases checked on 2026-09-06. Japanese providers remain unchanged. There is no cloud fallback for Turkish screenshots.

`setup-turkish-ocr` explicitly downloads the two models, stages them under the Turkish data directory, records file checksums, and activates a complete model directory. Runtime verifies local files before lazily importing PaddleOCR, disables host connectivity probing, passes both local model paths, and disables orientation/unwarping models. Failed setup retains the previous directory. Model setup uses PaddleX's official downloader; the installed manifest records the downloaded bytes rather than claiming an immutable upstream weight revision.

The popup captures a bounded region around the pointer on its own monitor. Qt screen coordinates are converted to screenshot pixels using the actual captured dimensions. Paddle's `text_word_boxes` map a hit to an offset in the full recognized line, then the existing Turkish analyzer chooses the token. No character-width estimates or Japanese-only text filtering. Screen images remain in memory.

Verification: the real PP-OCRv6 small models recognize `Bugün çocuklar kitap okuyor.` with Turkish glyphs intact and select `kitap` at offset 15; the smoke blocks socket connections throughout model initialization and inference. Focused fixtures cover repeated words, box misses and missing-model failure before imports/downloads. Desktop capture and popup acceptance are recorded below separately.

## 10. Implementation sequence and likely files

Completed milestone: TDK pack + Stanza + explicit clipboard + standalone persistent definitions/examples window. Continue in this order:

1. **Development conventions and lemma upgrade — complete.** Added the slim `AGENTS.md`, switched lemma to `imst_charlm`, updated analyzer identity, and installed the new weights locally. Offline checks preserve the six original smoke cases. CharLM alone still mislemmatizes `BENZERLİĞİ` as `benüzlik`; lowercase/title case resolve to `benzerlik`, and `hayırdır` retains `[0:8]`. Keep the no-CharLM findings above as the baseline.
2. **Lookup recovery and provenance — initial implementation complete.** Results now include original phrase spans, candidates, routes, and source-qualified entry IDs. Failed token lookup retries Turkish-aware lowercase context once, maps normalized boundaries back to the original text, and accepts only an aligned dictionary match. Original analysis stays intact; the clipboard header labels casing recovery. `BENZERLİĞİ` now reaches `benzerlik`. `lookup-turkish --debug` now includes raw expanded Words and dictionary query attempts. Failed lookups offer bounded dictionary-validated nominal, diacritic, and spelling suggestions; corrected spellings can also be analyzed in context. See limits below. The ten-sentence span investigation is complete; revisit only with new evidence.
3. **WordNet pack and lookup — complete for MVP.** Locked KeNet importer/store and explicit setup command; sense-grouped definitions, synonyms and typed semantic links in the popup. Missing/corrupt optional WordNet does not break TDK. WordNet-only members remain navigable. Groups remain separate from TDK senses; POS ranking is future refinement.
4. **UI refinement — corrected after reader feedback; broader acceptance remains.** Preserve the original Meikipop reading surface using shared frame/placement helpers. Keep copy-to-pin, Peek/Pinned state, global Escape, bounded Back navigation, menu-based search/settings and a tray-first source launcher. Background OCR preparation and unchanged-image reuse restore the original separation between recognition and pointer lookup. Selection injection remains deferred.
5. **Turkish OCR — complete for MVP.** Current local PaddleOCR API and PP-OCRv6 small models, explicit staged setup, checksummed local runtime paths, real word-box-to-source offsets, bounded capture region and background inference. No Turkish cloud fallback. Existing recovery runs on full OCR-line context.
6. **Optional English pack.** Add a locked Kaikki importer using raw English-Wiktionary entries filtered to Turkish. Preserve glosses, POS, labels, examples, and form-of links; do not align its sense numbers with TDK or WordNet.
7. **Offline audio.** Verify live mappings/recordings, add a resumable builder, and adapt playback/settings/speaker actions using the existing audio reader and worker. Text and semantic lookup remain usable without audio.
8. **Distribution and acceptance.** Add separate dictionary workflows, a Turkish-enabled Windows build, and download/update UI. Run clean-machine/manual checks. Keep setup guidance in `TURKISH_SETUP.md`; edit README only when explicitly requested or required by agreed release scope.

### Recovery limits and verification

- Recovery runs only after normal lookup and casing retry fail. Guesses remain separate, clickable **Did you mean?** results; the original text and analysis are preserved. Nominal guesses are not asserted to be definitive analyses.
- The nominal validator generates a conservative single-suffix subset (plural and selected case forms, with vowel harmony and consonant softening) from candidate dictionary stems with nominal POS. It does not implement a full Turkish morphology engine or arbitrary suffix chains.
- Recovery accepts alphabetic source words of 2-32 characters. Diacritic generation emits at most 64 variants with at most three substitutions and caps queued states at 256 per generation call. At most six nominal stem proposals use the same bounded generator. Up to eight corrected contexts are reanalyzed. All queries use the existing SQLite key index; no dictionary rebuild or full-table runtime scan is needed.
- Only when those guesses find nothing, try at most 256 single-edit candidates (deletion, transposition, insertion, substitution). These cost more than diacritic substitutions. Return at most five distinct headwords. Generation order and caps deliberately limit coverage; suggestions are not exhaustive or confidence scores.
- Real offline checks cover `cocuk`, inflected `cocugu`, ambiguous `kisi`, and transposed `kitpa`, alongside the previous ten cases. Stanza splits `cocugu` into `cocug` and `u` across sentences; selectable tokens now merge analyzer splits contained within one original lexical word. Raw diagnostics preserve both original analyzer tokens and all MWT Words. The earlier `hayırdır` report remains unreproduced.
- `--debug` includes original analyzer identity, raw token text/offsets and every expanded Word's lemma/POS/features, plus dictionary candidates/routes/spans and matched IDs (including misses). Exact mode reports no raw Stanza analysis. Diagnostics go only to requested CLI output, not files or clipboard logs.

### WordNet integration

Feedback correction (2026-09-07): KeNet groups now sort by compatible analyzed POS and the queried member's own source sense number, with ID only as a stable tie-breaker. For `yırtmak`, source sense 1 (tear fabric) precedes source sense 3 (destroy). TDK keeps its source order; no cross-dictionary sense alignment or contextual probability is claimed. The locked XML stores DERIVATION_RELATED at synset level. Multi-member synsets cannot attribute those edges to one lemma, so those derivations are hidden. Single-member derivations remain under expanded Related words. Examples split on the source delimiter; previews show one example and at most four other members, with full content behind an expand arrow. Normal results omit analysis provenance, repeated lemmas and infrastructure notes; CLI diagnostics retain them.

Use [TurkishWordNet-Py / KeNet](https://github.com/starlangsoftware/TurkishWordNet-Py) as linguistic data infrastructure. Pin the selected upstream revision and actual data artifacts/checksums before implementation; record attribution and bundled license notices. The repository advertises GPL-3.0 and Meikipop already declares GPL-3.0. Inspect the chosen data files and dependencies rather than inferring their contents from repository totals.

Implemented a separate `tr-kenet` SQLite pack under `languages/tr/packs/tr-kenet/1/`, installed explicitly alongside TDK. It retains synset IDs, member spellings, sense/group identifiers, definitions/POS and typed semantic edges. Turkish-aware member keys are indexed. Import reports missing relation targets; runtime uses indexed read-only queries instead of the upstream object graph. Attribution and source identity are stored as pack metadata.

Query by the validated canonical headword, preserving all relevant synsets and their member groups. Use available POS to rank compatible groups; spelling or POS alone does not establish a TDK-sense-to-synset mapping. Show synonyms and named relations such as broader/narrower concepts or antonyms only when the chosen data supplies them. Clicking a member starts a normal lookup; if TDK has no definition, retain the labeled WordNet information rather than creating a dead link or inventing a TDK entry.

WordNet installation and refresh are independent of TDK/model versions. Missing WordNet does not break TDK lookup. Include pack identity in result-cache invalidation. Do not present WordNet as an inflection analyzer, spelling corrector, or source of automatic English translations.

Tureng remains outside the planned pack pipeline: the linked repository is a scraper/download source, while Tureng's published terms restrict extraction and redistribution. No Tureng integration is part of these milestones.

## 11. Verification without a benchmark project

Run the existing test suite with the repository's supported runner (`python -m unittest discover -s tests` after checking existing test conventions). Add focused tests only for behavior that could otherwise regress:

- Import preserves multiple senses, labels, authors, homographs, phrase relations and verb aliases; Turkish dotted/dotless I stays distinct.
- Missing-model status permits exact lookup; Stanza results map to original source spans and stale requests cannot replace newer content.
- Lemma CharLM setup and offline inference use the same pinned processor configuration. Compare actual results for `benzerliği`, `Benzerliği`, `BENZERLİĞİ`, `hayırdır`, and contextual `fark etti` against the recorded baseline.
- Casing/OCR retries preserve original spans, exact results outrank guesses, and candidate generation remains bounded even for long ambiguous ASCII strings. Include `cocuk`, inflected `cocugu`, and ambiguous `kisi`; suggestions must be labeled and dictionary-validated.
- Phrase results preserve `fark etti` as the matched span when either token is selected. Raw diagnostic output retains all MWT Words while normal UI keeps one selectable source token.
- WordNet import preserves synsets, member sense IDs, relation types, and attribution. Verify ambiguous headwords, missing relation targets, offline navigation, missing-pack behavior, and separation from TDK senses.
- Clipboard deduplication/self-copy suppression, selection-copy timeout, and release of input modifiers cannot trigger duplicate or stale lookup.
- Persistent visibility survives shortcut release, does not retain the screen lock, and background OCR cannot overwrite it. Existing Japanese hold and audio tests pass.
- Interrupted/bad pack installation retains the working pack; opening a new pack invalidates dictionary caches.

Use a tiny hand-inspected dictionary fixture for unit tests and manual actual-model smoke checks, not a checked-in full TDK copy or network-dependent test suite. Manually try `kitaplarımdan`, `gözlükçüler`, an inflected verb, `Ankara'ya`, and `fark etti` in context. These are smoke cases, not statistical accuracy claims.

Manual Windows acceptance:

1. Select/copy in Notepad, a browser and a PDF reader with selectable text; explicit lookup shows the expected lemma and TDK definitions.
2. Turn on automatic clipboard lookup; one copy produces one persistent popup, including sentence token selection. Turn it off and verify normal copying no longer opens popups.
3. Use selection shortcut with existing clipboard text and with no selection; no stale clipboard result appears on failure, and focus stays in the source app until interaction with the popup.
4. Read/scroll examples and switch tokens without the popup following the pointer or disappearing on key release.
5. Try a Turkish OCR line using local PaddleOCR and a Japanese OCR line using the existing Japanese setup.
6. Restart offline after setup; text analysis and definitions work without downloads. Test absent/corrupt model and failed dictionary update separately.
7. Run the packaged Turkish-enabled app on Windows without Python installed. Clipboard-only mode starts without OCR setup.

Keep a small permanent regression set of real reading failures and a few targeted contrasts; grow it when new bugs appear. No throughput study, analyzer tournament, large corpus collection, model training, or performance dashboard is required.

MVP verification on 2026-09-06: **58 unit tests pass**, fourteen real-model offline Stanza cases pass, and the real-model offline PaddleOCR smoke passes. Desktop checks used a separate controlled application for actual Ctrl+C/global Escape, and a visible Turkish fixture for actual global Shift, Qt screen capture, word-box selection, Stanza/TDK/KeNet delivery, click pin and release. Both passed. Rendered popup inspected with real Windows fonts. Negative-coordinate monitor clamping is covered by fixtures; actual mixed-DPI multi-monitor hardware, broader browser/PDF focus behavior, Japanese live OCR and clean-machine packaging remain unverified.

## References and inspected evidence

- [TDK source repository](https://github.com/ogun/guncel-turkce-sozluk)
- [v12 database history](https://github.com/ogun/guncel-turkce-sozluk/commits/master/sozluk/v12/v12.gts.sqlite3.db)
- [Autocomplete-only update workflow](https://github.com/ogun/guncel-turkce-sozluk/blob/master/.github/workflows/download-autocomplete-json.yml)
- [Stanza releases](https://github.com/stanfordnlp/stanza/releases) and [1.14 model resource manifest](https://raw.githubusercontent.com/stanfordnlp/stanza-resources/main/resources_1.14.0.json)
- [TurkishWordNet-Py / KeNet](https://github.com/starlangsoftware/TurkishWordNet-Py)
- [PaddleOCR current upstream](https://github.com/PaddlePaddle/PaddleOCR) and [local pipeline API](https://github.com/PaddlePaddle/PaddleOCR/blob/main/paddleocr/_pipelines/ocr.py)
- [Tureng scraper repository](https://github.com/helallao/tureng) and [Tureng terms](https://tureng.com/en/termsofuse)
- [Kaikki Turkish overview](https://kaikki.org/dictionary/Turkish/index.html) and [recommended raw downloads](https://kaikki.org/dictionary/rawdata.html)
- [Qt clipboard behavior and platform notes](https://doc.qt.io/qt-6/qclipboard.html)
- [Windows SendInput behavior and integrity restrictions](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [TDK client sound mapping](https://github.com/clydeofficial/tdk-sozluk/blob/main/src/features/ses.js), [sound URL construction](https://github.com/clydeofficial/tdk-sozluk/blob/main/src/utils/normalize.js), and [service hosts](https://github.com/clydeofficial/tdk-sozluk/blob/main/src/core/constants.js). Client code was inspected; live service access was not confirmed.

Local evidence: the implemented Turkish route is in `language/`, `dictionary/turkish_store.py`, `dictionary/turkish_lookup.py`, `gui/turkish/`, and `scripts/turkish.py`. Hiku's `crates/turkish/src/lib.rs` provides the inspected diacritic-recovery reference. Japanese `dictionary/customdict.py` and `lookup.py` still use pickle data and deconjugation; `ocr/hit_scan.py`, provider filtering, shared activation generations, and the popup screen lock remain integration points. Turkish CLI dispatch bypasses the normal OCR/capture startup path; unified language setup is still pending.
