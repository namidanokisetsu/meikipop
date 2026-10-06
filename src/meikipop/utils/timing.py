"""Opt-in, content-free request traces (MEIKIPOP_TIMING=1 or DEBUG logging)."""
import logging
import os
from time import perf_counter

logger = logging.getLogger("meikipop.timing")
if os.environ.get("MEIKIPOP_TIMING") == "1":
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())
    logger.propagate = False


def mark(stage, request=0, **values):
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("t=%.6f id=%s %s %s", perf_counter(), request, stage,
                     " ".join(f"{key}={value}" for key, value in values.items()))
