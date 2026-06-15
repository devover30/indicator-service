"""Data shapes passed between modules. No logic here."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Bar:
    """A single OHLCV bar."""

    symbol: str
    timestamp: str | int  # ISO-8601 string or epoch number; passed through
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class IndicatorRequest:
    """One indicator to compute, parsed from the spec."""

    name: str
    params: dict = field(default_factory=dict)

    @property
    def period(self) -> int:
        """Lookback period, or 1 if the indicator doesn't use one."""
        return int(self.params.get("period", 1))

    @property
    def label(self) -> str:
        """Stable key for the result, e.g. 'sma_20'."""
        p = self.params.get("period")
        return f"{self.name}_{p}" if p is not None else self.name


@dataclass(frozen=True)
class IndicatorResult:
    """Computed values for one symbol at one point in time."""

    symbol: str
    timestamp: str | int
    values: dict  # label -> float, e.g. {"sma_20": 191.3, "vwap": 190.8}
