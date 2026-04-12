import asyncio
import json
import pytest
from src.utils.heartbeat_wrapper import add_heartbeat_to_stream


async def simple_gen(*chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_passthrough_without_heartbeat():
    """Short stream completes before heartbeat interval fires."""
    gen = simple_gen("data: a\n\n", "data: b\n\n")
    results = []
    async for chunk in add_heartbeat_to_stream(gen, interval=10.0):
        results.append(chunk)
    assert results == ["data: a\n\n", "data: b\n\n"]


@pytest.mark.asyncio
async def test_heartbeat_injected_on_delay():
    """Heartbeat fires when generator pauses longer than interval."""
    async def slow_gen():
        yield "data: first\n\n"
        await asyncio.sleep(0.15)  # longer than our test interval
        yield "data: second\n\n"

    results = []
    async for chunk in add_heartbeat_to_stream(slow_gen(), interval=0.1):
        results.append(chunk)

    # first chunk + at least one heartbeat + second chunk
    assert results[0] == "data: first\n\n"
    assert results[-1] == "data: second\n\n"
    heartbeats = [r for r in results if "data-heartbeat" in r]
    assert len(heartbeats) >= 1
    hb_data = json.loads(heartbeats[0].removeprefix("data: ").strip())
    assert hb_data["type"] == "data-heartbeat"
    assert "timestamp" in hb_data["data"]
