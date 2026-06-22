"""Orchestration: read a bar -> update window -> compute spec -> publish.

Holds a warm rolling window per symbol so we don't reload history every cycle.
If Rust owns history and ships a full window each tick instead, you can drop
the `windows` state and compute straight from the incoming payload.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import datetime

from loguru import logger
import redis

from . import indicators, redis_io
from .config import Settings, load_spec, load_lookback_reference, required_lookback
from .models import Bar, IndicatorRequest, IndicatorResult


_TF_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}


def _timeframe_seconds(timeframe: str, default: float = 300.0) -> float:
    """Parse a timeframe like '5min' / '15m' / '1h' into seconds."""
    match = re.fullmatch(r"\s*(\d+)\s*([a-zA-Z]*)\s*", timeframe or "")
    if not match:
        return default
    value = int(match.group(1))
    unit = match.group(2).lower() or "min"
    return value * _TF_UNITS.get(unit, 60)


def _to_epoch(timestamp: str | int | float) -> float | None:
    """Best-effort timestamp -> epoch seconds for gap math only.

    Accepts ISO-8601 strings (with or without offset) and epoch numbers. The
    Bar's own timestamp is never mutated — this is purely to measure spacing.
    Returns None if it can't be parsed, so callers can treat it as 'unknown'.
    """
    if isinstance(timestamp, (int, float)):
        return float(timestamp)
    try:
        return datetime.fromisoformat(timestamp).timestamp()
    except (TypeError, ValueError):
        return None


def contiguous_tail(bars: list[Bar], max_gap_seconds: float) -> list[Bar]:
    """Keep only the most-recent run of bars with no oversized time gap.

    Seeded history can reach back across non-trading gaps (overnight, weekends,
    holidays). Feeding bars from either side of such a gap into a range
    indicator like ATR counts the whole cross-session price jump as one bar's
    True Range, which blows the value up (e.g. an intraday ATR reading in the
    thousands instead of tens). Dropping everything before the last big gap
    keeps the window to the current contiguous session.

    Bars whose timestamps don't parse are treated as contiguous (no basis to
    split on), so this never throws data away on a parse failure.
    """
    if len(bars) < 2:
        return bars
    cut = 0
    for i in range(1, len(bars)):
        prev = _to_epoch(bars[i - 1].timestamp)
        cur = _to_epoch(bars[i].timestamp)
        if prev is None or cur is None:
            continue
        if cur - prev > max_gap_seconds:
            cut = i  # session boundary here; discard everything before it
    return bars[cut:]


class Engine:
    def __init__(self, settings: Settings,
                 spec: dict[str, list[IndicatorRequest]],
                 reference: dict[str, dict]):
        self.settings = settings
        self.spec = spec
        self.reference = reference
        # A gap larger than this (seconds) between consecutive bars is a
        # session boundary, not a missed bar.
        self.max_gap_seconds = (
            _timeframe_seconds(settings.timeframe) * settings.max_gap_factor
        )
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

        # If this bar arrives after a session-sized gap from the last one, the
        # existing window belongs to an earlier session (a holiday/overnight
        # boundary). Drop it so range indicators don't span the gap; the new
        # session warms up fresh.
        if window:
            prev = _to_epoch(window[-1].timestamp)
            cur = _to_epoch(bar.timestamp)
            if prev is not None and cur is not None and cur - prev > self.max_gap_seconds:
                logger.info(
                    "{} session gap ({:.0f}s) — resetting window",
                    bar.symbol, cur - prev,
                )
                window.clear()

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
            # Drop any bars before a session/holiday gap — history can reach
            # back across non-trading periods, and those gaps would otherwise
            # poison range indicators (e.g. ATR) with cross-session jumps.
            kept = contiguous_tail(bars, self.max_gap_seconds)
            if len(kept) < len(bars):
                logger.warning(
                    "{}: dropped {} seed bar(s) before a session gap; "
                    "seeding {} contiguous bar(s)",
                    symbol, len(bars) - len(kept), len(kept),
                )
            bars = kept
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
