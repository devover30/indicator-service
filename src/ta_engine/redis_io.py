"""The only module that knows Redis exists. Handles transport + (de)serialize.

Swap the guts of this file to change brokers; nothing else needs to move.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import redis

from .models import Bar, IndicatorResult


def connect(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True)


def decode_bar(payload: str) -> Bar:
    """All symbols share one channel, so the symbol comes from the payload."""
    d = json.loads(payload)
    return Bar(
        symbol=d["symbol"],
        timestamp=int(d["timestamp"]),
        open=float(d["open"]),
        high=float(d["high"]),
        low=float(d["low"]),
        close=float(d["close"]),
        volume=float(d["volume"]),
    )


def encode_result(result: IndicatorResult) -> str:
    return json.dumps({
        "symbol": result.symbol,
        "timestamp": result.timestamp,
        "values": result.values,
    })


def subscribe_bars(client: redis.Redis, channel: str) -> Iterator[Bar]:
    """Yield bars as they arrive on the single candle channel."""
    pubsub = client.pubsub()
    pubsub.subscribe(channel)
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        yield decode_bar(message["data"])


def publish_result(client: redis.Redis, channel: str,
                   result: IndicatorResult) -> None:
    client.publish(channel, encode_result(result))
