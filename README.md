# ta-engine

A small service that reads OHLCV bars from Redis, computes technical
indicators (SMA, VWAP, RSI, ...), and publishes the results back to Redis.

Pure calculation lives in `indicators.py` and never touches I/O, so it's
trivially testable. `redis_io.py` is the only module that knows Redis exists.
`engine.py` ties them together in the read -> compute -> publish loop.

## Setup

```bash
uv sync                      # install deps from the lock file
uv run python -m ta_engine   # run the service
uv run pytest                # run tests
```

The TA-Lib Python wrapper needs the underlying TA-Lib C library. On recent
versions (0.6.5+) `pip`/`uv` pulls a prebuilt wheel that bundles it. If you're
on a platform without a wheel, install the C library first (e.g.
`brew install ta-lib` on macOS, `apt-get install libta-lib0-dev` on Debian).

## Configuration

`indicators.json` holds the slow-changing spec: which indicators to compute
for which symbol. Edit it there rather than passing indicator params over
Redis every cycle.

Runtime settings (Redis URL, channel prefixes) are read from environment
variables in `config.py`; defaults work for a local Redis. Channels are
per-symbol — bars arrive on `bars:{symbol}` (e.g. `bars:AAPL`) and results are
published to `indicators:{symbol}`. The engine derives the channel list from
the symbols in the spec and subscribes to all of them on one connection.
