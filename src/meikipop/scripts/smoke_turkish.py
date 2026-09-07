"""Opt-in actual-model checks; run after dictionary and model setup."""
from unittest.mock import patch

from meikipop.dictionary.turkish_lookup import TurkishLookup
from meikipop.dictionary.turkish_store import TurkishStore, default_dictionary_path
from meikipop.language.stanza_analyzer import StanzaAnalyzer
from meikipop.scripts.turkish import print_json


def main():
    # Setup is explicit. Even model initialization must work without networking.
    with patch("socket.socket.connect", side_effect=AssertionError("Offline smoke check attempted networking")):
        run_checks()


def run_checks():
    # Construct directly: this check must fail if Stanza is unavailable.
    analyzer = StanzaAnalyzer()
    store = TurkishStore(default_dictionary_path())
    try:
        lookup = TurkishLookup(store, "exact")
        lookup.analyzer = analyzer
        lookup.status = analyzer.identity
        cases = [
            ("kitaplarımdan", 0, "kitap"),
            ("gözlükçüler", 0, "gözlükçü"),
            ("Dün kitaplarımdan birini okudum.", 3, "okumak"),
            ("Ankara'ya gittim.", 0, "Ankara"),
            ("Bunu hemen fark etti.", 3, "fark etmek"),
            ("Dün bir mektup yazdım.", 3, "yazmak"),
            ("benzerliği", 0, "benzerlik"),
            ("Benzerliği", 0, "benzerlik"),
            ("BENZERLİĞİ", 0, "benzerlik"),
            ("hayırdır", 0, "hayır"),
        ]
        report = []
        for text, target, expected in cases:
            result = lookup.lookup(text, target)
            words = [e["headword"] for e in result.entries]
            token = result.tokens[target]
            report.append({"text": text, "surface": text[token.start:token.end],
                           "span": [token.start, token.end],
                           "routes": list(dict.fromkeys(m.route for m in result.matches)),
                           "lemma": token.lemma, "entries": words, "passed": expected in words})
        for text, expected in (("cocuk", {"çocuk"}), ("cocugu", {"çocuk"}),
                               ("kisi", {"kişi", "kış"}), ("kitpa", {"kitap"}),
                               ("Icerikleriniz", {"içerik"})):
            result = lookup.lookup(text)
            suggestions = {s.headword for s in result.suggestions}
            span_ok = len(result.tokens) == 1 and (result.tokens[0].start, result.tokens[0].end) == (0, len(text))
            report.append({"text": text, "suggestions": sorted(suggestions),
                           "passed": expected <= suggestions and not result.entries and span_ok})
        print_json(report)
        if not all(r["passed"] for r in report):
            raise SystemExit("Some smoke cases did not resolve; inspect the report above.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
