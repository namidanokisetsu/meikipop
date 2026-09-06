from functools import lru_cache
from pathlib import Path

from .analyzer import ExactAnalyzer, Token

STANZA_VERSION = "1.14.0"
RESOURCES_VERSION = "1.14.0"
PROCESSORS = {"tokenize": "imst", "mwt": "imst", "pos": "imst_charlm", "lemma": "imst_charlm"}


def default_model_dir():
    from meikipop.utils.paths import paths
    return Path(paths.data_dir) / "languages/tr/stanza" / RESOURCES_VERSION


def setup_models(model_dir=None):
    import stanza
    if stanza.__version__ != STANZA_VERSION:
        raise RuntimeError(f"Install stanza=={STANZA_VERSION} before setting up models")
    stanza.download("tr", model_dir=str(model_dir or default_model_dir()),
                    package=None, processors=PROCESSORS, resources_version=RESOURCES_VERSION)


class StanzaAnalyzer:
    def __init__(self, model_dir=None):
        import stanza
        if stanza.__version__ != STANZA_VERSION:
            raise RuntimeError(f"Expected stanza=={STANZA_VERSION}")
        model_dir = Path(model_dir or default_model_dir()).resolve()
        configuration = ",".join(f"{name}={package}" for name, package in PROCESSORS.items())
        self.identity = f"tr:stanza:{STANZA_VERSION}:{RESOURCES_VERSION}:{configuration}:{model_dir}"
        self.pipeline = stanza.Pipeline(
            "tr", dir=str(model_dir), package=None, processors=PROCESSORS,
            download_method=None, use_gpu=False, verbose=False,
            resources_version=RESOURCES_VERSION,
        )

    @lru_cache(maxsize=32)
    def _document(self, text):
        return self.pipeline(text)

    def diagnostics(self, text):
        return [{"text": token.text, "start": token.start_char, "end": token.end_char,
                 "words": [{key: getattr(word, key, None)
                            for key in ("id", "text", "lemma", "upos", "xpos", "feats")}
                           for word in token.words]}
                for sentence in self._document(text).sentences for token in sentence.tokens]

    @lru_cache(maxsize=32)
    def analyze(self, text):
        doc = self._document(text)
        tokens = []
        source_tokens = ExactAnalyzer().analyze(text)
        seen = set()
        for sentence in doc.sentences:
            for token in sentence.tokens:
                # A multiword expansion has only one selectable original span.
                word = token.words[0]
                if word.upos == "PUNCT":
                    continue
                start, end = token.start_char, token.end_char
                # Stanza can split an OCR word (cocugu -> cocug + u), even across sentences.
                for source in source_tokens:
                    if source.start <= start and end <= source.end:
                        start, end = source.start, source.end
                        break
                if (start, end) not in seen:
                    tokens.append(Token(start, end, word.lemma or token.text, word.upos))
                    seen.add((start, end))
        return tuple(tokens)
