"""Entrypoint: `python -m ta_engine` or the `ta-engine` console script."""

from __future__ import annotations

from loguru import logger

from .engine import build_engine
from .logging_config import setup_logging


def main() -> None:
    setup_logging()
    engine, client = build_engine()
    logger.info("ta-engine running — symbols: {}", ", ".join(engine.spec))
    try:
        engine.run(client)
    except KeyboardInterrupt:
        logger.info("shutting down")


if __name__ == "__main__":
    main()
