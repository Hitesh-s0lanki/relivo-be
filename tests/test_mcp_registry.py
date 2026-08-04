"""Tests for the MCP tool cache."""

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.tools import BaseTool

from src.tools.mcp_registry import McpToolRegistry


class FakeTool(BaseTool):
    """Minimal tool stand-in."""

    name: str = "tool"
    description: str = "A tool."

    def _run(self, *args, **kwargs) -> str:
        return "ok"


class FakeClock:
    """Manually advanced clock."""

    def __init__(self) -> None:
        """Start at a fixed time."""
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def server(name: str, config_hash: str) -> SimpleNamespace:
    """Build a server stand-in with the fields the registry reads."""
    return SimpleNamespace(name=name, config_hash=config_hash)


def counting_loader(calls: dict[str, int], *, fail: set[str] | None = None, delay: float = 0.0):
    """Build a loader that records how many times each server was fetched."""

    async def loader(target) -> list[BaseTool]:
        calls[target.name] = calls.get(target.name, 0) + 1
        if delay:
            await asyncio.sleep(delay)
        if fail and target.name in fail:
            raise ConnectionError(f"{target.name} is down")
        return [FakeTool(name=f"{target.name}_tool")]

    return loader


@pytest.mark.asyncio
async def test_second_call_is_served_from_cache() -> None:
    """A repeated resolve does not hit the network again."""
    calls: dict[str, int] = {}
    registry = McpToolRegistry()
    target = [server("weather", "hash-1")]

    await registry.get_tools_for_servers(counting_loader(calls), target)
    await registry.get_tools_for_servers(counting_loader(calls), target)

    assert calls == {"weather": 1}
    assert registry.stats == {"hits": 1, "misses": 1}


@pytest.mark.asyncio
async def test_rotated_credentials_bypass_the_cache() -> None:
    """A new config hash is a new entry, so a rotated key is never reused."""
    calls: dict[str, int] = {}
    registry = McpToolRegistry()

    await registry.get_tools_for_servers(counting_loader(calls), [server("weather", "hash-old")])
    await registry.get_tools_for_servers(counting_loader(calls), [server("weather", "hash-new")])

    assert calls == {"weather": 2}


@pytest.mark.asyncio
async def test_expired_entries_reload() -> None:
    """Tools are refetched once the TTL passes."""
    calls: dict[str, int] = {}
    clock = FakeClock()
    registry = McpToolRegistry(ttl_seconds=60.0, clock=clock)
    target = [server("weather", "hash-1")]

    await registry.get_tools_for_servers(counting_loader(calls), target)
    clock.now += 61
    await registry.get_tools_for_servers(counting_loader(calls), target)

    assert calls == {"weather": 2}


@pytest.mark.asyncio
async def test_invalidate_drops_one_entry() -> None:
    """Explicit invalidation forces the next resolve to reload."""
    calls: dict[str, int] = {}
    registry = McpToolRegistry()
    target = [server("weather", "hash-1")]

    await registry.get_tools_for_servers(counting_loader(calls), target)
    registry.invalidate("hash-1")
    await registry.get_tools_for_servers(counting_loader(calls), target)

    assert calls == {"weather": 2}


@pytest.mark.asyncio
async def test_one_dead_server_does_not_break_the_others() -> None:
    """A failing server is skipped while the rest still load."""
    calls: dict[str, int] = {}
    registry = McpToolRegistry()
    servers = [server("weather", "h1"), server("broken", "h2"), server("jira", "h3")]

    tools = await registry.get_tools_for_servers(
        counting_loader(calls, fail={"broken"}),
        servers,
    )

    assert sorted(tool.name for tool in tools) == ["jira_tool", "weather_tool"]


@pytest.mark.asyncio
async def test_failures_are_not_cached() -> None:
    """A server that recovers is picked up on the next turn."""
    calls: dict[str, int] = {}
    registry = McpToolRegistry()
    target = [server("flaky", "h1")]

    assert (
        await registry.get_tools_for_servers(counting_loader(calls, fail={"flaky"}), target) == []
    )
    tools = await registry.get_tools_for_servers(counting_loader(calls), target)

    assert [tool.name for tool in tools] == ["flaky_tool"]


@pytest.mark.asyncio
async def test_concurrent_resolves_load_once() -> None:
    """A cold server hit by parallel requests opens one connection, not five."""
    calls: dict[str, int] = {}
    registry = McpToolRegistry()
    loader = counting_loader(calls, delay=0.05)
    target = [server("weather", "hash-1")]

    await asyncio.gather(*(registry.get_tools_for_servers(loader, target) for _ in range(5)))

    assert calls == {"weather": 1}


@pytest.mark.asyncio
async def test_tools_from_every_server_are_returned() -> None:
    """Each registered server contributes its tools to the turn."""
    registry = McpToolRegistry()
    servers = [server("weather", "h1"), server("jira", "h2")]

    tools = await registry.get_tools_for_servers(counting_loader({}), servers)

    assert sorted(tool.name for tool in tools) == ["jira_tool", "weather_tool"]
