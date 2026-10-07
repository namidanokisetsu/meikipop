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

DEFAULT_ENDPOINT = "http://127.0.0.1:8765"
FIELD_SOURCES = {
    "": "Skip", "expression": "Word", "reading": "Reading", "glossary": "Definition",
    "sentence": "Sentence", "source": "Dictionary", "frequency": "Frequency",
    "pitch": "Pitch accent", "language": "Language",
    "sentence_furigana": "Sentence furigana", "sentence_translation": "Sentence translation",
    "picture": "Screenshot", "word_audio": "Word audio",
    "pitch_positions": "Pitch positions", "pitch_categories": "Pitch categories",
}

FIELD_ALIASES = {
    "expression": ("word", "expression", "term", "vocabulary", "headword", "front"),
    "reading": ("reading", "kana", "pronunciation", "wordreading"),
    "glossary": ("definition", "glossary", "meaning", "chosendefinition", "back"),
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


def load_settings(settings, profile):
    prefix = f"profiles/{profile}/anki/"
    try:
        fields = json.loads(settings.value(prefix + "fields", "{}"))
        if not isinstance(fields, dict):
            fields = {}
    except (ValueError, TypeError):
        fields = {}
    return AnkiSettings(settings.value(prefix + "enabled", False, bool),
                        settings.value(prefix + "endpoint", DEFAULT_ENDPOINT),
                        settings.value(prefix + "api_key", ""), settings.value(prefix + "deck", ""),
                        settings.value(prefix + "model", ""), fields,
                        tuple(settings.value(prefix + "tags", "meikipop").split()))


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

    def call(self, action, **params):
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

    def add(self, values):
        settings = self.settings
        if not settings.enabled:
            raise ValueError("Enable Anki in Settings first.")
        if not settings.deck or not settings.model:
            raise ValueError("Choose an Anki deck and note type.")
        fields = self.names("modelFieldNames", modelName=settings.model)
        if not fields or settings.fields.get(fields[0]) != "expression":
            raise ValueError("Map the first Anki field to Word for duplicate checks.")
        if any(name not in fields for name in settings.fields):
            raise ValueError("Anki fields changed. Reload them in Settings.")
        if any(source not in FIELD_SOURCES for source in settings.fields.values()):
            raise ValueError("Choose valid Anki field mappings in Settings.")
        note = dict(deckName=settings.deck, modelName=settings.model,
                    fields={name: values.get(source, "") for name, source in settings.fields.items() if source},
                    tags=list(settings.tags), options=dict(allowDuplicate=False, duplicateScope="deck",
                    duplicateScopeOptions=dict(deckName=settings.deck, checkChildren=False, checkAllModels=False)))
        if not note["fields"].get(fields[0]):
            raise ValueError("Choose a word to add.")
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


def note_values(entries, sentence="", selection="", translation="", furigana=None):
    entry = entries[0]
    glossary = (escape(selection).replace("\n", "<br>") if selection else
                "".join(f"<div>{gloss}</div>" for item in entries for gloss in item.glosses()))
    rank = harmonic_rank(f for item in entries for f in item.frequencies)
    pitches = tuple(dict.fromkeys(p for item in entries for p in item.pitches if p.reading == entry.reading))
    positions = tuple(dict.fromkeys(p.position for p in pitches if type(p.position) is int))
    categories = tuple(dict.fromkeys("heiban" if p == 0 else "atamadaka" if p == 1 else
                                    "odaka" if p == len(morae(entry.reading)) else "nakadaka" for p in positions))
    return dict(expression=escape(entry.term), reading=escape(entry.reading), glossary=glossary,
                sentence=escape(sentence).replace("\n", "<br>"), source=escape(entry.source),
                sentence_furigana=furigana if furigana is not None else sentence_readings(sentence, entries),
                sentence_translation=escape(translation).replace("\n", "<br>"),
                pitch_positions=", ".join(map(str, positions)), pitch_categories=", ".join(categories),
                language=escape(entry.language), frequency=str(max(1, round(rank))) if rank is not None else "",
                pitch=render_pitches(p for item in entries for p in item.pitches))


def sentence_readings(sentence, entries=(), engine=None):
    """Anki's base[reading] syntax, using local dictionary matches only."""
    parts, index = [], 0
    while index < len(sentence):
        rest = sentence[index:]
        candidates = [entry for entry in entries if entry.language == "ja" and rest.startswith(entry.term)]
        candidate = max(candidates, key=lambda e: len(e.term), default=None)
        length = len(candidate.term) if candidate else 0
        if engine is not None and any("\u3400" <= c <= "\u9fff" or "\U00020000" <= c <= "\U000323af" for c in rest[:1]):
            result = engine.search(rest[:25], source="ja", foreign="ja")
            if result.entries:
                match = result.entries[0]
                matched = result.matched_length
                # Inflected forms need a tokenizer to derive the inflected reading.
                if matched and rest[:matched] == match.term:
                    candidate, length = match, matched
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
