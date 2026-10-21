"""Local reading candidates for manual Japanese search; source text stays intact."""
import re
import unicodedata


def kana_candidates(text):
    text = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    if not re.search(r"[a-zāīūēōâîûêô]", text):
        return ()
    from romkan2 import to_hiragana

    candidates = []
    # Long vowels have distinct native and loanword spellings.
    for vowels in (("aa", "ii", "uu", "ei", "ou"),
                   ("aa", "ii", "uu", "ee", "oo"),
                   ("a-", "i-", "u-", "e-", "o-")):
        mapping = dict(zip("āīūēō", vowels)) | dict(zip("âîûêô", vowels))
        expanded = text.translate(str.maketrans(mapping))
        prolonged = re.sub(r"([aiueo])\1|ou", lambda match: match.group(0)[0] + "-", expanded)
        for spelling in dict.fromkeys((expanded, prolonged)):
            kana = re.sub(r"\s+", "", to_hiragana(spelling))
            if re.fullmatch(r"[ぁ-ゖァ-ヺー\u3400-\u9fff々〆0-9]+", kana):
                candidates.append(kana)
    return tuple(dict.fromkeys(candidates))
