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


# --- session-gap handling (history seeding + live feed) ---

from ta_engine.engine import contiguous_tail, _timeframe_seconds, _to_epoch

FIVE_MIN = 300


def test_timeframe_parsing():
    assert _timeframe_seconds("5min") == 300
    assert _timeframe_seconds("15m") == 900
    assert _timeframe_seconds("1h") == 3600
    assert _timeframe_seconds("garbage") == 300  # safe default


def test_to_epoch_handles_iso_and_epoch():
    assert _to_epoch(1700000000) == 1700000000.0
    assert _to_epoch("2026-06-15T09:15:00+05:30") is not None
    assert _to_epoch("not-a-time") is None


def test_contiguous_tail_drops_pre_gap_bars():
    threshold = _timeframe_seconds("5min") * 1.5  # 450s
    bars = [bar(i, ts=i * FIVE_MIN) for i in range(5)]          # contiguous
    after_gap = 5 * FIVE_MIN + 3 * 86400                        # 3-day holiday gap
    bars += [bar(98, ts=after_gap), bar(99, ts=after_gap + FIVE_MIN)]
    kept = contiguous_tail(bars, threshold)
    assert [b.close for b in kept] == [98, 99]  # only the post-gap session


def test_contiguous_tail_keeps_all_when_contiguous():
    threshold = _timeframe_seconds("5min") * 1.5
    bars = [bar(i, ts=i * FIVE_MIN) for i in range(6)]
    assert contiguous_tail(bars, threshold) == bars


def test_contiguous_tail_unparseable_ts_not_split():
    threshold = 450
    bars = [bar(1, ts="x"), bar(2, ts="y"), bar(3, ts="z")]
    assert contiguous_tail(bars, threshold) == bars  # no basis to split


def test_live_session_gap_resets_window():
    eng = make_engine()  # sma period 3, timeframe default 5min -> 450s threshold
    eng.on_bar(bar(1, ts=0))
    eng.on_bar(bar(2, ts=FIVE_MIN))
    assert eng.on_bar(bar(3, ts=2 * FIVE_MIN)) is not None  # window full
    assert len(eng.windows["AAPL"]) == 3
    # a bar a full day later is a new session: window restarts, no result yet
    assert eng.on_bar(bar(9, ts=2 * FIVE_MIN + 86400)) is None
    assert len(eng.windows["AAPL"]) == 1
