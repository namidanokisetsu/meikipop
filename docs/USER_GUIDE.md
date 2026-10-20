# Using Meikipop

## Install

[Download](https://github.com/namidanokisetsu/meikipop/releases/latest) the Windows
installer or the macOS DMG for your Mac's processor. Open Meikipop, choose a
language, and select the dictionaries and models to download. You can skip
downloads and add them later in **Settings**. Meikipop runs in the system tray.

On macOS, allow **Screen Recording**, **Input Monitoring** and **Accessibility**
in System Settings → Privacy & Security, then reopen the app. If permissions
stop working after an update, remove the old app from those lists and add it
again. The app is not Apple-notarized, so Gatekeeper may show a warning.

## Look up words

- **On screen:** hold Shift and point at a word. While holding it, click to pin
  the result. Escape or a click outside closes it. Change or disable shortcuts
  in **Settings → Lookup**.
- **In a dialogue box:** enable **Hover scan** from the tray and select an area.
  Point at words inside it without holding a key. The area lasts until you quit.
- **Typed or copied text:** open **Search** from the tray. The configurable text
  shortcut can also open selected text or clipboard text. Select a word in the
  search input and press Enter to look it up with the surrounding sentence.
- **Read more:** click **More** or a dictionary heading to expand definitions.
  **Back** returns to the previous lookup. **Copy sentence** copies the context.

Screen lookup freezes the image while Shift is held. For changing subtitles,
release and press Shift again, or turn off **Freeze capture while holding the
lookup key** in Lookup.
Automatic lookup of selected text is separate and optional.

## Dictionaries and appearance

Switch languages from the tray or Settings. In **Dictionaries**, download
recommended packs or use **Import ZIPs** for Yomitan dictionaries. Enable and
reorder them there. For a bundle containing several dictionary ZIPs, extract
the outer archive first. Japanese recommendations include definitions, kanji,
frequency and pitch accent; available features depend on the installed packs.
**Remove language** deletes its settings while keeping downloaded dictionaries
and models. Keep at least one language; **Add language** restores access to its packs.

Japanese word forms work through bundled rules; Turkish uses bundled Zeyrek.
Other supported languages offer an optional **Download word-form support**
action. OCR and translation coverage depend on the selected provider/model;
Settings shows the available choices for your language.

**Appearance** controls fonts, themes and readings, with separate options for
preview and pinned results. Scrolling is continuous by default; enable
**Snap scrolling** to move between sections.
Set **Definitions** in Preview or Pinned to choose the meaning cutoff; **All**
shows the full content. Turkish misses can still show the analyzed root and
grammar, and screen lookup keeps available spelling suggestions.
These include accent alternatives of recovered Turkish roots, shown as links
without replacing the original analysis.
Settings save immediately and most preferences are separate for each language.

## Audio and translation

Use **Read word** for pronunciation and **Read sentence** for system speech.
In **Audio**, choose and reorder system voices, optional online recordings and
local audio databases. Autoplay can be off, on lookup or only when pinned.
Online pronunciation sends the word and language to Wikimedia; lookup, OCR
and translation run locally after setup.

In **Translation**, download **Lightweight** (Hy-MT2 1.8B, about 2 GB) or
**Quality** (7B, about 8 GB). These are download sizes; running a model needs
additional memory. **Translate** uses the selected model and sentence context.
Typed sentences and manual word misses also use translation; hovering does not.
The first request loads the model. **Keep model warm** avoids later reloads
but keeps its memory allocated.

## Save to Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) and keep Anki
open. Enable **Settings → Anki**, reload decks and fields, choose a deck and
note type, and map the first field to **Word**. Use **+** in the popup to review
and add a card. Sentence, screenshot and available word recordings can be
included. Existing notes are not overwritten. If saving times out, check Anki
before retrying.

For source installation, custom OCR and release procedures, see
[development notes](DEVELOPMENT.md).
