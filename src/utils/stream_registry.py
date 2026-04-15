"""In-memory SSE stream registry for cancel/resume support.

Single-process only. Swap for Redis-backed implementation for multi-worker deployments.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_DONE_SENTINEL = object()


class InMemoryStreamRegistry:
    """Tracks active SSE streams: cancel events, live queues, and replay buffers."""

    def __init__(self) -> None:
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._buffers: dict[str, list[str]] = {}
        self._status: dict[str, str] = {}

    async def register(self, conv_id: str) -> None:
        """Register a new active stream."""
        self._cancel_events[conv_id] = asyncio.Event()
        self._queues[conv_id] = asyncio.Queue()
        self._buffers[conv_id] = []
        self._status[conv_id] = "active"
        logger.debug("Registered stream for %s", conv_id)

    async def cancel(self, conv_id: str) -> bool:
        """Signal cancellation. Returns True if stream was active."""
        event = self._cancel_events.get(conv_id)
        if event and self._status.get(conv_id) == "active":
            event.set()
            logger.info("Cancelled stream for %s", conv_id)
            return True
        return False

    def is_cancelled(self, conv_id: str) -> bool:
        """Synchronous check — safe to call inside a stream generator."""
        event = self._cancel_events.get(conv_id)
        return event is not None and event.is_set()

    async def mark_done(self, conv_id: str) -> None:
        """Mark the stream as done and unblock any subscriber."""
        self._status[conv_id] = "done"
        queue = self._queues.get(conv_id)
        if queue:
            await queue.put(_DONE_SENTINEL)
        logger.debug("Marked stream done for %s", conv_id)

    async def unregister(self, conv_id: str) -> None:
        """Remove all state for conv_id."""
        self._cancel_events.pop(conv_id, None)
        self._queues.pop(conv_id, None)
        self._buffers.pop(conv_id, None)
        self._status.pop(conv_id, None)
        logger.debug("Unregistered stream for %s", conv_id)

    async def get_status(self, conv_id: str) -> str:
        """Returns 'active', 'done', or 'unknown'."""
        return self._status.get(conv_id, "unknown")

    async def has_chunks(self, conv_id: str) -> bool:
        """True if replay buffer has any chunks."""
        return bool(self._buffers.get(conv_id))

    async def replay(self, conv_id: str, cursor: int) -> list[str]:
        """Return buffered chunks from cursor onward."""
        buf = self._buffers.get(conv_id, [])
        return buf[cursor:]

    async def publish(self, conv_id: str, chunk: str) -> None:
        """Append chunk to replay buffer and broadcast to live subscriber."""
        buf = self._buffers.get(conv_id)
        if buf is not None:
            buf.append(chunk)
        queue = self._queues.get(conv_id)
        if queue:
            await queue.put(chunk)

    async def subscribe(self, conv_id: str) -> AsyncGenerator[str, None]:
        """Async generator; yields live chunks until the stream is done."""
        queue = self._queues.get(conv_id)
        if not queue:
            return
        while True:
            item = await queue.get()
            if item is _DONE_SENTINEL:
                break
            yield item


stream_registry = InMemoryStreamRegistry()
