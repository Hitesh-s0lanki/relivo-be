import asyncio
import time
from collections.abc import AsyncGenerator

from src.utils.data_protocol import StreamProtocolBuilder

_SENTINEL = object()


async def add_heartbeat_to_stream(
    generator: AsyncGenerator[str, None],
    interval: float = 10.0,
) -> AsyncGenerator[str, None]:
    """
    Wrap an SSE generator and inject heartbeat events during inactivity.

    If no chunk is yielded for `interval` seconds, a heartbeat SSE event is
    injected to keep the HTTP connection alive. The heartbeat check runs every
    1 second.
    """
    queue: asyncio.Queue = asyncio.Queue()
    last_event_time = [time.monotonic()]  # Use list to allow modification in nested function

    async def _drain_generator():
        try:
            async for chunk in generator:
                await queue.put(chunk)
        finally:
            await queue.put(_SENTINEL)

    async def _heartbeat_monitor():
        # Check every min(interval/2, 0.5) seconds to be responsive
        check_interval = min(interval / 2, 0.5)
        while True:
            await asyncio.sleep(check_interval)
            elapsed = time.monotonic() - last_event_time[0]
            if elapsed >= interval:
                hb = StreamProtocolBuilder.data_custom(
                    "heartbeat",
                    {"timestamp": time.time(), "time_since_last_event": round(elapsed, 2)},
                ).to_sse()
                await queue.put(hb)
                last_event_time[0] = time.monotonic()  # Reset after heartbeat

    gen_task = asyncio.create_task(_drain_generator())
    hb_task = asyncio.create_task(_heartbeat_monitor())

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            last_event_time[0] = time.monotonic()
            yield item
    finally:
        hb_task.cancel()
        gen_task.cancel()
        await asyncio.gather(gen_task, hb_task, return_exceptions=True)
