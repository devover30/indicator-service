"""Entrypoint: `python -m ta_engine` or the `ta-engine` console script."""

from __future__ import annotations

from loguru import logger

from .config import Settings
from .engine import build_engine
from .logging_config import setup_logging


def main() -> None:
    setup_logging()
    settings = Settings()
    if settings.past_cutoff():
        logger.info(
            "started after {} IST cutoff — exiting without running",
            settings.run_until,
        )
        return
    engine, client = build_engine(settings)
    logger.info("ta-engine running — symbols: {}", ", ".join(engine.spec))
    engine.seed_history(client)  # fill windows from candle-service before live
    try:
        engine.run(client)
    except KeyboardInterrupt:
        logger.info("shutting down")


if __name__ == "__main__":
    main()
