"""Lightweight readiness checks for shared lookup."""


def model_available(language):
    if language == "tr":
        from .turkish_analyzer import available
        if available():
            return True
    from .stanza_analyzer import model_available as stanza_available
    return stanza_available(language)
