"""Engine tests — no Redis needed; we drive on_bar() directly."""

from ta_engine.config import Settings
from ta_engine.engine import Engine
from ta_engine.models import Bar, IndicatorRequest

# A tiny reference so the SMA gate is small and easy to test (lookback = period).
REFERENCE = {
    "sma": {
        "name": "SMA",
        "default_period": 14,
        "lookback_required": True,
        "minimum_candles_formula": "period",
    },
}


def make_engine():
    spec = {"AAPL": [IndicatorRequest("sma", {"period": 3})]}
    return Engine(Settings(), spec, REFERENCE)


def bar(close, ts=0):
    return Bar("AAPL", ts, close, close, close, close, 100)


def test_no_result_until_window_filled():
    eng = make_engine()
    assert eng.on_bar(bar(1, ts=1)) is None
    assert eng.on_bar(bar(2, ts=2)) is None
    # third bar completes the period-3 window
    result = eng.on_bar(bar(3, ts=3))
    assert result is not None
    assert result.values["sma_3"] == 2.0  # mean of 1,2,3


def test_unknown_symbol_ignored():
    eng = make_engine()
    assert eng.on_bar(Bar("TSLA", 1, 1, 1, 1, 1, 1)) is None


def test_window_is_capped_to_lookback():
    eng = make_engine()
    for i in range(10):
        eng.on_bar(bar(i, ts=i))
    assert len(eng.windows["AAPL"]) == 3  # period, not 10


def test_duplicate_timestamp_skipped():
    eng = make_engine()
    eng.on_bar(bar(1, ts=1))
    eng.on_bar(bar(2, ts=2))
    eng.on_bar(bar(3, ts=3))
    # re-sending the same timestamp must not advance the window
    before = len(eng.windows["AAPL"])
    assert eng.on_bar(bar(99, ts=3)) is None
    assert len(eng.windows["AAPL"]) == before
