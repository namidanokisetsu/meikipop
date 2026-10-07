Updated: 2026-10-06

# Shared Japanese, Turkish and Yomitan popup

The requested shared app supersedes the earlier separate-app-only plan. Keep
the shared Japanese rendering while using one language selector,
search surface and dictionary library. The original Japanese and Turkish
clients remain explicit compatibility entrypoints.

## Current design

1. **Indexed library.** Import local Yomitan definition, forms, frequency, pitch and
   kanji archives into immutable SQLite packs. Imports are atomic and
   cancellable; per-pack enablement and ordering are separate preferences.
   Imports show percentages through bank processing and indexing; 100% follows
   publication. Downloads show percentages when their total size is known.
   Explicit recommended downloads reuse this importer. Removal closes readers
   and deletes every stored revision of the selected pack.
   Structured Turkdict content and multiple Japanese dictionaries share the
   existing HTML converter. The working local library includes full Turkdict,
   Jitendex, KANJIDIC and Jiten packs; data and models stay outside Git.
   In-process changes refresh readers immediately; external inventory changes have
   a two-second fallback check. Search caches include each reader's library revision.
   Japanese pitch packs retain reading-specific alternatives, source labels, tags,
   nasal/devoicing markers and numeric or H/L patterns. Schema 3 keeps older packs
   readable; reimport adds pitch metadata transactionally with live readers.
   The optional Japanese pitch display uses high-mora overlines and downstep marks.
   This adapts [Chibipop's pitch approach](https://github.com/stellarie/chibipop/blob/main/src/dict/pitch.rs)
   to our existing SQLite library and Qt HTML rather than its Rust renderer.

2. **One popup.** Debounced typing, Enter, explicit local translation and OCR
   use the shared result surface. A worker retains only the newest pending
   search. OCR misses hide the preview and scanning continues while held.
   Manual search translates misses. Launches without lookup text start in the tray.
   Edits invalidate old results immediately. Keep source labels,
   independent expansion, scrolling, pinning, resizing and Back. Show supplied
   frequency, inflection and kanji data without merging distinct source senses
   or inventing missing kanji components. Profile changes also reload cached
   settings controls. Ruby explicitly resolves the selected font for kana and
   kanji, uses visible glyph bounds for spacing, and defaults to gray at 50%
   with a Japanese size control. Autoplay remembers all pronunciations in a
   scan-key hold; manual playback remains repeatable. Headword and definition
   readings default to brackets, with separate Japanese furigana toggles.
   Shared dictionary rendering retains topic/usage labels, emphasis, line breaks
   and merged table cells; forms use visible status labels and theme-aware borders.
   Frequency display defaults to the harmonic mean of positive ranks, with one
   best rank per dictionary; counts and nonnumeric labels are excluded. Per-source
   display remains optional. Themes are Monochrome Dark, Light and Custom; removed
   dark presets migrate to Monochrome Dark while saved colors seed Custom once.
   Unchanged render identities preserve documents and selections; fitting is coalesced.
   Selection lookup inside results is independently opt-in for new profiles, with
   a one-time migration preserving existing behavior. The Turkish compatibility
   browser retains immediate double-click lookup without a duplicate release request.
   Pin freezes a preview; existing dismissal and fresh-scan actions leave it.
   Pinned OCR results include compact original context, enabled by default with
   a per-profile Appearance toggle. Long context is limited to two lines that adapt
   to the popup width; copy, translation and audio retain the complete context.
   Dictionary-provided disclosures remain independently collapsible after pinning,
   including nested Turkdict sections; toggles preserve the reading position and
   history restores their state. Embedded Turkish source headings share the popup's
   source style; expansion links stay separate from selection lookup after scrolling.
   Audio orders enabled Online pronunciations, System voice and Local recordings in one
   per-profile list with checkboxes, drag/drop and arrows, preserving existing choices. Online
   retrieves language-matched Wiktionary/Lingua Libre files from Wikimedia Commons on
   the audio worker through indexed title searches with exact language/word filters, bounded downloads, cached
   misses and fallback to the next enabled source. System voice can run before the network.
   Recording attribution remains accessible from the audio menu. Existing local database
   profiles keep their priority order; new profiles default to system voice first.
   Explicit word lookup within typed or pasted input retains the full input as
   sentence context through dictionary analysis, translation, audio, copying and Back.

3. **Language policies.** Japanese deconjugation and Turkish accent recovery
   remain specialized. Other installed languages use indexed entries/readings
   and imported forms. Russian additionally tries bounded е/ё variants after
   an exact/form miss, reusing indexed packs without neural analysis.
   Form labels retain equally short alternatives without cyclic homograph detours;
   Russian stress-only readings appear once in the headword.
   Small Unicode word/sentence policies share a registry
   design inspired by [Anki Miner's language registry](https://github.com/0xzerolight/anki_miner/blob/a1955f4a/anki_miner/languages/registry.py),
   independently implemented without importing its NLP models. Original text
   and offsets are preserved for OCR hit-testing and sentence copying. Optional
   lemma fallback reuses the Turkish Stanza adapter for other languages after
   dictionary forms miss. Stanza has a shared
   [processor API](https://stanfordnlp.github.io/stanza/pipeline.html) with
   [language-specific models](https://stanfordnlp.github.io/stanza/download_models.html),
   rather than one model for every language. Dictionaries exposes **Find base forms**,
   installation status and explicit **Install model**; enabling it never downloads.
   Setup installs only the required processors and dependencies. Imports remain lazy,
   runtime offline and worker-bound; Japanese never invokes neural analysis.

4. **Local OCR and context.** Windows defaults to MeikiOCR for Japanese and
   Paddle for Turkish and Indonesian. Languages outside Paddle's coverage,
   including Russian, default to Chrome Screen AI; incompatible Paddle choices
   are disabled. New profiles inherit the current scan shortcuts, including disablement.
   macOS also offers native Vision with runtime language checks.
   The Windows desktop environment uses Python 3.12 and PaddleOCR 3.7
   PP-OCRv6 small models, supporting 50 languages on CPU. Unicode word assembly
   corrects Paddle's accent fragments; nearby aligned lines retain visible
   sentence context.
   Model creation and inference remain off the Qt thread. Copy sentence is an
   explicit local clipboard action using visible scanned context, with a local
   Ctrl/Cmd+Shift+C shortcut. Copy sentence closes the popup; selected-text copying
   keeps it open. History retains that context. No automatic text
   upload for dictionary/translation lookup or ChatGPT API connection is added.
   Online pronunciation mode sends only the requested word and language to Wikimedia.
   Pointer hit-testing reuses recognized
   frames independently of fresh recognition, with dictionary work on a separate worker.
   Windows captures regions through worker-owned MSS with immutable geometry and pixel
   ownership; unsupported capture uses the guarded Qt fallback. Capture exclusion is held
   through a scan. Stationary capture requests are spaced by 250 ms when the worker is free,
   plus the 16 ms scheduling tick; capture and recognition add their own latency. Cached
   live frames expire after two seconds and cannot cross sessions, screens or profiles.
   Clipped paragraphs trigger at most two bounded crop expansions. Per-profile
   Freeze while held reuses one full-display screenshot, including expanded crops, until
   release or invalidation; it defaults on and can be disabled for live scanning. Scan transitions and
   capture ownership live in the pure `gui/lookup_session.py` controller so old callbacks
   cannot unlock a newer capture. These additions adapt interaction ideas from
   [Chibipop](https://github.com/stellarie/chibipop/blob/main/ARCHITECTURE.md)
   within the existing Qt pipeline.
   Previews stay anchored until the lookup changes and fit complete text lines.
   Scanning requires a held trigger; automatic hover scanning is removed.

5. **Optional local translation.** Explicitly installed
   [Hy-MT2](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) GGUF models run through
   local llama.cpp, with Quality 7B Q8_0 and Lightweight 1.8B Q8_0 selectors.
   Both support 33 languages plus five regional and minority varieties.
   There is no silent fallback or Argos backend. Models start lazily when
   a sentence lookup or Translate is requested; downloads occur only in setup. Custom servers must
   use loopback HTTP, without proxies or redirects, and can extend translation
   coverage with other models. Results identify the model.
   Translation settings offer automatic or manual source and target language
   strips independently of the dictionary profile. Ordinary settings save immediately.
   Sentence lookups translate automatically; unpunctuated Japanese input falls back
   to translation after a partial dictionary match. Manual word misses always translate,
   including without installed or enabled dictionaries; partial-match routing for explicit
   word lookups remains optional. English-to-Turkish dictionary lookup requires a
   direct meaning match; incidental definition/example mentions fall through to translation.
   Streaming is batched, cancellable through startup
   and HTTP reads, and retains useful dictionary content. Keep model warm is optional,
   defaults off, and changes only the owned server on the next intentional translation.

6. **Optional Anki.** A small AnkiConnect v6 adapter uses explicit loopback HTTP
   requests on background workers. Per-profile settings store deck, note type,
   field mappings, tags and an independently recorded popup shortcut. Export snapshots
   the chosen dictionary entry and original sentence, with editable definition/context
   and optional frequency/pitch fields. The first Anki field must map to the word;
   duplicates are refused within the chosen deck and note type. Writes are never
   retried automatically; timeouts report an uncertain outcome. Enabling Anki or
   opening its enabled settings loads decks and fields; stale profile replies are
   ignored. A round Anki plus button appears at the bottom left when enabled. Field suggestions
   normalize case/separators, use common aliases and conservatively match spelling.
   Saved manual mappings remain intact. Kikitori-compatible exports include editable
   translation, dictionary-derived sentence furigana, pitch positions/categories,
   captured screenshots and a matching loaded word recording. Media uploads finish
   before the note is written; no new screenshot is taken during export.
   This adapts [Chibipop's Anki integration](https://github.com/stellarie/chibipop/blob/main/src/anki.rs)
   to Qt and the existing entry/context model. Existing-note updates remain excluded.

## Compatibility and remaining acceptance

- The shared desktop has a one-time resource suggestion per added language and a per-user Windows installer,
  plus Apple silicon/Intel DMGs. Bundles include Python and inference libraries,
  not user dictionaries or model weights. Settings downloads OCR, translation
  and base-form models explicitly; frozen builds use bundled setup workers.
  Existing settings skip the initial suggestion. Later dismisses each profile's
  resource suggestion permanently; individual installers remain in Settings.
  Installer upgrades/uninstall preserve user data. Publisher signing and Apple
  notarization still require release credentials.
  Selecting a language offers individually optional dictionaries and supported
  models. Translation defaults unchecked, with lightweight/quality choices;
  Later starts without downloads. New installations have Japanese only; Turkish
  appears after explicit addition or dictionary import. The tray has no setup menu.
  Green is the new default appearance,
  with percentage background opacity available for every theme. Popup expansion
  preserves an above-text preview's lower edge and fits within the display. ZIP imports run
  in a separate process and continue with Settings closed. CRC metadata is advisory;
  decompression, JSON and entry validation still reject unreadable content.

- Preserve the existing configuration, original Japanese `dictionary.pkl`,
  and separate Turkish data/settings. `meikipop legacy-japanese` and
  `meikipop-turkish` retain the earlier workflows and providers.
- Non-OCR global shortcuts are independently recorded and enabled. Defaults
  remain off in library code; the user's requested search shortcut can be
  provisioned in this workspace. Model and dictionary downloads remain explicit.
- macOS requires Input Monitoring/Screen Recording permissions. Recognition
  languages follow the installed Vision version or selected OCR component.
  Native capture exclusion, mixed-DPI placement, global gestures and packaging still
  require platform acceptance; fixture timings do not measure model inference speed.
- Fixture tests cover dictionary metadata, language policies, latest-request
  delivery, popup controls/context, import safety and translation. Final broad
  test results belong to the current run, not a fixed count in this document.

Implementation lives in `dictionary/library.py`, `dictionary/search.py`,
`dictionary/translation.py`, `language/profiles.py`, `gui/quick_lookup.py`,
`gui/dictionary_manager.py`, and `gui/unified_ocr.py`. The retained Turkish
client lives under `gui/turkish/`. See [setup and usage](TURKISH_SETUP.md).

Resources tab groups explicit downloads, reports file readiness and names current OCR/translation selections.
Translation models share one installation across profiles, with separate per-profile selection.
Dictionary removal clears the recommended pack indicator; manual imports stay in Dictionaries.
Packaged OCR includes the PaddleX extras metadata checked at runtime. Model setup errors preserve
underlying exceptions and validate loaded Stanza/Paddle models before reporting success.
