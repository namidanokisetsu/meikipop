"""Per-language pronunciation modes and retained local source order."""


def database_path(settings, language):
    return settings.value(f"profiles/{language}/audio_database", "")


def source_order(settings, language):
    saved = settings.value(f"profiles/{language}/audio_priority")
    if saved is not None:
        return saved if isinstance(saved, list) else [saved] if saved else []
    return ["tts", "online"]


def source_label(source):
    return {"tts": "System voice", "database": "Local recordings", "online": "Online pronunciations"}.get(source, source.removeprefix("db:"))
