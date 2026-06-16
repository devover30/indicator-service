"""Data shapes passed between modules. No logic here."""

from __future__ import annotations

from dataclasses import dataclass, field

# Spec authors use domain-friendly names; the code and lookback formulas use
# canonical ones. Map the former to the latter so either spelling works.
PARAM_ALIASES = {
    "length": "period",
    "timeperiod": "period",
    "n": "period",
    "factor": "multiplier",
    "mult": "multiplier",
}


def canonical_param(name: str) -> str:
    """e.g. 'length' -> 'period', 'factor' -> 'multiplier'."""
    return PARAM_ALIASES.get(name.lower(), name.lower())


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

    def get(self, canonical: str, default=None):
        """Read a param by canonical name, honouring aliases.

        get('period') finds 'period', 'length', 'timeperiod', or 'n';
        get('multiplier') finds 'multiplier' or 'factor'.
        """
        for key, value in self.params.items():
            if canonical_param(key) == canonical:
                return value
        return default

    @property
    def period(self) -> int:
        """Lookback period, or 1 if the indicator doesn't use one."""
        return int(self.get("period", 1))

    @property
    def label(self) -> str:
        """Stable key for the result, e.g. 'supertrend_7'."""
        p = self.get("period")
        return f"{self.name}_{p}" if p is not None else self.name


@dataclass(frozen=True)
class IndicatorResult:
    """Computed values for one symbol at one point in time."""

    symbol: str
    timestamp: str | int
    values: dict  # label -> float, e.g. {"sma_20": 191.3, "vwap": 190.8}
