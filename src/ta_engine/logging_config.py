"""Logging setup in one place. loguru is colorized by default on a TTY."""

from __future__ import annotations

import os
import sys

from loguru import logger


def setup_logging() -> None:
    """Replace loguru's default sink with one we control.

    loguru already colorizes when the sink is a terminal; we keep its built-in
    color scheme and just set the level and a tidy format. Level comes from the
    TA_LOG_LEVEL env var (default INFO).
    """
    logger.remove()  # drop the default handler so we don't double-log
    logger.add(
        sys.stderr,
        level=os.getenv("TA_LOG_LEVEL", "INFO"),
        colorize=True,  # force loguru's built-in colors even if not a TTY
        format=(
            "<green>{time:HH:mm:ss}</green> "
            "<level>{level: <8}</level> "
            "<cyan>{name}</cyan> - <level>{message}</level>"
        ),
    )
