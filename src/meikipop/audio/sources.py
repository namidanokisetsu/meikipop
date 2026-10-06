"""Per-language pronunciation modes and retained local source order."""
from meikipop.config.config import config


def database_path(settings, language):
    return settings.value(f"profiles/{language}/audio_database", config.audio_database_path if language == "ja" else "")


def source_order(settings, language):
    mode = audio_mode(settings, language)
    if mode == "online":
        return ["online", "tts"]
    if mode == "tts":
        return ["tts"]
    return local_source_order(settings, language)


def audio_mode(settings, language):
    saved = settings.value(f"profiles/{language}/audio_mode")
    if saved in ("online", "local", "tts"):
        return saved
    return "local" if database_path(settings, language) else "online"


def local_source_order(settings, language):
    saved = settings.value(f"profiles/{language}/audio_order")
    if saved is not None:
        return saved if isinstance(saved, list) else [saved] if saved else []
    legacy = settings.value(f"profiles/{language}/audio_sources", config.audio_preferred_sources if language == "ja" else "")
    sources = ["db:" + source.strip() for source in legacy.split(",") if source.strip()]
    return list(dict.fromkeys([*sources, "database", "tts"]))


def source_label(source):
    return {"tts": "System voice", "database": "Local recordings", "online": "Online pronunciations"}.get(source, source.removeprefix("db:"))
