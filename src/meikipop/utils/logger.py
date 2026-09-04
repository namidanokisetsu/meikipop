# meikipop/utils/logger.py
import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

from meikipop.config.config import APP_NAME
from meikipop.utils.paths import paths

TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")


def trace(self, message, *args, **kws):
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kws)


logging.Logger.trace = trace

def setup_logging():
    log_formatter = logging.Formatter(
        f"%(asctime)s - [%(levelname)-5s] - [{APP_NAME}] - %(message)s",
        datefmt='%H:%M:%S'
    )

    if sys.stdout is not None:
        handler = logging.StreamHandler(sys.stdout)
    else:
        log_dir = Path(paths.cache_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "meikipop.log",
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
    handler.setFormatter(log_formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # logging.INFO or TRACE_LEVEL_NUM

    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(handler)
