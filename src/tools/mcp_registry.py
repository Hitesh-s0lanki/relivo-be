"""Process-wide cache of tools loaded from user-registered MCP servers."""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.tools import BaseTool

from src.utils.exception_detail import describe_exception

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300.0

ToolLoader = Callable[[Any], Awaitable[list[BaseTool]]]


class McpToolRegistry:
    """
    TTL cache over an MCP tool loader, keyed by server `config_hash`.

    The key is safe to share across users because `config_hash` includes the
    server's secret: two users with the same URL but different credentials hash
    differently and never touch the same entry, while two identical configs
    produce a byte-identical tool set with nothing to leak.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize an empty cache."""
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, list[BaseTool]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.stats = {"hits": 0, "misses": 0}

    def invalidate(self, config_hash: str) -> None:
        """Drop one cached entry, e.g. after a credential rotation."""
        self._cache.pop(config_hash, None)

    def clear(self) -> None:
        """Drop every cached entry."""
        self._cache.clear()
        self._locks.clear()
        self.stats = {"hits": 0, "misses": 0}

    async def get_tools_for_servers(
        self,
        loader: ToolLoader,
        servers: Sequence[Any],
    ) -> list[BaseTool]:
        """
        Return the tools for every server, loading only what is not cached.

        Servers are loaded concurrently and failures are isolated: one dead
        server is logged and skipped so the chat turn still runs.
        """
        groups = await asyncio.gather(*(self._safe_load(loader, server) for server in servers))
        return [tool for group in groups for tool in group]

    async def _safe_load(self, loader: ToolLoader, server: Any) -> list[BaseTool]:
        try:
            return await self._load_one(loader, server)
        except Exception as exc:  # noqa: BLE001 - one bad server must not fail the turn
            logger.warning(
                "Skipping MCP server name=%s after load failure: %s",
                getattr(server, "name", "?"),
                describe_exception(exc),
            )
            return []

    async def _load_one(self, loader: ToolLoader, server: Any) -> list[BaseTool]:
        key = server.config_hash
        cached = self._read(key)
        if cached is not None:
            return cached

        # Single-flight per key so a cold user with concurrent requests opens
        # one connection instead of one per request.
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self._read(key)
            if cached is not None:
                return cached

            self.stats["misses"] += 1
            tools = await loader(server)
            self._cache[key] = (self._clock() + self._ttl, tools)
            logger.info("Loaded MCP tools server=%s count=%s", server.name, len(tools))
            return tools

    def _read(self, key: str) -> list[BaseTool] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, tools = entry
        if expires_at <= self._clock():
            self._cache.pop(key, None)
            return None
        self.stats["hits"] += 1
        return tools


_registry: McpToolRegistry | None = None


def get_tool_registry() -> McpToolRegistry:
    """Return the process-wide MCP tool registry."""
    global _registry

    if _registry is None:
        _registry = McpToolRegistry(ttl_seconds=tool_cache_ttl_seconds())
    return _registry


def tool_cache_ttl_seconds() -> float:
    """Return the configured tool cache TTL."""
    return float(os.getenv("RELIVO_MCP_TOOL_CACHE_TTL", DEFAULT_TTL_SECONDS))
