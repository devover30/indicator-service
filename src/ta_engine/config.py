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


def required_lookback(requests: list[IndicatorRequest]) -> int:
    """Largest period across a symbol's indicators — how much history to seed."""
    return max((r.period for r in requests), default=1)
