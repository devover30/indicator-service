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
from .config import Settings, load_spec, load_lookback_reference, required_lookback
from .models import Bar, IndicatorRequest, IndicatorResult


class Engine:
    def __init__(self, settings: Settings,
                 spec: dict[str, list[IndicatorRequest]],
                 reference: dict[str, dict]):
        self.settings = settings
        self.spec = spec
        self.reference = reference
        # Precompute the lookback each symbol needs (from the reference
        # formulas + actual params), then size its window to match.
        self.needed: dict[str, int] = {}
        self.windows: dict[str, deque[Bar]] = {}
        for symbol, reqs in spec.items():
            n = required_lookback(reqs, reference)
            self.needed[symbol] = n
            self.windows[symbol] = deque(maxlen=max(n, 1))

    def on_bar(self, bar: Bar) -> IndicatorResult | None:
        reqs = self.spec.get(bar.symbol)
        if not reqs:
            return None  # symbol not in spec, ignore

        window = self.windows[bar.symbol]

        # Skip a candle we already have (e.g. a seeded bar that the live feed
        # then republishes) so it isn't double-counted in recursive indicators.
        if window and window[-1].timestamp == bar.timestamp:
            return None

        window.append(bar)

        # not enough history yet to satisfy the largest lookback
        needed = self.needed[bar.symbol]
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
        for symbol in self.spec:
            needed = self.needed[symbol]
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
        channels = [self.settings.candle_channel(sym) for sym in self.spec]
        logger.info("subscribing to {}", channels)
        for bar in redis_io.subscribe_bars(client, channels):
            if self.settings.past_cutoff():
                logger.info(
                    "reached {} IST cutoff — stopping", self.settings.run_until
                )
                return
            result = self.on_bar(bar)
            if result is not None:
                redis_io.publish_result(
                    client,
                    self.settings.results_channel(result.symbol),
                    result,
                )


def build_engine(settings: Settings | None = None) -> tuple[Engine, redis.Redis]:
    settings = settings or Settings()
    reference = load_lookback_reference(settings.lookback_spec_path)
    spec = load_spec(settings.spec_path, reference)
    client = redis_io.connect(settings.redis_url)
    return Engine(settings, spec, reference), client
