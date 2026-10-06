"""One-time migration, before adding or writing any new profile preferences."""

KEYS = ("selection_lookup", "auto_translate_miss")


def migrate(preferences):
    if preferences.value("interaction_version", 0, int) >= 1:
        return
    keys = preferences.allKeys()
    existing = {key.split("/")[1] for key in keys if key.startswith("profiles/") and key.count("/") >= 2}
    if keys:
        existing.update(("ja", "tr"))
        existing.update(preferences.value(key, "ja") for key in ("profile", "source"))
    for profile in existing - {"auto"}:
        for key in KEYS:
            path = f"profiles/{profile}/{key}"
            if not preferences.contains(path):
                preferences.setValue(path, True)
    preferences.setValue("interaction_version", 1)


def enabled(preferences, profile, key):
    return preferences.value(f"profiles/{profile}/{key}", False, bool)
