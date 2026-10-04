Updated: 2026-10-05

# Shared Japanese, Turkish and Yomitan popup

The requested shared app supersedes the earlier separate-app-only plan. Keep
the compact Japanese/Nazeka appearance while using one language selector,
search surface and dictionary library. The original Japanese and Turkish
clients remain explicit compatibility entrypoints.

## Current design

1. **Indexed library.** Import local Yomitan definition, forms, frequency and
   kanji archives into immutable SQLite packs. Imports are atomic and
   cancellable; per-pack enablement and ordering are separate preferences.
   Structured Turkdict content and multiple Japanese dictionaries share the
   existing HTML converter. The working local library includes full Turkdict,
   Jitendex, KANJIDIC and Jiten packs; data and models stay outside Git.

2. **One popup.** Debounced typing, Enter, explicit local translation and OCR
   use the shared result surface. A worker retains only the newest pending
   search; edits invalidate old results immediately. Keep source labels,
   independent expansion, scrolling, pinning, resizing and Back. Show supplied
   frequency, inflection and kanji data without merging distinct source senses
   or inventing missing kanji components.

3. **Language policies.** Japanese deconjugation and Turkish accent recovery
   remain specialized. Other installed languages use indexed entries/readings
   and imported forms. Small Unicode word/sentence policies share a registry
   design inspired by [Anki Miner's language registry](https://github.com/0xzerolight/anki_miner/blob/a1955f4a/anki_miner/languages/registry.py),
   independently implemented without importing its NLP models. Original text
   and offsets are preserved for OCR hit-testing and sentence copying.

4. **Local OCR and context.** Windows uses MeikiOCR for Japanese and optional
   Paddle for Turkish; macOS uses native Vision with runtime language checks.
   The tested Windows desktop environment uses Python 3.12 and PaddleOCR 3.7
   PP-OCRv6 small models on CPU for interactive latency. Unicode word assembly
   corrects Paddle's accent fragments; nearby aligned lines retain visible
   sentence context. This is not a claim of best accuracy across screen content.
   Model creation and inference remain off the Qt thread. Copy sentence is an
   explicit local clipboard action using visible scanned context, with a local
   Ctrl/Cmd+Shift+C shortcut. History retains that context. No automatic text
   upload or ChatGPT API connection is added.

5. **Optional local translation.** Explicitly installed
   [Hy-MT2](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) GGUF models run through
   local llama.cpp, with Quality 7B Q8_0 and Lightweight 1.8B Q8_0 selectors.
   There is no silent fallback or Argos backend. Models start lazily when
   Translate is pressed; downloads occur only in setup. Custom servers must
   use loopback HTTP, without proxies or redirects. Results identify the model;
   model claims do not imply verified accuracy for every passage or language.

## Compatibility and remaining acceptance

- Preserve the existing configuration, original Japanese `dictionary.pkl`,
  and separate Turkish data/settings. `meikipop legacy-japanese` and
  `meikipop-turkish` retain the earlier workflows and providers.
- Non-OCR global shortcuts are independently recorded and enabled. Defaults
  remain off in library code; the user's requested search shortcut can be
  provisioned in this workspace. Model and dictionary downloads remain explicit.
- macOS launch/build configuration and CI are prepared. Actual macOS hardware,
  Input Monitoring/Screen Recording permissions, packaged builds, mixed-DPI
  placement and OCR accuracy still need platform acceptance. Windows Turkish
  models are installed and passed a bounded screenshot check; wider OCR
  accuracy remains dependent on fonts and screen content.
- Fixture tests cover dictionary metadata, language policies, latest-request
  delivery, popup controls/context, import safety and translation. Final broad
  test results belong to the current run, not a fixed count in this document.

Implementation lives in `dictionary/library.py`, `dictionary/search.py`,
`dictionary/translation.py`, `language/profiles.py`, `gui/quick_lookup.py`,
`gui/dictionary_manager.py`, and `gui/unified_ocr.py`. The retained Turkish
client lives under `gui/turkish/`. See [setup and usage](TURKISH_SETUP.md).
