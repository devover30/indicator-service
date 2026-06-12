"""Indicator math is pure, so tests need nothing but numpy arrays."""

import numpy as np
import pytest

from ta_engine import indicators
from ta_engine.models import Bar, IndicatorRequest


def test_sma_is_mean_of_window():
    closes = np.arange(1.0, 21.0)  # 1..20
    assert indicators.sma(closes, period=20) == pytest.approx(10.5)


def test_vwap_weights_by_volume():
    highs = np.array([10.0, 10.0])
    lows = np.array([10.0, 10.0])
    closes = np.array([10.0, 20.0])
    volumes = np.array([1.0, 3.0])
    # typical prices: 10 and ~13.33, weighted toward the high-volume bar
    result = indicators.vwap(highs, lows, closes, volumes)
    assert result == pytest.approx((10.0 * 1 + (40.0 / 3) * 3) / 4)


def test_vwap_zero_volume_is_nan():
    z = np.zeros(3)
    assert np.isnan(indicators.vwap(z, z, z, z))


def test_compute_one_rejects_unknown():
    with pytest.raises(ValueError):
        indicators.compute_one(IndicatorRequest("nope"), {})


def test_columns_from_bars_shapes():
    bars = [Bar("AAPL", i, 1, 2, 0.5, 1.5, 100) for i in range(3)]
    cols = indicators.columns_from_bars(bars)
    assert cols["close"].tolist() == [1.5, 1.5, 1.5]
    assert len(cols["volume"]) == 3
