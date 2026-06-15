"""The only module that knows Redis exists. Handles transport + (de)serialize.

Swap the guts of this file to change brokers; nothing else needs to move.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

import redis
from loguru import logger

from .models import Bar, IndicatorResult


def connect(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        # Block forever waiting for pub/sub messages (don't time out when idle).
        socket_timeout=None,
        # Keep the connection alive and detect dead ones.
        socket_keepalive=True,
        health_check_interval=30,
    )


def _bar_from_dict(d: dict) -> Bar:
    return Bar(
        symbol=d["symbol"],
        timestamp=d["timestamp"],  # pass through as-is (ISO string or epoch)
        open=float(d["open"]),
        high=float(d["high"]),
        low=float(d["low"]),
        close=float(d["close"]),
        volume=float(d["volume"]),
    )


def decode_bar(payload: str) -> Bar:
    """All symbols share one channel, so the symbol comes from the payload."""
    return _bar_from_dict(json.loads(payload))


def request_history(client: redis.Redis, request_channel: str, reply_key: str,
                    symbol: str, count: int, timeframe: str,
                    timeout: float = 10.0) -> list[Bar]:
    """Ask candle-service for the last `count` candles and block for the reply.

    Protocol (candle-service must honour this):
      1. We publish a JSON request to `request_channel`:
         {"symbol", "count", "timeframe", "reply_to"}  (reply_to == reply_key)
      2. candle-service RPUSHes ONE item to `reply_key`: a JSON array of candle
         objects, oldest first, then sets a short TTL on the key.
      3. We BLPOP that key (so there's no subscribe-before-publish race).

    The reply key is fixed (no UUID); since seeding is sequential we just clear
    any stale leftover before each request. Returns candles oldest-first, or []
    if nothing came back in time.
    """
    client.delete(reply_key)  # drop any stale reply from a timed-out request
    request = json.dumps({
        "symbol": symbol,
        "count": count,
        "timeframe": timeframe,
        "reply_to": reply_key,
    })
    client.publish(request_channel, request)

    item = client.blpop(reply_key, timeout=timeout)
    if item is None:
        return []  # candle-service didn't answer in time
    _key, payload = item
    candles = json.loads(payload)  # expect a JSON array of candle dicts
    bars = [_bar_from_dict(c) for c in candles]
    # safety: ignore anything that isn't the symbol we asked for
    return [b for b in bars if b.symbol == symbol]


def encode_result(result: IndicatorResult) -> str:
    return json.dumps({
        "symbol": result.symbol,
        "timestamp": result.timestamp,
        "values": result.values,
    })


def subscribe_bars(client: redis.Redis, channel: str) -> Iterator[Bar]:
    """Yield bars from the candle channel, surviving idle timeouts and drops.

    A read timeout while idle is normal (no message arrived) — we just keep
    waiting. If the connection actually drops, we back off and resubscribe.
    """
    while True:
        pubsub = client.pubsub()
        try:
            pubsub.subscribe(channel)
            for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                yield decode_bar(message["data"])
        except redis.exceptions.TimeoutError:
            # No message within the socket timeout window — keep listening.
            continue
        except redis.exceptions.ConnectionError as exc:
            logger.warning("redis connection lost ({}); reconnecting in 5s", exc)
            time.sleep(5)
            continue
        finally:
            try:
                pubsub.close()
            except Exception:
                pass


def publish_result(client: redis.Redis, channel: str,
                   result: IndicatorResult) -> None:
    client.publish(channel, encode_result(result))
