"""Small AnkiConnect v6 adapter; requests are explicit and never retried."""
from dataclasses import dataclass, field
from html import escape
import base64
import hashlib
import http.client
import ipaddress
import json
import socket
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from meikipop.dictionary.metadata import harmonic_rank
from meikipop.dictionary.pitch import morae, render_pitches
from meikipop.utils.timing import mark

DEFAULT_ENDPOINT = "http://127.0.0.1:8765"
DUPLICATE_ACTIONS = {"prevent": "Prevent", "allow": "Allow"}
DUPLICATE_SCOPES = {"deck": "Current deck", "deckroot": "Deck tree", "decks": "Selected decks",
                    "collection": "Collection"}
FIELD_SOURCES = {
    "": "Skip", "expression": "Word", "reading": "Reading",
    "glossary-first": "glossary-first", "glossary": "glossary",
    "popup-selection-text": "popup-selection-text",
    "kanji-details": "Kanji details",
    "sentence": "Sentence", "source": "Dictionary", "frequency": "Frequency",
    "pitch": "Pitch accent", "language": "Language",
    "sentence_furigana": "Sentence furigana", "sentence_translation": "Sentence translation",
    "picture": "Screenshot", "word_audio": "Word audio",
    "pitch_positions": "Pitch positions", "pitch_categories": "Pitch categories",
}

FIELD_ALIASES = {
    "expression": ("word", "expression", "term", "vocabulary", "headword", "front"),
    "reading": ("reading", "kana", "pronunciation", "wordreading"),
    "glossary-first": ("glossaryfirst", "firstdefinition"),
    "glossary": ("definition", "glossary", "meaning", "back"),
    "popup-selection-text": ("popupselectiontext", "chosendefinition"),
    "kanji-details": ("kanji", "kanjidetails", "kanjibreakdown"),
    "sentence": ("sentence", "examplesentence", "context"),
    "sentence_furigana": ("sentencefurigana", "furiganasentence", "contextfurigana"),
    "sentence_translation": ("sentencetranslation", "translation", "translatedsentence"),
    "picture": ("picture", "screenshot", "image"),
    "word_audio": ("wordaudio", "expressionaudio", "vocabularyaudio", "audio"),
    "source": ("source", "dictionary"),
    "frequency": ("frequency", "frequencies", "freqsort", "frequencyrank"),
    "pitch": ("pitch", "pitchaccent", "pitchaccents"),
    "pitch_positions": ("pitchpositions", "pitchposition"),
    "pitch_categories": ("pitchcategories", "pitchcategory"),
    "language": ("language",),
}


def suggest_fields(fields):
    def normalized(value):
        return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())
    aliases = {normalized(alias): source for source, names in FIELD_ALIASES.items() for alias in names}
    result = {}
    for field_name in fields:
        name = normalized(field_name)
        source = aliases.get(name, "")
        if not source and len(name) >= 5:
            scores = sorted(((max(SequenceMatcher(None, name, normalized(alias)).ratio() for alias in names), key)
                             for key, names in FIELD_ALIASES.items()), reverse=True)
            if scores[0][0] >= .86 and scores[0][0] - scores[1][0] >= .08:
                source = scores[0][1]
        result[field_name] = source
    return result


@dataclass(frozen=True)
class AnkiSettings:
    enabled: bool = False
    endpoint: str = DEFAULT_ENDPOINT
    api_key: str = ""
    deck: str = ""
    model: str = ""
    fields: dict = field(default_factory=dict)
    tags: tuple = ("meikipop",)
    duplicate_action: str = "prevent"
    duplicate_scope: str = "deck"
    duplicate_decks: tuple = ()
    check_all_models: bool = False


def load_settings(settings, profile):
    prefix = f"profiles/{profile}/anki/"
    try:
        fields = json.loads(settings.value(prefix + "fields", "{}"))
        if not isinstance(fields, dict):
            fields = {}
    except (ValueError, TypeError):
        fields = {}
    try:
        decks = json.loads(settings.value(prefix + "duplicate_decks", "[]"))
        if not isinstance(decks, list) or not all(isinstance(deck, str) for deck in decks):
            decks = []
    except (ValueError, TypeError):
        decks = []
    return AnkiSettings(settings.value(prefix + "enabled", False, bool),
                        settings.value(prefix + "endpoint", DEFAULT_ENDPOINT),
                        settings.value(prefix + "api_key", ""), settings.value(prefix + "deck", ""),
                        settings.value(prefix + "model", ""), fields,
                        tuple(settings.value(prefix + "tags", "meikipop").split()),
                        settings.value(prefix + "duplicate_action", "prevent"),
                        settings.value(prefix + "duplicate_scope", "deck"), tuple(decks),
                        settings.value(prefix + "check_all_models", False, bool))


def endpoint_address(endpoint):
    url = urlsplit(endpoint)
    host = url.hostname or ""
    try:
        local = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if (url.scheme != "http" or not local or url.username or url.password
            or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("Use a local AnkiConnect address, such as http://127.0.0.1:8765.")
    return "127.0.0.1" if host == "localhost" else host, url.port or 8765


class AnkiClient:
    def __init__(self, settings):
        self.settings = settings
        self.address = endpoint_address(settings.endpoint)
        self._checked_expression = None

    def call(self, action, **params):
        mark("anki_request_begin", action=action)
        body = dict(action=action, version=6, params=params)
        if self.settings.api_key:
            body["key"] = self.settings.api_key
        connection = http.client.HTTPConnection(*self.address, timeout=5)
        writing = action == "addNote"
        try:
            connection.request("POST", "/", json.dumps(body, ensure_ascii=False).encode("utf-8"),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 2 * 1024 * 1024:
                raise ValueError("Unexpected AnkiConnect response.")
            result = json.loads(raw)
            if not isinstance(result, dict) or "result" not in result or "error" not in result:
                raise ValueError("Invalid AnkiConnect response.")
        except (OSError, socket.timeout, http.client.HTTPException, ValueError) as error:
            if writing:
                raise ValueError("Anki did not confirm the save. Check Anki before retrying.") from error
            raise ValueError("Cannot reach AnkiConnect. Open Anki and check the add-on and address.") from error
        finally:
            connection.close()
            mark("anki_request_end", action=action)
        if result["error"] is not None:
            raise ValueError(f'Anki: {result["error"]}')
        return result["result"]

    def names(self, action, **params):
        names = self.call(action, **params)
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError("Invalid AnkiConnect list.")
        return names

    def catalog(self):
        version = self.call("version")
        if type(version) is not int or version < 6:
            raise ValueError("Update AnkiConnect to support API version 6.")
        return self.names("deckNames"), self.names("modelNames")

    def existing_notes(self, expressions):
        """Find exact first-field duplicates with Anki's indexed native search."""
        settings = self.settings
        models = self.call("modelNamesAndIds")
        if (not isinstance(models, dict) or settings.model not in models
                or any(type(value) is not int or value <= 0 for value in models.values())):
            raise ValueError("Invalid Anki note types.")
        model_ids = tuple(models.values()) if settings.check_all_models else (models[settings.model],)
        scope = ""
        if settings.duplicate_scope != "collection":
            decks = self.call("deckNamesAndIds")
            if not isinstance(decks, dict) or any(type(value) is not int or value <= 0 for value in decks.values()):
                raise ValueError("Invalid Anki decks.")
            names = {settings.deck, *settings.duplicate_decks} if settings.duplicate_scope == "decks" else {settings.deck}
            if settings.duplicate_scope == "deckroot":
                root = settings.deck.split("::")[0]
                names = {name for name in decks if name == root or name.startswith(root + "::")}
            ids = [str(value) for name, value in decks.items() if name in names]
            if not ids:
                return {}
            scope = "did:" + ",".join(ids) + " "
        expressions = tuple(dict.fromkeys(expressions))
        actions = []
        for expression in expressions:
            text = escape(expression).replace("\\", "\\\\").replace('"', '\\"')
            query = scope + "(" + " or ".join(f'"dupe:{model_id},{text}"' for model_id in model_ids) + ")"
            action = dict(action="findNotes", version=6, params=dict(query=query))
            if settings.api_key:
                action["key"] = settings.api_key
            actions.append(action)
        if not actions:
            return {}
        results = self.call("multi", actions=actions)
        if not isinstance(results, list) or len(results) != len(expressions):
            raise ValueError("Invalid Anki duplicate response.")
        found = {}
        for expression, result in zip(expressions, results):
            if not isinstance(result, dict) or result.get("error") is not None:
                raise ValueError("Anki duplicate lookup failed.")
            ids = result.get("result")
            if not isinstance(ids, list) or any(type(value) is not int or value <= 0 for value in ids):
                raise ValueError("Invalid Anki note IDs.")
            if ids:
                found[expression] = tuple(dict.fromkeys(ids))
        return found

    def _duplicate_options(self, deck=None, scope=None):
        settings = self.settings
        deck, scope = deck or settings.deck, scope or settings.duplicate_scope
        options = dict(allowDuplicate=settings.duplicate_action == "allow",
                       duplicateScope="collection" if scope == "collection" else "deck",
                       duplicateScopeOptions=dict(checkAllModels=settings.check_all_models))
        if scope != "collection":
            options["duplicateScopeOptions"].update(
                deckName=deck.split("::")[0] if scope == "deckroot" else deck,
                checkChildren=scope == "deckroot")
        return options

    def _note(self, values):
        settings = self.settings
        return dict(deckName=settings.deck, modelName=settings.model,
                    fields={name: values.get(source, "") for name, source in settings.fields.items() if source},
                    tags=list(settings.tags), options=self._duplicate_options())

    def check(self, expression):
        """Validate the mapping and duplicates before preparing definitions or media."""
        self._checked_expression = None
        settings = self.settings
        if not settings.enabled:
            raise ValueError("Enable Anki in Settings first.")
        if not settings.deck or not settings.model:
            raise ValueError("Choose an Anki deck and note type.")
        if settings.duplicate_action not in DUPLICATE_ACTIONS or settings.duplicate_scope not in DUPLICATE_SCOPES:
            raise ValueError("Choose valid Anki duplicate settings.")
        fields = self.names("modelFieldNames", modelName=settings.model)
        if not fields or settings.fields.get(fields[0]) != "expression":
            raise ValueError("Map the first Anki field to Word for duplicate checks.")
        if any(name not in fields for name in settings.fields):
            raise ValueError("Anki fields changed. Reload them in Settings.")
        if any(source not in FIELD_SOURCES for source in settings.fields.values()):
            raise ValueError("Choose valid Anki field mappings in Settings.")
        if not expression:
            raise ValueError("Choose a word to add.")
        if settings.duplicate_action == "prevent":
            decks = tuple(dict.fromkeys((settings.deck, *settings.duplicate_decks))) if settings.duplicate_scope == "decks" else (settings.deck,)
            notes = []
            for deck in decks:
                note = self._note({"expression": expression})
                note.update(deckName=deck, options=self._duplicate_options(deck, "deck")
                            if settings.duplicate_scope == "decks" else self._duplicate_options())
                notes.append(note)
            results = self.call("canAddNotesWithErrorDetail", notes=notes)
            if (not isinstance(results, list) or len(results) != len(notes)
                    or any(not isinstance(item, dict) or type(item.get("canAdd")) is not bool for item in results)):
                raise ValueError("Invalid Anki duplicate-check response.")
            for deck, result in zip(decks, results):
                if not result["canAdd"]:
                    detail = result.get("error") or "Cannot add this note."
                    location = f" ({deck})" if settings.duplicate_scope == "decks" else ""
                    raise ValueError(f"Anki{location}: {detail}")
        self._checked_expression = expression

    def add(self, values):
        expression = values.get("expression", "")
        if self._checked_expression != expression:
            self.check(expression)
        self._checked_expression = None
        settings = self.settings
        note = self._note(values)
        # Store media explicitly so a media error cannot silently become card text.
        for source, media in values.get("_media", {}).items():
            targets = [name for name, mapped in settings.fields.items() if mapped == source]
            if not targets:
                continue
            filename = self.call("storeMediaFile", filename=media["filename"],
                                 data=base64.b64encode(media["data"]).decode("ascii"))
            if not isinstance(filename, str) or not filename:
                raise ValueError("Anki did not confirm the media upload.")
            content = (f'<img src="{escape(filename, quote=True)}">' if source == "picture"
                       else f"[sound:{filename}]")
            for target in targets:
                note["fields"][target] = content
        note_id = self.call("addNote", note=note)
        if type(note_id) is not int or note_id <= 0:
            raise ValueError("Anki did not confirm the save. Check Anki before retrying.")
        return note_id


def note_values(entries, sentence="", selection="", translation="", furigana=None, *, converter=None, sources=None):
    entry = entries[0]
    sources = set(FIELD_SOURCES if sources is None else sources)
    glossary_entries = entries if "glossary" in sources else entries[:1] if "glossary-first" in sources else ()
    glossaries = ["".join(f"<div>{gloss}</div>" for gloss in
                         (converter.extract_glosses(list(item.definitions)) if converter else item.glosses()))
                 for item in glossary_entries]
    glossary = "".join(f'<div style="margin:0 0 .5em"><div style="font-size:.75em;'
                       f'font-weight:normal;opacity:.65">{escape(item.source)}</div>{gloss}</div>'
                       for item, gloss in zip(glossary_entries, glossaries)) if "glossary" in sources else ""
    def aligned(content):
        return f'<div class="meikipop-glossary" style="text-align:left;line-height:1.5">{content}</div>'
    rank = harmonic_rank(f for item in entries for f in item.frequencies) if "frequency" in sources else None
    pitches = tuple(dict.fromkeys(p for item in entries for p in item.pitches if p.reading == entry.reading)) if sources.intersection(
        ("pitch_positions", "pitch_categories")) else ()
    positions = tuple(dict.fromkeys(p.position for p in pitches if type(p.position) is int))
    categories = tuple(dict.fromkeys("heiban" if p == 0 else "atamadaka" if p == 1 else
                                    "odaka" if p == len(morae(entry.reading)) else "nakadaka" for p in positions))
    return dict({"glossary-first": aligned(glossaries[0]) if glossaries else "",
                 "popup-selection-text": escape(selection).replace("\n", "<br>")},
                expression=escape(entry.term), reading=escape(entry.reading), glossary=aligned(glossary) if glossary else "",
                sentence=escape(sentence).replace("\n", "<br>"), source=escape(entry.source),
                sentence_furigana=(furigana if furigana is not None else sentence_readings(sentence, entries))
                    if "sentence_furigana" in sources else "",
                sentence_translation=escape(translation).replace("\n", "<br>"),
                pitch_positions=", ".join(map(str, positions)), pitch_categories=", ".join(categories),
                language=escape(entry.language), frequency=str(max(1, round(rank))) if rank is not None else "",
                pitch=render_pitches((p for item in entries for p in item.pitches), native=False) if "pitch" in sources else "")


def sentence_readings(sentence, entries=(), library=None):
    """Anki's base[reading] syntax, using local dictionary matches only."""
    parts, index = [], 0
    while index < len(sentence):
        rest = sentence[index:]
        candidates = [entry for entry in entries if entry.language == "ja" and rest.startswith(entry.term)]
        candidate = max(candidates, key=lambda e: len(e.term), default=None)
        length = len(candidate.term) if candidate else 0
        if library is not None and any("\u3400" <= c <= "\u9fff" or "\U00020000" <= c <= "\U000323af" for c in rest[:1]):
            # Only literal headwords can supply readings without an inflection tokenizer.
            for matched in range(min(25, len(rest)), length, -1):
                matches = library.lookup(rest[:matched], "ja", limit=1, tolerant=False)
                if matches and matches[0].term == rest[:matched]:
                    candidate, length = matches[0], matched
                    break
        if candidate is not None:
            base, reading = sentence[index:index + length], candidate.reading
            has_kanji = any("\u3400" <= c <= "\u9fff" or "\U00020000" <= c <= "\U000323af" for c in base)
            if reading and reading != base and has_kanji:
                parts.append(f" {escape(base)}[{escape(reading)}]")
            else:
                parts.append(escape(base))
            index += length
        else:
            parts.append(escape(sentence[index]))
            index += 1
    return "".join(parts).replace("\n", "<br>")


def media_value(data, extension):
    return dict(filename=f"meikipop-{hashlib.sha256(data).hexdigest()[:24]}.{extension}", data=data)
