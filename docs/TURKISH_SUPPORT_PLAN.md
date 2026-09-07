# Turkish support and shared desktop input

Updated: 2026-09-07. Current scope: finish reusable Japanese text input, reinstall the Japanese Windows app, and retain Turkish as a usable source-install MVP. Japanese and Turkish should ship as separate installers with separate launch entries; no combined installer. Broad desktop acceptance belongs to the user. Optional Turkish packs and release infrastructure are deferred.

See [setup and usage](TURKISH_SETUP.md) for Turkish installation, commands and data locations.

## Delivered

- Japanese clipboard lookup, compact typed search and Windows selected-text lookup. Each global shortcut is disabled by default and independently editable in Settings ? Text Lookup; an enable checkbox controls each recorder. Presets are Ctrl+Alt+L (clipboard), Ctrl+Alt+D (search) and Ctrl+Alt+S (selection). All feed the existing Japanese dictionary/deconjugation worker and popup. Automatic clipboard lookup is separately opt-in in Settings or the tray. Turkish clipboard/search shortcuts and automatic copy/double-click capture also default off; older implicit Turkish defaults reset once on upgrade. Existing Japanese OCR, rendering, configuration and audio behavior are retained.
- Shared Windows selection capture waits for shortcut modifiers to be released, keeps source focus, requires a fresh clipboard sequence and cancels on focus change or timeout. Automatic monitoring ignores the capture's clipboard events. Existing clipboard MIME formats are restored only while the observed sequence is still current. Japanese and Turkish reuse this helper for opt-in double-click lookup; Japanese exposes it in Settings ? Text Lookup.
- Shared text-shortcut normalization supports Windows virtual-key events from accessibility input tools. Japanese and Turkish share popup placement/style and unchanged-image OCR caching on the Turkish branch; language workers and rendering remain separate.
- Turkish tray-first popup: TDK definitions/examples, clickable tokens, compact search, automatic copy-to-pin, double-click selection, Shift OCR preview, pinning, Escape/outside-click dismissal, Back navigation and expandable WordNet. Settings retain appearance, input and explicit background data/model installation independently of Japanese settings.
- Offline TDK SQLite importer/store, lazy Stanza analysis, phrase lookup, Turkish-aware casing retry and bounded dictionary-validated correction suggestions. CLI debugging retains source spans, raw MWT Words and attempted lookup routes.
- Offline KeNet SQLite pack with independent synsets, typed relations and linked navigation. Compatible POS and the queried member's own sense number determine ordering; TDK sense order stays separate. Ambiguous multi-member derivation edges are hidden.
- Local PaddleOCR with explicit setup and cached recognition. Turkish inference stays offline; absent Stanza models permit exact lookup. Installer workers release database/model handles before replacing files and resume with fresh caches.

## Repository and installed Japanese version

One repository, with separate reviewable branches/worktrees:

- `feature/native-input-audio` in `../meikipop`: original Japanese base at `666b479`.
- `feature/japanese-clipboard` in `../meikipop-japanese-clipboard`: Japanese clipboard/search/selection additions, without Turkish NLP dependencies.
- `feature/turkish-support` in this checkout: Turkish implementation plus the shared Japanese input changes.

Build the Japanese executable from its dedicated worktree with the existing Windows PyInstaller spec and Japanese project environment. Built and installed on 2026-09-07 at `%LOCALAPPDATA%\Programs\meikipop\meikipop.exe`; retain existing dictionaries, OCR models, settings and startup shortcuts. Clean-rebuilt and reinstalled after fixing a launch crash caused by passing Qt signal `emit` directly to the pynput mouse listener. A Python callback now bridges the signal; regression coverage constructs a real listener without starting a desktop hook. Installed and built executable hashes match; the replacement stays running and logs successful OCR scans. Prior executables are retained as `meikipop.exe.pre-text-input.bak` and a timestamped `meikipop.exe.pre-launch-fix-*.bak`. Generated binaries, environments, data and model weights remain ignored by Git.

Keep focused commits. Existing uncommitted Turkish lemma recovery and shortcut fixes were preserved separately. No history rewriting, branch deletion, remote push or publication is needed. After user acceptance, integrate the Japanese branch into the maintained base; retain the Turkish worktree until its separate scope is accepted.

## Remaining work, in priority order

1. **User acceptance of Japanese input.** Try selected text, copied text and typed search in normal reading apps, plus existing OCR/audio. Report concrete failures for focused fixes. Selection requires a copyable source; image-only text still uses OCR. No broad automated desktop session is scheduled.
2. **Turkish OCR responsiveness and user acceptance.** Reader reports noticeably less smooth OCR than Japanese. Code inspection shows CPU PaddleOCR followed by Stanza analysis/recovery and KeNet on one serialized worker, versus Japanese MeikiOCR and dictionary deconjugation. Unchanged-image/text caching exists; cold initialization and changed text still cost inference. The dominant cause has not been measured. This PC has an RTX 5070, but Turkish currently has CPU-only PyTorch 2.8.0 and PaddlePaddle 3.3.1; GPU acceleration requires compatible packages and device selection. Installed Japanese MeikiOCR also reports CPU execution. If requested, distinguish recognition time from analysis/queue delay with one focused trace before changing models or splitting the worker. Browser/PDF focus behavior, mixed-DPI monitors and actual reading examples remain user checks. Revisit the reported missing final `r` in `hay?rd?r` only when the exact failing input is available; previous focused checks did not reproduce it.
3. **Optional Turkish English definitions, deferred.** A separate locked Kaikki English-Wiktionary pack, filtered to Turkish, should preserve POS, glosses, labels, examples and form-of links. Do not align senses with TDK or KeNet.
4. **Optional Turkish audio, deferred.** Verify actual recording access and mappings before a resumable offline TDK builder. Reuse the existing `android.db` reader schema and audio worker. Manual persistent-popup replay needs explicit playback intent and request-generation checks. Missing audio must not block text lookup.
5. **Separate installers, deferred release work.** The current Japanese handoff replaces the existing portable executable; it is not a newly authored setup wizard. Keep Japanese and Turkish installer identities, shortcuts and uninstall targets separate, and keep Turkish dependencies out of the Japanese build. For Turkish: Versioned dictionary release assets, checksum/update/rollback flow and a separate Turkish-enabled Windows build. Reuse the current PyInstaller structure; do not install Python packages from the GUI. Clean-machine acceptance remains unverified. Japanese local reinstallation does not complete this milestone.

Japanese dictionary import also needs a safe UI if requested: the existing source CLI converts term ZIPs into one replacement pickle, with no pack toggles, standalone frequency merging, pitch import or kanji-bank import. Preserve the active dictionary until this is addressed.

Further Turkish morphology expansion, UI redesign and generic language infrastructure are outside the current request. No analyzer tournament, suffix-explanation engine, translation of TDK definitions, browser extension or Tureng integration.

## Implementation constraints retained

- Stanza 1.14.0/resources 1.14.0 with IMST tokenize/MWT and `imst_charlm` POS/lemma; setup/runtime configuration and analyzer identity agree. No parser, NER or runtime downloads. Imports stay lazy.
- TDK: locked `ogun/guncel-turkce-sozluk` v12 snapshot, indexed read-only runtime SQLite and Turkish-aware keys. The local pack has 99,209 visible entries. Preserve ordered senses/examples, homographs, POS-gated verb aliases and source anomalies.
- KeNet: revision `718fd441262602db6ea1ac9e2dcf3a5142bda06d`, 78,327 synsets, 110,259 members and 213,403 edges with no missing targets in the imported pack. Retain attribution, source identity, GPL-3.0 notices and independent sense IDs. Missing KeNet must not break TDK lookup.
- PaddleOCR 3.7.0, PaddleX 3.7.2, PaddlePaddle 3.3.1 and local PP-OCRv6 small models. Setup stages weights and records hashes; runtime verifies local paths. Japanese continues to use its existing OCR provider.
- Preserve original text/spans and normalize lookup keys separately (`I` to `?`, `?` to `i`). Parent MWT spans remain selectable; the adapter currently uses the first expanded Word's lemma/POS, with all Words available in diagnostics.
- Phrase lookup considers up to five tokens and retains source spans and lookup routes (`fark etti` ? `fark etmek`). Normal UI omits infrastructure diagnostics.
- Recovery follows ordinary lookup and casing retry. Guesses remain separately labeled and dictionary-validated. Nominal recovery supports a conservative single-suffix subset, not arbitrary Turkish suffix chains.
- Recovery bounds: source words of 2?32 letters; at most 64 diacritic variants, three substitutions and 256 queued states; six nominal stem proposals; eight corrected contexts; 256 single-edit candidates; five distinct headword suggestions. An analyzed ASCII lemma can also supply a bounded diacritic suggestion (`Icerikleriniz` ? `i?erik`). Original analysis remains intact.
- Text input is limited to 2,000 characters. No clipboard history, screen-image logging or text uploads. Stale generations cannot replace newer lookup results. Pinned Turkish lookup suspends background replacement.
- Selection capture is Windows-only. It does not elevate, use accessibility frameworks or claim support for every app. Clipboard restoration is a deliberate reuse of the implemented Turkish behavior; native formats not exposed by Qt are not guaranteed.

## Validation

Current lightweight validation: **87 unit tests passed** with `.venv/Scripts/python.exe -m unittest discover -s tests`. The dedicated Japanese environment also passed all 37 tests before the clean rebuild. Coverage includes real pynput callback construction and signal forwarding, shared selection modifier waits, fresh-copy/timeout handling, focus-change cancellation, rich clipboard restoration, duplicate suppression and Japanese worker reuse, disabled defaults, live shortcut replacement and duplicate-binding rejection.

The existing offline Stanza and Paddle smoke scripts remain available for specific analysis/OCR failures. They were not rerun for this input-focused handoff. The preserved ASCII-lemma fix has fixture coverage; its newly added actual-model case is not yet verified. Earlier real-model and controlled desktop checks are historical evidence, not a claim of current broad acceptance.

Follow [AGENTS.md](../AGENTS.md): focused fixtures, one appropriate suite run, no repeated live testing or benchmark work without a concrete need. Leave clean-machine packaging, browser/PDF combinations and mixed-DPI hardware checks to user acceptance.

## Source locks and implementation

- [`resources/turkish/sources.json`](../src/meikipop/resources/turkish/sources.json): TDK source/checksum.
- [`resources/turkish/wordnet.json`](../src/meikipop/resources/turkish/wordnet.json): KeNet source/checksum and attribution.
- Shared input: `gui/clipboard_lookup.py`, `gui/selection.py`, `gui/text_shortcuts.py`.
- Turkish adapters: `language/`, `dictionary/turkish_*`, `gui/turkish/`, `scripts/turkish.py`.
- Optional future sources: [Kaikki raw downloads](https://kaikki.org/dictionary/rawdata.html), [TDK recording client](https://github.com/clydeofficial/tdk-sozluk/blob/main/src/features/ses.js). Live recording access remains unconfirmed.
