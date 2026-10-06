"""Provider language coverage, independent of installed resources.

Checked 2026-10-06 against:
https://yomidevs.github.io/wiktionary-to-yomitan/release_metadata_yomitan.json
https://huggingface.co/tencent/Hy-MT2-7B#supported-languages
https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html
https://github.com/PaddlePaddle/PaddleOCR/blob/release/3.7/paddleocr/_utils/langs.py
https://raw.githubusercontent.com/stanfordnlp/stanza-resources/main/resources_1.14.0.json
"""
from meikipop.dictionary.translation import MANAGED_LANGUAGES

DICTIONARY_LANGUAGES = frozenset("""
ady af afb aii ajp ang apc ar arz as ast az ba bcl be bg bn bo ca ceb cim cmn cop crh cs csb cu cy
da de dsb dum egy el en enm eo es et eu fa fi fo fr frm fro fy ga gd gem-pro gl gmw-pro goh got grc
gu gv haw he hi hu hy ia id io is it izh ja jv ka kix kk km kmr kn ko kw ky la lb liv lld lo lt lv lzz
mg mi mk ml mn mr ms mt my nb nl nn no non nrf nv oc or ota pa pdt pi pl pt ro rsk ru rup sa sah scn
sco se sga sh sk sl sla-pro sq su sv sw syc ta te tg th tl tr ug uk ur urj-fin-pro uz vec vi vo vot
xcl yi yo yue zh zlw-ocs zlw-opl zu
""".split())
TRANSLATION_LANGUAGES = MANAGED_LANGUAGES | {"zh-hant", "zh-tw", "zh-hk"}
# PP-OCRv6 small: Chinese, English, Japanese and 46 Latin-script languages.
# Pali belongs to the separate v5 Latin model, not the installed v6 model.
PADDLE_LANGUAGES = frozenset("""
af az bs ca cs cy da de en es et eu fi fr ga gl hr hu id is it ja ku la lb lt lv mi ms mt nl no oc
pl pt qu rm ro sk sl sq sr-latn sv sw tl tr uz vi zh zh-hant
""".split()) | {"cmn", "fil", "kmr", "nb", "nn", "zh-hans", "zh-tw", "zh-hk"}
STANZA_LANGUAGES = frozenset("""
ab af ang ar be bg bxr ca cop cs cu cy da de el en es et eu fa fi fr fro ga gd gl got grc gv hbo he
hi hr hsb hu hy hyw id is it ja ka kk kmr ko kpv ky la lij lt lv lzh mr myv nb nds nl nn or orv ota
pcm pl pt qaf qpm qtd ro ru sa sd sk sl sme sq sr sv ta tr ug uk ur wo xcl zh-hans zh-hant
""".split())
STANZA_LANGUAGES |= {"no", "se", "zh"}  # Stanza aliases for nb, sme and zh-hans.
AVAILABLE_LANGUAGES = DICTIONARY_LANGUAGES | TRANSLATION_LANGUAGES
EXTRA_NAMES = {
    "arz": "Egyptian Arabic", "afb": "Gulf Arabic", "apc": "North Levantine Arabic", "ajp": "South Levantine Arabic",
    "xcl": "Old Armenian", "rup": "Aromanian", "aii": "Assyrian Neo-Aramaic", "bcl": "Central Bikol",
    "cmn": "Mandarin Chinese", "cim": "Cimbrian", "crh": "Crimean Tatar", "zlw-ocs": "Old Czech",
    "dum": "Middle Dutch", "egy": "Egyptian", "enm": "Middle English", "ang": "Old English",
    "frm": "Middle French", "fro": "Old French", "goh": "Old High German", "got": "Gothic",
    "grc": "Ancient Greek", "izh": "Ingrian", "sga": "Old Irish", "csb": "Kashubian",
    "kix": "Khiamniungan Naga", "kmr": "Northern Kurdish", "lzz": "Laz", "liv": "Livonian",
    "nrf": "Norman", "no": "Norwegian", "non": "Old Norse", "rsk": "Pannonian Rusyn",
    "pdt": "Plautdietsch", "zlw-opl": "Old Polish", "urj-fin-pro": "Proto-Finnic",
    "gem-pro": "Proto-Germanic", "sla-pro": "Proto-Slavic", "gmw-pro": "Proto-West Germanic",
    "sco": "Scots", "sh": "Serbo-Croatian", "syc": "Classical Syriac", "tl": "Tagalog",
    "ota": "Ottoman Turkish", "vot": "Votic", "ady": "West Circassian",
}


def default_ocr_provider(code, platform=None):
    if platform is None:
        import sys
        platform = sys.platform
    if platform == "darwin":
        return "vision"
    if code == "ja":
        return "meikiocr"
    return "paddle" if code in PADDLE_LANGUAGES else "screenai"


def support_summary(code):
    parts = []
    if code in DICTIONARY_LANGUAGES:
        parts.append("Dictionary")
    if code in TRANSLATION_LANGUAGES:
        parts.append("Translation")
    if code in PADDLE_LANGUAGES:
        parts.append("OCR")
    return " · ".join(parts) or "Imported dictionary"
