# Meikipop

Meikipop is a popup dictionary for games, subtitles and other text on your screen. Hold your scan shortcut and point at a word to look it up, hear it or translate its sentence. Save words to Anki with context, screenshots and available recordings. Supports Japanese, Turkish and other languages through Yomitan dictionaries.

[Download](https://github.com/namidanokisetsu/meikipop/releases/latest) for Windows or macOS (Apple silicon and Intel). On first launch, choose a language and the dictionaries and models you want. Lookup and translation work offline after setup; online pronunciations are optional.

- App: Python, PyQt6, SQLite.
- Dictionaries: Yomitan, Jitendex, Wiktionary.
- OCR: MeikiOCR, PaddleOCR PP-OCRv6, Chrome Screen AI, Apple Vision.
- Translation: Hy-MT2 1.8B / 7B, Q8_0, llama.cpp.
- Word forms: Japanese deconjugation rules, Zeyrek for Turkish, optional Stanza for other languages.
- Audio: system TTS, Wikimedia recordings, local audio databases.

Fork of [rtr46/meikipop](https://github.com/rtr46/meikipop). GPL-3.0. [User guide](docs/USER_GUIDE.md).
