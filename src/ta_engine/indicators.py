"""Pure indicator math. No I/O, no Redis, no state — just numbers in, numbers out.

Each function takes numpy arrays and returns the latest value (a float).
This is the heart of the service and the easiest part to unit-test.
"""

from __future__ import annotations

import numpy as np
import talib

from .models import Bar, IndicatorRequest


def sma(closes: np.ndarray, period: int) -> float:
    return float(talib.SMA(closes, timeperiod=period)[-1])


def rsi(closes: np.ndarray, period: int) -> float:
    return float(talib.RSI(closes, timeperiod=period)[-1])


def vwap(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
         volumes: np.ndarray) -> float:
    """Volume-weighted average price over the supplied window."""
    typical = (highs + lows + closes) / 3.0
    total_vol = volumes.sum()
    if total_vol == 0:
        return float("nan")
    return float((typical * volumes).sum() / total_vol)


# name -> how to call it given the column arrays + request params
def compute_one(req: IndicatorRequest, cols: dict[str, np.ndarray]) -> float:
    if req.name == "sma":
        return sma(cols["close"], req.period)
    if req.name == "rsi":
        return rsi(cols["close"], req.period)
    if req.name == "vwap":
        return vwap(cols["high"], cols["low"], cols["close"], cols["volume"])
    raise ValueError(f"unknown indicator: {req.name!r}")


def columns_from_bars(bars: list[Bar]) -> dict[str, np.ndarray]:
    """Turn a window of bars into column arrays TA-Lib can chew on."""
    return {
        "open": np.array([b.open for b in bars], dtype=float),
        "high": np.array([b.high for b in bars], dtype=float),
        "low": np.array([b.low for b in bars], dtype=float),
        "close": np.array([b.close for b in bars], dtype=float),
        "volume": np.array([b.volume for b in bars], dtype=float),
    }
