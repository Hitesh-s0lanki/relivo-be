# tests/test_stream_registry.py
import asyncio

import pytest

from src.utils.stream_registry import InMemoryStreamRegistry


@pytest.mark.asyncio
async def test_register_and_get_status():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    assert await r.get_status("c1") == "active"


@pytest.mark.asyncio
async def test_unregistered_status_is_unknown():
    r = InMemoryStreamRegistry()
    assert await r.get_status("missing") == "unknown"


@pytest.mark.asyncio
async def test_cancel_active_returns_true():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    result = await r.cancel("c1")
    assert result is True
    assert r.is_cancelled("c1") is True


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false():
    r = InMemoryStreamRegistry()
    result = await r.cancel("missing")
    assert result is False


@pytest.mark.asyncio
async def test_is_cancelled_false_before_cancel():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    assert r.is_cancelled("c1") is False


@pytest.mark.asyncio
async def test_replay_returns_chunks_from_cursor():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    await r.publish("c1", "a")
    await r.publish("c1", "b")
    await r.publish("c1", "c")
    assert await r.replay("c1", 0) == ["a", "b", "c"]
    assert await r.replay("c1", 1) == ["b", "c"]
    assert await r.replay("c1", 3) == []


@pytest.mark.asyncio
async def test_has_chunks_false_before_publish():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    assert await r.has_chunks("c1") is False


@pytest.mark.asyncio
async def test_has_chunks_true_after_publish():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    await r.publish("c1", "x")
    assert await r.has_chunks("c1") is True


@pytest.mark.asyncio
async def test_subscribe_receives_published_chunks():
    r = InMemoryStreamRegistry()
    await r.register("c1")

    async def producer():
        await asyncio.sleep(0.01)
        await r.publish("c1", "chunk1")
        await r.publish("c1", "chunk2")
        await r.mark_done("c1")

    chunks = []

    async def consumer():
        async for chunk in r.subscribe("c1"):
            chunks.append(chunk)

    await asyncio.gather(producer(), consumer())
    assert chunks == ["chunk1", "chunk2"]


@pytest.mark.asyncio
async def test_unregister_clears_state():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    await r.publish("c1", "x")
    await r.unregister("c1")
    assert await r.get_status("c1") == "unknown"
    assert await r.has_chunks("c1") is False
    assert r.is_cancelled("c1") is False


@pytest.mark.asyncio
async def test_mark_done_changes_status():
    r = InMemoryStreamRegistry()
    await r.register("c1")
    await r.mark_done("c1")
    assert await r.get_status("c1") == "done"
