import asyncio

import redis
import pytest

from app.core.growing_data2redis import GrowingData2Redis, PacketType

# redis_params fixture is provided by conftest.py


@pytest.fixture
def redis_client(redis_params):
    """Synchronous Redis client for test inspection/cleanup."""
    client = redis.Redis(
        host=redis_params["host"],
        port=redis_params["port"],
        db=redis_params["db"],
        password=redis_params.get("password"),
        decode_responses=True,
    )
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis server is not available")
    return client


class SampleSource:
    """Simple object used as source for GrowingData2Redis write mode."""

    def __init__(self):
        self.value = 0
        self.items = []


def test_write_mode_sends_start_data_end_packets(redis_client, redis_params):
    redis_key = "test:growing_data2redis:stream:write"

    # Clean stream before test
    redis_client.delete(redis_key)

    source = SampleSource()
    source.value = 0
    source.items = []

    uploader = GrowingData2Redis(
        redis_params=redis_params,
        redis_key=redis_key,
        source_object=source,
        property_names=["value", "items"],
    )

    # Initial snapshot (no data yet)
    uploader.reset()

    # Change state after reset so that send_changes() sees new elements
    source.value = 42
    source.items = [1, 2, 3]

    uploader.send_changes()
    uploader.finish()

    # Read all entries from stream
    results = redis_client.xread({redis_key: "0-0"})
    assert results, "Stream should contain entries"

    stream, entries = results[0]
    assert stream == redis_key
    # Expect three packets: START, DATA, END
    assert len(entries) == 3

    types = []
    data_packets = []
    for _, fields in entries:
        types.append(fields.get("type"))
        data_packets.append(fields.get("data"))

    assert types[0] == PacketType.START.value
    assert types[1] == PacketType.DATA.value
    assert types[2] == PacketType.END.value

    # DATA packet should contain serialized fields
    import json as _json

    payload = _json.loads(data_packets[1])
    assert payload["value"] == 42
    assert payload["items_new"] == [1, 2, 3]


def test_async_read_mode_reads_stream_and_trims(redis_client, redis_params):
    redis_key = "test:growing_data2redis:stream:async"

    # Clean stream before test
    redis_client.delete(redis_key)

    # Populate stream synchronously using write-mode uploader
    source = SampleSource()
    source.value = 1
    source.items = ["a", "b"]

    uploader = GrowingData2Redis(
        redis_params=redis_params,
        redis_key=redis_key,
        source_object=source,
        property_names=["value", "items"],
    )
    uploader.reset()
    uploader.send_changes()
    uploader.finish()

    async def _run():
        # Read-mode instance (no source_object/property_names) -> async client
        reader = GrowingData2Redis(
            redis_params=redis_params,
            redis_key=redis_key,
        )

        # Read all entries from the beginning
        entries = await reader.read_stream_from_async(last_id="0-0", block_ms=0, count=10)
        assert entries is not None
        # Expect at least START packet
        start_entry = next(
            (e for e in entries if e[1].get("type") == PacketType.START.value),
            None,
        )
        assert start_entry is not None
        start_id, _ = start_entry

        # Trim stream so everything before START is removed (here it is the first entry)
        await reader.trim_stream_min_id_async(start_id)

        # After trim, reading from 0-0 should still return entries starting from START
        results = redis_client.xread({redis_key: "0-0"})
        assert results
        _, trimmed_entries = results[0]
        # First entry id should be >= start_id
        first_id, _ = trimmed_entries[0]
        assert first_id >= start_id

    asyncio.run(_run())


