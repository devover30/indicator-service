"""Orchestration: read a bar -> update window -> compute spec -> publish.

Holds a warm rolling window per symbol so we don't reload history every cycle.
If Rust owns history and ships a full window each tick instead, you can drop
the `windows` state and compute straight from the incoming payload.
"""

from __future__ import annotations

from collections import defaultdict, deque

from loguru import logger
import redis

from . import indicators, redis_io
from .config import Settings, load_spec, required_lookback
from .models import Bar, IndicatorRequest, IndicatorResult


class Engine:
    def __init__(self, settings: Settings,
                 spec: dict[str, list[IndicatorRequest]]):
        self.settings = settings
        self.spec = spec
        # per-symbol rolling window, capped at the lookback that symbol needs
        self.windows: dict[str, deque[Bar]] = {}
        for symbol, reqs in spec.items():
            maxlen = max(required_lookback(reqs), 1)
            self.windows[symbol] = deque(maxlen=maxlen)

    def on_bar(self, bar: Bar) -> IndicatorResult | None:
        reqs = self.spec.get(bar.symbol)
        logger.info("reqs: {}", reqs)
        if not reqs:
            return None  # symbol not in spec, ignore

        window = self.windows[bar.symbol]
        logger.info("window: {}", window)

        # Skip a candle we already have (e.g. a seeded bar that the live feed
        # then republishes) so it isn't double-counted in recursive indicators.
        if window and window[-1].timestamp == bar.timestamp:
            return None

        window.append(bar)
        logger.info("window: {}", window)

        # not enough history yet to satisfy the largest lookback
        needed = required_lookback(reqs)
        logger.info("needed: {}", needed)
        if len(window) < needed:
            logger.debug(
                "{} warming up: {}/{} bars", bar.symbol, len(window), needed
            )
            return None

        cols = indicators.columns_from_bars(list(window))
        values = {r.label: indicators.compute_one(r, cols) for r in reqs}
        logger.debug("{} computed {}", bar.symbol, values)
        return IndicatorResult(bar.symbol, bar.timestamp, values)

    def seed_history(self, client: redis.Redis) -> None:
        """Before going live, fill each symbol's window from candle-service.

        Requests exactly the lookback each symbol needs. If the market just
        opened (or candle-service returns fewer), we seed what we get and the
        rest warms up from the live feed.
        """
        for symbol, reqs in self.spec.items():
            needed = required_lookback(reqs)
            bars = redis_io.request_history(
                client,
                self.settings.history_request_channel,
                self.settings.history_reply_key,
                symbol,
                needed,
                self.settings.timeframe,
                timeout=self.settings.history_timeout,
            )
            window = self.windows[symbol]
            # keep the most recent `needed`, oldest first so newest ends last
            for bar in bars[-needed:]:
                window.append(bar)
            if len(window) >= needed:
                logger.info("seeded {}: {} candles (ready)", symbol, len(window))
            else:
                logger.warning(
                    "seeded {}: {}/{} candles (will warm up live)",
                    symbol, len(window), needed,
                )

    def run(self, client: redis.Redis) -> None:
        logger.info("subscribing to {}", self.settings.candle_channel)
        for bar in redis_io.subscribe_bars(client, self.settings.candle_channel):
            result = self.on_bar(bar)
            if result is not None:
                redis_io.publish_result(
                    client, self.settings.results_channel, result
                )


def build_engine() -> tuple[Engine, redis.Redis]:
    settings = Settings()
    spec = load_spec(settings.spec_path)
    client = redis_io.connect(settings.redis_url)
    return Engine(settings, spec), client
