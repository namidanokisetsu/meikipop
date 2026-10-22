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
  Point at words inside it without holding a key. The area is remembered between
  sessions while the display layout and scaling match. Enable Hover scan each session.
- **Typed or copied text:** open **Search** from the tray. The configurable text
  shortcut opens selected text, or an empty input when nothing is selected.
  Select a word in the search input and press Enter to look it up with the
  surrounding sentence.
  Japanese Search accepts kanji, hiragana, katakana and romaji such as `neko`,
  `tabemashita` or `kōhī`. Romaji matches appear alongside English matches;
  your input stays unchanged. English words find Japanese dictionary meanings.
- **Read more:** pin the popup to show all definitions. Dictionary headings
  collapse or reopen a dictionary; its own detail links open examples and notes.
  **Back** returns to the previous lookup. **Copy sentence** copies the context.
  Multiple headwords have separate pronunciation and Anki buttons. Each uses that
  headword and reading, combining its definitions across dictionaries.
- **Kanji:** click a character in the headword or bottom cards to open its detail
  pane. Another character replaces it. Click the same character again or use
  the pane's close button to hide it.
  Drag the thin divider to resize the panes; the split is remembered. By default,
  Kanji gets enough room for the stroke diagram where space allows. The popup
  keeps its size; longer details scroll.
  The pane combines shared meanings and readings from your dictionaries;
  **More** reveals reference fields and tags, grouped by source.

Screen lookup freezes the image while Shift is held. For changing subtitles,
release and press Shift again, or turn off **Freeze capture while holding the
lookup key** in Lookup.
Automatic lookup of selected text is separate and optional.
**Lookup → Close popup when cursor leaves** also closes pinned popups when you
move away. Corner search stays open, as does text selection or an open menu.
Ctrl+C copies selected popup text, or the first headword when nothing is selected.
Corner search keeps its size between lookups. Drag an edge to resize it.

## Dictionaries and appearance

Switch languages from the tray or Settings. In **Dictionaries**, download
recommended packs or use **Import ZIPs** for Yomitan dictionaries. Enable and
reorder them there. For a bundle containing several dictionary ZIPs, extract
the outer archive first. Japanese recommendations include definitions, kanji,
frequency and pitch accent; available features depend on the installed packs.
**Data** lists shared models first, then dictionaries and models for each language.
Download, repair, open or remove them there; dictionary checkboxes enable or disable
packs. Built-in resources and linked external files are labeled separately.
Removed files still in use are cleared after restarting Meikipop.
**Remove language** deletes its settings, dictionaries and language-specific models
after confirmation. Shared OCR and translation downloads remain available to other
languages. Keep at least one language.

Japanese word forms work through bundled rules; Turkish uses bundled Zeyrek.
Other supported languages offer an optional **Download word-form support**
action. OCR and translation coverage depend on the selected provider/model;
Settings shows the available choices for your language.

**Appearance** controls fonts, themes and readings, with separate options for
preview and pinned results. Scrolling is continuous by default; enable
**Snap scrolling** to move between sections. Drag the progress bar to jump
between reading positions. Within a section, the wheel and arrows move by whole
text lines. Mouse Back/Forward buttons turn pages over the popup;
**Side-button scrolling** disables this per profile. Over fullscreen Windows
apps, a pinned popup accepts arrows, Page Up/Down and Home/End while the source
keeps focus. **Esc** closes the popup. In **Settings > Shortcuts**, record or
disable lookup and popup bindings. Popup defaults are **R** for replay,
**Shift+A** for Anki, **Shift+C** for copying the sentence and **Alt+Left** for Back.
Close a pinned popup before starting another lookup with a keyboard hold.
**Buttons** controls each popup action independently. **Sentence size** controls
sentence and translation text. Click the compact sentence to read it in full.
Tokyo Night and Dracula use darker, high-contrast palettes. Background opacity
defaults to 98%; changing themes keeps your chosen opacity.
Preview shows one definition without grammar labels by default; change **Definitions** or select **All**.
Pinned results have no definition limit. Turkish misses can still show the analyzed root and
grammar, and screen lookup keeps available spelling suggestions.
These include accent alternatives of recovered Turkish roots, shown as links
without replacing the original analysis.
Settings save immediately. The language selector also changes the active lookup
language; most preferences belong to that language. **Lookup** also contains
the app-wide text shortcut and Windows startup setting. The text shortcut
starts disabled. **First dictionary only** limits preview to the first matching
dictionary; **Text scale** scales word, definition and sentence sizes together.

## Audio and translation

Use **Read word** for pronunciation and **Read sentence** for system speech.
In **Audio**, choose and reorder system voices, optional online recordings and
local audio databases. Autoplay can be off, on lookup or only when pinned.
Online pronunciation sends the word and language to Wikimedia; lookup, OCR
and translation run locally after setup.

In **Translation**, download **Lightweight** (Hy-MT2 1.8B, about 2 GB) or
**Quality** (7B, about 8 GB). These are download sizes; running a model needs
additional memory. Models are shared across languages; new-language setup
reuses installed models. Each language can choose its model and translation pair.
**Translate** opens editable input and translated output. Open it directly from
the tray, or enable **Translate** in **Shortcuts** with the Ctrl+Shift+T preset
(Command+Shift+T on macOS). Click a language name to change it; language search
accepts codes, English names and native names. The swap button reverses direction
and uses the output as the new input. Copy buttons stay beside the language labels.
Use **Translate** or Ctrl+Enter to submit edited input. **Back** returns to the
dictionary with its selection and scroll position preserved.
Drag the divider to resize the text panes. **Translation → Side-by-side text panes**
puts input on the left and output on the right; resize the window as needed.
Long text translates in passages. **Advanced → Passage size** controls their
maximum length; the model's context and output limits still apply per passage.
To translate an English word or phrase into Japanese, use **Translate** and
choose **English → 日本語** when the automatic direction is ambiguous.
With an automatic source, a target that matches the detected language switches
to the other language in the pair.
Typing searches dictionaries and offers available spelling suggestions.
Translation starts only when you choose **Translate**, including for sentences
and words without dictionary matches.
The first request loads the model. **Keep model warm** avoids later reloads
but keeps its memory allocated.

## Save to Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) and keep Anki
open. Enable **Settings → Anki**, reload decks and fields, choose a deck and
note type, and map the first field to **Word**. Click **+** in the popup to save
immediately; click the checkmark to open the saved note in Anki. Map **glossary-first** to the first
entry's full definitions, **glossary** to all entries from the lookup, or
**popup-selection-text** to selected popup text (blank when nothing is selected).
Glossaries include definitions hidden by popup cutoffs or collapsed sections.
Map **Kanji details** to a note field and place that field below the definitions
in your Anki card template (for example, `{{Kanji}}` for a field named Kanji).
It includes the word's kanji readings, meanings, examples and components available
in your dictionaries, even when collapsed in the popup; missing data stays blank.
Sentence, screenshot and available word recordings are included when mapped.
Hover scan screenshots include the full active screen.
**Anki → Duplicates** can prevent or allow duplicate words. Checks can cover the
current deck, its top-level deck and subdecks, selected decks, or the collection,
optionally across all note types. Selected decks always include the destination.
Duplicates are checked before preparing definitions and media. Existing notes are
not overwritten. If saving times out, check Anki before retrying.
Existing words show a checkmark after a background check using the selected scope.
With **Prevent**, clicking opens matching notes; with **Allow**, it adds another note.

For source installation, custom OCR and release procedures, see
[development notes](DEVELOPMENT.md).
