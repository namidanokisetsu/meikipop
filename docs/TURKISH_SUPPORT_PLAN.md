Updated: 2026-10-06

# Shared Japanese, Turkish and Yomitan popup

The requested shared app supersedes the earlier separate-app-only plan. Keep
the shared Japanese rendering while using one language selector,
search surface and dictionary library. The original Japanese and Turkish
clients remain explicit compatibility entrypoints.

## Current design

1. **Indexed library.** Import local Yomitan definition, forms, frequency and
   kanji archives into immutable SQLite packs. Imports are atomic and
   cancellable; per-pack enablement and ordering are separate preferences.
   Explicit recommended downloads reuse this importer. Removal closes readers
   and deletes every stored revision of the selected pack.
   Structured Turkdict content and multiple Japanese dictionaries share the
   existing HTML converter. The working local library includes full Turkdict,
   Jitendex, KANJIDIC and Jiten packs; data and models stay outside Git.
   In-process changes refresh readers immediately; external inventory changes have
   a two-second fallback check. Search caches include each reader's library revision.

2. **One popup.** Debounced typing, Enter, explicit local translation and OCR
   use the shared result surface. A worker retains only the newest pending
   search; edits invalidate old results immediately. Keep source labels,
   independent expansion, scrolling, pinning, resizing and Back. Show supplied
   frequency, inflection and kanji data without merging distinct source senses
   or inventing missing kanji components. Profile changes also reload cached
   settings controls. Ruby explicitly resolves the selected font for kana and
   kanji, uses visible glyph bounds for spacing, and defaults to gray at 50%
   with a Japanese size control. Autoplay remembers all pronunciations in a
   scan-key hold; manual playback remains repeatable.
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
   a per-profile Appearance toggle. Copy and translation retain the complete context.

3. **Language policies.** Japanese deconjugation and Turkish accent recovery
   remain specialized. Other installed languages use indexed entries/readings
   and imported forms. Small Unicode word/sentence policies share a registry
   design inspired by [Anki Miner's language registry](https://github.com/0xzerolight/anki_miner/blob/a1955f4a/anki_miner/languages/registry.py),
   independently implemented without importing its NLP models. Original text
   and offsets are preserved for OCR hit-testing and sentence copying. Optional
   lemma fallback reuses the Turkish Stanza adapter for other languages after
   dictionary forms miss. Stanza has a shared
   [processor API](https://stanfordnlp.github.io/stanza/pipeline.html) with
   [language-specific models](https://stanfordnlp.github.io/stanza/download_models.html),
   rather than one model for every language. Setup is explicit, imports lazy,
   runtime offline and worker-bound; Japanese never invokes neural analysis.

4. **Local OCR and context.** Windows defaults to MeikiOCR for Japanese and
   Paddle for Turkish; every profile can select Paddle or Chrome Screen AI.
   macOS also offers native Vision with runtime language checks.
   The Windows desktop environment uses Python 3.12 and PaddleOCR 3.7
   PP-OCRv6 small models, supporting 50 languages on CPU. Unicode word assembly
   corrects Paddle's accent fragments; nearby aligned lines retain visible
   sentence context.
   Model creation and inference remain off the Qt thread. Copy sentence is an
   explicit local clipboard action using visible scanned context, with a local
   Ctrl/Cmd+Shift+C shortcut. History retains that context. No automatic text
   upload or ChatGPT API connection is added. Pointer hit-testing reuses recognized
   frames independently of fresh recognition, with dictionary work on a separate worker.
   Windows captures regions through worker-owned MSS with immutable geometry and pixel
   ownership; unsupported capture uses the guarded Qt fallback. Capture exclusion is held
   through a scan. Stationary capture requests are spaced by 250 ms when the worker is free,
   plus the 16 ms scheduling tick; capture and recognition add their own latency. Cached
   frames expire after two seconds and cannot cross sessions, screens or profiles.
   Previews stay anchored until the lookup changes and fit complete text lines.
   Scanning requires a held trigger; automatic hover scanning is removed.

5. **Optional local translation.** Explicitly installed
   [Hy-MT2](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) GGUF models run through
   local llama.cpp, with Quality 7B Q8_0 and Lightweight 1.8B Q8_0 selectors.
   Both support 33 languages plus five regional and minority varieties.
   There is no silent fallback or Argos backend. Models start lazily when
   Translate is pressed; downloads occur only in setup. Custom servers must
   use loopback HTTP, without proxies or redirects, and can extend translation
   coverage with other models. Results identify the model.
   Translation settings offer automatic or manual source and target language
   strips independently of the dictionary profile. Ordinary settings save immediately.
   Automatic sentence and miss/partial-match routing default off in new profiles;
   migration preserves existing routing. Streaming is batched, cancellable through startup
   and HTTP reads, and retains useful dictionary content. Keep model warm is optional,
   defaults off, and changes only the owned server on the next intentional translation.

## Compatibility and remaining acceptance

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
