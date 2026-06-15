# ta-engine

A small service that reads 5-minute OHLCV candles from Redis, computes
technical indicators (SMA, RSI, VWAP, Supertrend), and publishes the results
back to Redis. It pairs with a separate **candle-service** that produces the
candles and serves historical ones for warm-up.

Pure calculation lives in `indicators.py` and never touches I/O, so it's
trivially testable. `redis_io.py` is the only module that knows Redis exists.
`engine.py` ties them together: seed history on startup, then a single
read -> compute -> publish loop.

## Setup

```bash
uv sync             # install deps from the lock file
uv run ta-engine    # run the service
uv run pytest       # run tests
```

The TA-Lib Python wrapper needs the underlying TA-Lib C library. On recent
versions (0.6.5+) `pip`/`uv` pulls a prebuilt wheel that bundles it. If you're
on a platform without a wheel, install the C library first (e.g.
`brew install ta-lib` on macOS, `apt-get install libta-lib0-dev` on Debian).

## How it works

1. **Spec** — `indicators.json` maps each symbol to the indicators to compute.
2. **Seed** — on startup, for each symbol the engine asks candle-service for the
   lookback candles it needs and fills a rolling window (see the contract
   below). If the market just opened or no reply comes, it warms up from the
   live feed instead.
3. **Live** — the engine subscribes to one candle channel, updates the per-symbol
   window as candles arrive, computes the indicators, and publishes results.

All symbols share a single live channel; the symbol is carried in each candle
payload. A candle whose timestamp matches the last one in the window is skipped,
so a seeded candle that the live feed later republishes isn't double-counted.

## Configuration

`indicators.json` holds the slow-changing spec — which indicators to compute
per symbol, with their parameters:

```json
{
  "NSE:NIFTY50-INDEX": [
    { "name": "sma", "period": 20 },
    { "name": "rsi", "period": 14 },
    { "name": "supertrend", "period": 10, "multiplier": 3 }
  ]
}
```

Recursive indicators need a warm-up longer than their `period`; `config.py`
sizes each symbol's window accordingly (`_WARMUP` map). Supertrend(10) needs
~40 candles, RSI(14) ~42.

Runtime settings come from environment variables (defaults in `config.py`):

| Variable               | Default                  | Meaning                              |
|------------------------|--------------------------|--------------------------------------|
| `TA_REDIS_URL`         | `redis://localhost:6379/0` | Redis connection                   |
| `TA_CANDLE_CHANNEL`    | `candle:5min`            | live candles in                      |
| `TA_RESULTS_CHANNEL`   | `indicators:5min`        | results out                          |
| `TA_HISTORY_CHANNEL`   | `candle:history:request` | history request channel              |
| `TA_HISTORY_REPLY_KEY` | `candle:history:reply`   | history reply key (BLPOP target)     |
| `TA_TIMEFRAME`         | `5min`                   | timeframe sent in history requests   |
| `TA_HISTORY_TIMEOUT`   | `10`                     | seconds to wait for a history reply  |
| `TA_SPEC_PATH`         | `indicators.json`        | path to the spec                     |
| `TA_LOG_LEVEL`         | `INFO`                   | loguru level                         |

## candle-service contract (history backfill)

On startup the engine requests historical candles so indicators don't sit at
`nan`. The candle-service (separate process) must:

1. Subscribe to `candle:history:request`. Each request is JSON:
   ```json
   { "symbol": "NSE:NIFTY50-INDEX", "count": 40, "timeframe": "5min",
     "reply_to": "candle:history:reply" }
   ```
2. `RPUSH` one item to the `reply_to` key: a JSON array of candle objects,
   **oldest first**, same shape as live candles
   (`{symbol, open, high, low, close, volume, timestamp}`).
3. Set a short TTL on the reply key afterwards (e.g. `EXPIRE ... 30`) as a
   safety net. The TTL must exceed `TA_HISTORY_TIMEOUT` (10s).

The engine clears the reply key before each request and blocks on `BLPOP`, so
the fixed key is safe for the sequential, one-symbol-at-a-time seeding.

**Constraint:** if the candle-service stores history in Redis with its own TTL,
that TTL must cover at least the largest indicator's lookback duration
(~3.5–4 hours for the defaults above), or hold the whole trading day.

## Candle payload

```json
{ "symbol": "NSE:NIFTY50-INDEX", "open": 23588.4, "high": 23606.75,
  "low": 23588.4, "close": 23603.6, "volume": 0,
  "timestamp": "2026-06-15T09:15:00+05:30" }
```

`timestamp` is passed through untouched (ISO-8601 or epoch). Note VWAP is `nan`
for index symbols, which have zero volume — use it only on instruments with
real volume.
