"""meikipop - Desktop OCR dictionary with multilingual Yomitan lookup."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("meikipop")
except PackageNotFoundError:
    __version__ = "0+unknown"
__author__ = "rtr46"
__license__ = "GPL-3.0"
