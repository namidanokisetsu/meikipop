"""Generate Turkish ranking data for a desktop bundle, outside the source tree."""
from pathlib import Path
import sys


def build(directory):
    from meikipop.language._zeyrek import TurkishAnalyzer
    from meikipop.language.turkish_ranking import FILENAME, write_counts
    path = Path(directory) / FILENAME
    write_counts(path, TurkishAnalyzer(rebuild_ranking=True)._family)
    return path


if __name__ == "__main__":
    build(sys.argv[1])
