# Meikipop

Look up words on your screen, hear them, translate sentences and send cards to Anki. Works with Japanese, Turkish and other Yomitan dictionaries.

[Download](https://github.com/namidanokisetsu/meikipop/releases/latest) the Windows EXE or the Mac DMG. Pick a language and let setup download its dictionaries and models, or skip and add them yourself. Lookup and translation run locally. Online recordings are optional.

- App: Python, PyQt6, SQLite.
- Dictionaries: Yomitan, Jitendex, Wiktionary.
- OCR: MeikiOCR, PaddleOCR PP-OCRv6, Chrome Screen AI, Apple Vision.
- Translation: Hy-MT2 1.8B / 7B, Q8_0, llama.cpp.
- Base forms: Stanza. Japanese uses deconjugation rules.
- Audio: system TTS, Wikimedia recordings, local audio databases.

Fork of [rtr46/meikipop](https://github.com/rtr46/meikipop). GPL-3.0. [Setup details](docs/TURKISH_SETUP.md).
