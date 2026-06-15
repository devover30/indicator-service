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

def supertrend(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
               period: int = 10, multiplier: float = 3.0) -> float:
    """Supertrend line — latest value.
 
    Built on ATR (from TA-Lib). TA-Lib has no Supertrend, so the band and
    trend recurrence is implemented here. Direction is recoverable from the
    result: the line sits *below* price in an uptrend and *above* it in a
    downtrend.
 
    Note: Supertrend needs a warm-up longer than `period` to stabilise (the
    bands carry state forward), so feed it a generous window — several times
    `period` — not just `period` bars.
    """
    n = len(closes)
    atr = talib.ATR(highs, lows, closes, timeperiod=period)
    hl2 = (highs + lows) / 2.0
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr
 
    start = period  # ATR is NaN before this index
    if n <= start:
        return float("nan")
 
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st = np.full(n, np.nan)
 
    # Seed the first valid bar from the close's position vs the bands.
    final_upper[start] = upper_basic[start]
    final_lower[start] = lower_basic[start]
    if closes[start] <= final_upper[start]:
        st[start] = final_upper[start]   # start in downtrend
    else:
        st[start] = final_lower[start]   # start in uptrend
 
    for i in range(start + 1, n):
        # Carry the final upper band forward unless it tightens or is broken.
        if upper_basic[i] < final_upper[i - 1] or closes[i - 1] > final_upper[i - 1]:
            final_upper[i] = upper_basic[i]
        else:
            final_upper[i] = final_upper[i - 1]
 
        # Same for the final lower band.
        if lower_basic[i] > final_lower[i - 1] or closes[i - 1] < final_lower[i - 1]:
            final_lower[i] = lower_basic[i]
        else:
            final_lower[i] = final_lower[i - 1]
 
        # Flip the line depending on which band the close crosses.
        if st[i - 1] == final_upper[i - 1]:
            st[i] = final_lower[i] if closes[i] > final_upper[i] else final_upper[i]
        else:
            st[i] = final_upper[i] if closes[i] < final_lower[i] else final_lower[i]
 
    return float(st[-1])



# name -> how to call it given the column arrays + request params
def compute_one(req: IndicatorRequest, cols: dict[str, np.ndarray]) -> float:
    if req.name == "sma":
        return sma(cols["close"], req.period)
    if req.name == "rsi":
        return rsi(cols["close"], req.period)
    if req.name == "vwap":
        return vwap(cols["high"], cols["low"], cols["close"], cols["volume"])
    if req.name == "supertrend":
        return supertrend(
            cols["high"], cols["low"], cols["close"],
            period=req.period,
            multiplier=float(req.params.get("multiplier", 3.0)),
        )

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
