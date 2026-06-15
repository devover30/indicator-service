"""Runtime settings and indicator-spec loading."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .models import IndicatorRequest


@dataclass(frozen=True)
class Settings:
    """Runtime settings, read from the environment with sane local defaults."""

    redis_url: str = os.getenv("TA_REDIS_URL", "redis://localhost:6379/0")
    # Single channel for all symbols; the symbol is carried in each payload.
    candle_channel: str = os.getenv("TA_CANDLE_CHANNEL", "candle:5min")
    results_channel: str = os.getenv("TA_RESULTS_CHANNEL", "indicators:5min")
    spec_path: str = os.getenv("TA_SPEC_PATH", "indicators.json")
    # Channel on which we ask candle-service for historical candles at startup.
    history_request_channel: str = os.getenv(
        "TA_HISTORY_CHANNEL", "candle:history:request"
    )
    history_reply_key: str = os.getenv(
        "TA_HISTORY_REPLY_KEY", "candle:history:reply"
    )
    timeframe: str = os.getenv("TA_TIMEFRAME", "5min")
    history_timeout: float = float(os.getenv("TA_HISTORY_TIMEOUT", "10"))


def load_spec(path: str | Path) -> dict[str, list[IndicatorRequest]]:
    """Parse indicators.json into {symbol: [IndicatorRequest, ...]}.

    Expected shape:
        {"AAPL": [{"name": "sma", "period": 20}, {"name": "vwap"}], ...}
    """
    raw = json.loads(Path(path).read_text())
    spec: dict[str, list[IndicatorRequest]] = {}
    for symbol, entries in raw.items():
        requests = []
        for entry in entries:
            params = dict(entry)
            name = params.pop("name")
            requests.append(IndicatorRequest(name=name, params=params))
        spec[symbol] = requests
    return spec


# Warm-up multiples of `period`. Recursive indicators need more than `period`
# bars before their output is trustworthy; simple ones just need `period`.
_WARMUP = {
    "supertrend": 4,
    "rsi": 3,
}


def lookback(req: IndicatorRequest) -> int:
    """Bars this indicator needs before it yields a stable (non-NaN) value."""
    return req.period * _WARMUP.get(req.name, 1)


def required_lookback(requests: list[IndicatorRequest]) -> int:
    """Largest warm-up-aware lookback across a symbol's indicators."""
    return max((lookback(r) for r in requests), default=1)
