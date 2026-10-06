"""Per-language pronunciation order, including a movable system voice."""
from meikipop.config.config import config


def database_path(settings, language):
    return settings.value(f"profiles/{language}/audio_database", config.audio_database_path if language == "ja" else "")


def source_order(settings, language):
    saved = settings.value(f"profiles/{language}/audio_order")
    if saved is not None:
        return saved if isinstance(saved, list) else [saved] if saved else []
    legacy = settings.value(f"profiles/{language}/audio_sources", config.audio_preferred_sources if language == "ja" else "")
    sources = ["db:" + source.strip() for source in legacy.split(",") if source.strip()]
    return list(dict.fromkeys([*sources, "database", "tts"]))


def source_label(source):
    return {"tts": "System voice", "database": "Any recording"}.get(source, source.removeprefix("db:"))
