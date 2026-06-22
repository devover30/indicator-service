"""Runtime settings and indicator-spec loading."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from .models import IndicatorRequest, canonical_param

# Market timezone — candles carry +05:30, so the daily cutoff is judged in IST
# regardless of where the host runs.
IST = timezone(timedelta(hours=5, minutes=30))

# Load .env BEFORE Settings is defined: the field defaults below call
# os.getenv() at class-definition (import) time, so the file must be read
# first or the values won't be picked up. Real environment variables still
# win — load_dotenv() does not override anything already set in the env.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Runtime settings, read from the environment with sane local defaults."""

    redis_url: str = os.getenv("TA_REDIS_URL", "redis://localhost:6379/0")
    # candle-service now publishes one channel PER symbol, named
    # "<prefix><symbol>" e.g. "candle:5:NSE:NIFTY50-INDEX". The symbol is still
    # carried in each payload too, so decoding is unchanged.
    candle_channel_prefix: str = os.getenv("TA_CANDLE_CHANNEL_PREFIX", "candle:5:")
    # Results are also published one channel PER symbol: "<prefix><symbol>"
    # e.g. "indicators:NSE:NIFTY50-INDEX". The symbol stays in the payload too.
    results_channel_prefix: str = os.getenv("TA_RESULTS_CHANNEL_PREFIX", "indicators:")
    spec_path: str = os.getenv("TA_SPEC_PATH", "indicators.json")
    lookback_spec_path: str = os.getenv(
        "TA_LOOKBACK_PATH", "indicator_lookback.json"
    )
    # Channel on which we ask candle-service for historical candles at startup.
    history_request_channel: str = os.getenv(
        "TA_HISTORY_CHANNEL", "candle:history:request"
    )
    history_reply_key: str = os.getenv(
        "TA_HISTORY_REPLY_KEY", "candle:history:reply"
    )
    timeframe: str = os.getenv("TA_TIMEFRAME", "5min")
    # A gap between consecutive candle timestamps larger than
    # timeframe * max_gap_factor marks a session boundary (overnight / weekend /
    # holiday). Bars across such a gap must not feed range indicators like ATR,
    # or the cross-session price jump is counted as a single-bar True Range.
    max_gap_factor: float = float(os.getenv("TA_MAX_GAP_FACTOR", "1.5"))
    history_timeout: float = float(os.getenv("TA_HISTORY_TIMEOUT", "10"))
    # Daily stop time (HH:MM, IST). The service won't start after this and
    # exits cleanly once the wall clock reaches it while running.
    run_until: str = os.getenv("TA_RUN_UNTIL", "15:00")

    def candle_channel(self, symbol: str) -> str:
        """Per-symbol live channel, e.g. 'candle:5:NSE:NIFTY50-INDEX'."""
        return f"{self.candle_channel_prefix}{symbol}"

    def results_channel(self, symbol: str) -> str:
        """Per-symbol results channel, e.g. 'indicators:NSE:NIFTY50-INDEX'."""
        return f"{self.results_channel_prefix}{symbol}"

    def past_cutoff(self, now: datetime | None = None) -> bool:
        """True once the IST wall clock has reached the daily run_until time."""
        now = (now or datetime.now(IST)).astimezone(IST)
        hour, minute = (int(p) for p in self.run_until.split(":"))
        cutoff = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return now >= cutoff


def resolve_request_defaults(
    req: IndicatorRequest, reference: dict[str, dict]
) -> IndicatorRequest:
    """Fill in a missing scalar period from the reference's default_period.

    The reference is the single source of truth for default periods. The
    lookback side already seeds `period` from default_period when the spec
    omits it (see _formula_vars), so the compute side MUST do the same — or the
    window gets sized for one period (e.g. 14 -> 34 bars) while the math runs
    at another. That mismatch is the silent `period` default of 1 in
    IndicatorRequest.period: an entry like {"name": "atr"} would size a 34-bar
    window but compute a meaningless 1-period ATR (just the latest bar's true
    range). Resolving the default here keeps both sides consistent.

    Only a *scalar* default_period maps to the canonical `period`. Dict
    defaults (MACD, stochastic, ...) name their own variables and are left
    alone. If the spec already gave any period alias (length/timeperiod/n),
    it wins and nothing is injected.
    """
    entry = reference.get(req.name.lower())
    if entry is None:
        return req
    if req.get("period") is not None:
        return req  # spec was explicit; respect it
    default_period = entry.get("default_period")
    if not isinstance(default_period, (int, float)) or isinstance(
        default_period, bool
    ):
        return req  # None or dict default -> no canonical period to inject
    return replace(req, params={**req.params, "period": default_period})


def load_spec(
    path: str | Path, reference: dict[str, dict] | None = None
) -> dict[str, list[IndicatorRequest]]:
    """Parse indicators.json into {symbol: [IndicatorRequest, ...]}.

    Expected shape:
        {"AAPL": [{"name": "sma", "period": 20}, {"name": "vwap"}], ...}

    If `reference` is given, any indicator whose spec entry omits a period
    inherits the reference's default_period, so compute and lookback agree.
    """
    raw = json.loads(Path(path).read_text())
    spec: dict[str, list[IndicatorRequest]] = {}
    for symbol, entries in raw.items():
        requests = []
        for entry in entries:
            params = dict(entry)
            name = params.pop("name").lower()  # normalise for matching
            req = IndicatorRequest(name=name, params=params)
            if reference is not None:
                req = resolve_request_defaults(req, reference)
            requests.append(req)
        spec[symbol] = requests
    return spec


def load_lookback_reference(path: str | Path) -> dict[str, dict]:
    """Load indicator_lookback.json into {indicator_name_lower: entry}."""
    raw = json.loads(Path(path).read_text())
    return {entry["name"].lower(): entry for entry in raw["indicators"]}


# Only arithmetic, identifiers, numbers, commas and max/min are allowed in a
# formula. The file is trusted (local config), but we still gate it.
_FORMULA_OK = re.compile(r"^[\w\s+\-*/().,]+$")
_DEFAULT_LOOKBACK = 50  # fallback when an indicator isn't in the reference


def _formula_vars(default_period, params: dict) -> dict:
    """Build the variable namespace for a formula.

    Defaults come from the reference's `default_period` (a scalar means the
    variable is `period`; a dict means its keys are the variable names). Actual
    spec params then override, resolved through aliases (length -> period, ...).
    """
    if isinstance(default_period, dict):
        variables = dict(default_period)
    elif default_period is None:
        variables = {}
    else:
        variables = {"period": default_period}

    for key, value in params.items():
        if isinstance(value, (int, float)):
            variables[canonical_param(key)] = value  # e.g. length -> period
            variables[key.lower()] = value           # also keep original name
    return variables


def _eval_formula(formula: str, variables: dict) -> int:
    if not _FORMULA_OK.match(formula):
        raise ValueError(f"unsafe lookback formula: {formula!r}")
    namespace = {"__builtins__": {}, "max": max, "min": min, **variables}
    return int(eval(formula, namespace))  # noqa: S307 - trusted local config


def lookback(req: IndicatorRequest, reference: dict[str, dict]) -> int:
    """Minimum candles this indicator needs, from the reference formula.

    Falls back to a safe constant if the indicator isn't in the reference.
    Uses the *actual* params, so a smaller `length` yields a smaller lookback.
    """
    entry = reference.get(req.name.lower())
    if entry is None:
        return _DEFAULT_LOOKBACK
    if not entry.get("lookback_required", False):
        return 1  # e.g. VWAP — no historical warm-up needed
    variables = _formula_vars(entry.get("default_period"), req.params)
    return max(1, _eval_formula(entry["minimum_candles_formula"], variables))


def required_lookback(requests: list[IndicatorRequest],
                      reference: dict[str, dict]) -> int:
    """Largest lookback across a symbol's indicators."""
    return max((lookback(r, reference) for r in requests), default=1)
