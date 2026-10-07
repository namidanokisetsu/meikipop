"""Explicit installation of openly published Yomitan dictionaries."""
from dataclasses import dataclass
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

from .library import import_yomitan, language_code
from meikipop.language.support import DICTIONARY_LANGUAGES
from meikipop.utils.progress import content_length, download_progress


@dataclass(frozen=True)
class RecommendedDictionary:
    title: str
    language: str
    url: str
    website: str


def recommendations(language):
    language = language_code(language)
    if language not in DICTIONARY_LANGUAGES:
        return ()
    if language == "ja":
        return (RecommendedDictionary("Jitendex", "ja",
                "https://github.com/stephenmk/stephenmk.github.io/releases/latest/download/jitendex-yomitan.zip",
                "https://jitendex.org/pages/downloads.html"),)
    return (RecommendedDictionary("Wiktionary · English definitions", language,
            f"https://huggingface.co/datasets/daxida/wty-release/resolve/main/latest/dict/{language}/en/wty-{language}-en.zip?download=true",
            "https://yomidevs.github.io/wiktionary-to-yomitan/download/"),)


def install_recommended(dictionary, directory, progress, cancelled):
    progress(f"Downloading {dictionary.title}…")
    request = Request(dictionary.url, headers={"User-Agent": "Meikipop dictionary installer"})
    with tempfile.TemporaryDirectory(prefix="meikipop-dictionary-") as folder:
        archive = Path(folder) / "dictionary.zip"
        with urlopen(request, timeout=30) as response, archive.open("wb") as output:
            total = 0
            size = content_length(response)
            progress(download_progress(dictionary.title, total, size))
            while chunk := response.read(1024 * 1024):
                if cancelled.is_set():
                    raise InterruptedError("Download cancelled.")
                total += len(chunk)
                if total > 2 * 1024**3:
                    raise ValueError("Dictionary download exceeds 2 GB.")
                output.write(chunk)
                progress(download_progress(dictionary.title, total, size))
        return import_yomitan(archive, directory, language=dictionary.language,
                             progress=progress, cancelled=cancelled.is_set)
