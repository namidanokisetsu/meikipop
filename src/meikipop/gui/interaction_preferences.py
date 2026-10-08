"""Opt-in behavior for the selected language profile."""


def enabled(preferences, profile, key):
    return preferences.value(f"profiles/{profile}/{key}", False, bool)
