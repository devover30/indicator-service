"""Lookback computation from the reference formulas + actual params."""

from ta_engine.config import lookback, required_lookback
from ta_engine.models import IndicatorRequest

REFERENCE = {
    "supertrend": {
        "name": "Supertrend", "default_period": 14,
        "lookback_required": True, "minimum_candles_formula": "period + 20",
    },
    "macd": {
        "name": "MACD", "default_period": {"fast": 12, "slow": 26, "signal": 9},
        "lookback_required": True,
        "minimum_candles_formula": "slow + signal + 20",
    },
    "adx": {
        "name": "ADX", "default_period": 14,
        "lookback_required": True, "minimum_candles_formula": "(2 * period) + 20",
    },
    "vwap": {
        "name": "VWAP", "default_period": None,
        "lookback_required": False, "minimum_candles_formula": "0",
    },
    "ichimoku cloud": {
        "name": "Ichimoku Cloud",
        "default_period": {"tenkan": 9, "kijun": 26, "senkou_b": 52},
        "lookback_required": True,
        "minimum_candles_formula": "max(tenkan, kijun, senkou_b) + 48",
    },
}


def test_length_alias_maps_to_period():
    # spec uses `length`, formula uses `period`
    req = IndicatorRequest("supertrend", {"length": 7, "factor": 3})
    assert req.period == 7
    assert req.get("multiplier") == 3
    assert lookback(req, REFERENCE) == 27  # 7 + 20


def test_non_default_reduces_lookback():
    big = IndicatorRequest("supertrend", {"length": 14})
    small = IndicatorRequest("supertrend", {"length": 7})
    assert lookback(small, REFERENCE) < lookback(big, REFERENCE)


def test_defaults_used_when_param_absent():
    # no params -> falls back to the reference default_period (14)
    req = IndicatorRequest("supertrend", {})
    assert lookback(req, REFERENCE) == 34  # 14 + 20


def test_dict_period_formula():
    req = IndicatorRequest("macd", {"slow": 26, "signal": 9})
    assert lookback(req, REFERENCE) == 55  # 26 + 9 + 20


def test_formula_with_arithmetic():
    req = IndicatorRequest("adx", {"period": 14})
    assert lookback(req, REFERENCE) == 48  # (2*14) + 20


def test_max_formula_uses_defaults():
    req = IndicatorRequest("ichimoku cloud", {})
    assert lookback(req, REFERENCE) == 100  # max(9,26,52) + 48


def test_no_lookback_required_returns_one():
    req = IndicatorRequest("vwap", {})
    assert lookback(req, REFERENCE) == 1


def test_unknown_indicator_falls_back():
    req = IndicatorRequest("totally_made_up", {"period": 5})
    assert lookback(req, REFERENCE) >= 1  # safe constant, no crash


def test_required_lookback_is_the_max():
    reqs = [
        IndicatorRequest("supertrend", {"length": 7}),  # 27
        IndicatorRequest("macd", {"slow": 26, "signal": 9}),  # 55
    ]
    assert required_lookback(reqs, REFERENCE) == 55
