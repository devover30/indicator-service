"""Lookback computation from the reference formulas + actual params."""

import json

from ta_engine.config import (
    lookback,
    required_lookback,
    resolve_request_defaults,
    load_spec,
)
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


# --- default-period resolution (compute side must match the lookback side) ---

ATR_REFERENCE = {
    "atr": {
        "name": "ATR", "default_period": 14,
        "lookback_required": True, "minimum_candles_formula": "period + 20",
    },
    "vwap": {
        "name": "VWAP", "default_period": None,
        "lookback_required": False, "minimum_candles_formula": "0",
    },
    "macd": {
        "name": "MACD", "default_period": {"fast": 12, "slow": 26, "signal": 9},
        "lookback_required": True, "minimum_candles_formula": "slow + signal + 20",
    },
}


def test_missing_period_inherits_reference_default():
    # {"name": "atr"} must resolve to the reference default (14), not 1.
    req = resolve_request_defaults(IndicatorRequest("atr", {}), ATR_REFERENCE)
    assert req.period == 14
    assert req.label == "atr_14"


def test_explicit_period_is_not_overridden():
    req = resolve_request_defaults(
        IndicatorRequest("atr", {"length": 7}), ATR_REFERENCE
    )
    assert req.period == 7  # spec wins over the default


def test_scalar_default_keeps_compute_and_lookback_in_sync():
    # The whole point: window size and timeperiod use the SAME period.
    raw = IndicatorRequest("atr", {})
    resolved = resolve_request_defaults(raw, ATR_REFERENCE)
    assert lookback(resolved, ATR_REFERENCE) == 34  # 14 + 20
    assert resolved.period == 14                      # not the silent 1


def test_none_default_period_left_alone():
    req = resolve_request_defaults(IndicatorRequest("vwap", {}), ATR_REFERENCE)
    assert req.get("period") is None  # vwap has no period; nothing injected


def test_dict_default_period_left_alone():
    req = resolve_request_defaults(IndicatorRequest("macd", {}), ATR_REFERENCE)
    assert req.get("period") is None  # dict defaults name their own vars


def test_unknown_indicator_left_alone():
    req = resolve_request_defaults(IndicatorRequest("nope", {}), ATR_REFERENCE)
    assert req.get("period") is None


def test_load_spec_applies_reference_defaults(tmp_path):
    spec_file = tmp_path / "indicators.json"
    spec_file.write_text(json.dumps({"NSE:BSE-EQ": [{"name": "atr"}]}))
    spec = load_spec(spec_file, ATR_REFERENCE)
    req = spec["NSE:BSE-EQ"][0]
    assert req.period == 14
    assert req.label == "atr_14"


def test_load_spec_without_reference_is_unchanged(tmp_path):
    # Backward compatible: no reference -> no injection (old behaviour).
    spec_file = tmp_path / "indicators.json"
    spec_file.write_text(json.dumps({"NSE:BSE-EQ": [{"name": "atr"}]}))
    spec = load_spec(spec_file)
    assert spec["NSE:BSE-EQ"][0].get("period") is None
