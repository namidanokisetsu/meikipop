# Turkish support and Japanese parity

Updated: 2026-09-09. Turkish is a separate app branded `meikipop-turkish`. The
Japanese build and its existing UI are the acceptance reference. Do not change
Japanese behavior or presentation.

## Goal

Make Turkish behaviorally and visually identical to Japanese wherever the
dictionary backend permits it. Only Turkish OCR, NLP, dictionary data and
language-specific content may differ. Keep the identities distinct so both apps
can be installed and used without confusion.

## Implementation status

1. **Japanese input parity implemented.** Clipboard, selected-text shortcut,
   drag selection, optional double-click and typed search reuse existing shortcut
   recording and clipboard-restoring selection capture. All text inputs default
   off and each shortcut is independently configurable. Turkish drag and
   double-click toggles are separate. Tray actions own search, clipboard,
   settings, pause and quit; Japanese files and settings are unchanged.

2. **Turkish popup implemented.** Shared theme, positioning and popup styling;
   compact source headers and definition indentation; italic examples; full-width
   show-more rows; a checked pin icon; click-to-pin, outside-click and Escape
   dismissal. Inside definitions/examples, dragged selections, double-click,
   selected-text shortcuts and scan-key lookup share the same history and lookup
   path, without clipboard capture. Empty OCR hits hide the popup.
   TDK, Wiktionary and KeNet can be
   reordered in Settings without combining their senses. KeNet remains collapsed
   alongside dictionary results, and opens directly when it is the only match.

3. **OCR dispatch separated.** Recognition has its own latest-frame worker;
   pointer hit-testing reads cached boxes on the Qt thread, and only the latest
   text lookup waits for Stanza/TDK/KeNet/Wiktionary. Background captures retain
   the configurable throttle and stale deliveries are rejected. CPU inference
   and unchanged-image caching remain offline. The historical 237 ms changed
   frame / 0.1 ms cached-hit measurements are not new-build benchmarks.

4. **Updateable English dictionary implemented.** Import Turkish-to-English
   Yomitan releases from [wiktionary-to-yomitan](https://github.com/yomidevs/wiktionary-to-yomitan),
   using the repository's current Hugging Face download feed. Settings explicitly
   installs/updates a separate SQLite pack; no dictionary snapshot is bundled.
   Record revision, source SHA-256 and attribution. Reuse the existing Yomitan
   structured-content converter, preserving upstream glosses, labels, examples
   and links. Turkish-specific overrides provide compact previews and local
   link navigation. Upstream plain-text form references remain plain text.
   No Tureng integration or global sense ranking.

5. **Turkish Windows release process implemented.** Dedicated window, tray,
   settings, notifications, executable, app ID, shortcuts and per-user Inno Setup
   installer. Existing `Meikipop/Turkish` settings and `languages/tr` data paths
   are retained, so no migration or Japanese settings rewrite is needed.
   First launch opens data settings when TDK is missing. Python, Qt, Stanza,
   Torch and Paddle dependencies are bundled; data/model downloads remain explicit.
   Complete staged asset installs record checksums and retain one previous
   installation for rollback. Optional pronunciation uses an installed Turkish
   system voice instead of the Japanese audio database. Build locally with
   `Build-Turkish.ps1` or the Turkish Windows workflow; installer artifacts have
   SHA-256 sidecars. No publishing or installation on this desktop is automatic.

## Rules

- Treat `../meikipop-japanese-clipboard` as the etalon and keep Japanese files,
  settings and implementation unchanged.
- Keep Turkish runtime lookup offline, imports lazy, model/data setup explicit,
  and downloaded data, weights, packs and environments out of Git.
- Keep Turkish and Japanese work in separate focused commits and worktrees.
- Extend shared components where that preserves Japanese behavior; document only
  genuine Turkish divergence.

## Validation and user acceptance

- The fixture suite passed 99 tests. Focused GUI checks passed after the final
  dispatch cleanup and in-popup lookup additions (28 GUI tests). Standalone dependency/resource imports passed without OCR
  inference. No new actual-model OCR tests or benchmarks were run, as requested.
- The user owns hands-on input/focus, popup appearance, audio, OCR accuracy,
  browser/PDF, mixed-DPI and clean-machine install/upgrade/uninstall acceptance.
  Code implementation does not establish visual or clean-machine acceptance.
- This release uses CPU OCR. GPU compatibility and CPU/GPU performance
  measurements are optional follow-up work, not claimed as completed.

## Implementation locations

- Japanese reference: `../meikipop-japanese-clipboard`, shared popup and input
  components.
- Turkish input and popup: `src/meikipop/gui/turkish/`.
- Turkish dictionaries and analyzers: `src/meikipop/dictionary/` and
  `src/meikipop/language/`.
- Turkish OCR: `src/meikipop/ocr/turkish_paddle.py`.
- Source locks: `src/meikipop/resources/turkish/`.
- Setup and usage: [TURKISH_SETUP.md](TURKISH_SETUP.md).
