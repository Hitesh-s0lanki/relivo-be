"""Tests for per-user agent resolution and tool isolation."""

from types import SimpleNamespace

import pytest
from langchain_core.tools import BaseTool

from src.agents import orchestrator
from src.agents.base_agent import BaseAgent, BaseAgentConfig
from src.tools.mcp_registry import McpToolRegistry


class FakeTool(BaseTool):
    """Minimal tool stand-in."""

    name: str = "tool"
    description: str = "A tool."

    def _run(self, *args, **kwargs) -> str:
        return "ok"


def server(name: str, config_hash: str, *, enabled: bool = True) -> SimpleNamespace:
    """Build a stored-server stand-in."""
    return SimpleNamespace(name=name, config_hash=config_hash, enabled=enabled)


@pytest.fixture(autouse=True)
def isolated_caches(monkeypatch):
    """Give each test a fresh base agent, agent cache, and tool cache."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    orchestrator.clear_agent_cache()

    base = BaseAgent(
        BaseAgentConfig(model=_fake_model(), system_prompt="s", name="Orchestrator"),
        tools=[FakeTool(name="base_tool")],
        checkpointer=orchestrator._shared_checkpointer,
    )
    monkeypatch.setattr(orchestrator, "_orchestrator_agent", base)
    monkeypatch.setattr(orchestrator, "get_tool_registry", McpToolRegistry)
    yield base
    orchestrator.clear_agent_cache()


def _fake_model():
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    return FakeListChatModel(responses=["ok"])


def patch_servers(monkeypatch, by_user: dict[str, list]) -> None:
    """Stub the per-user server lookup."""

    async def load(user_id: str, session) -> list:
        return [s for s in by_user.get(user_id, []) if s.enabled]

    monkeypatch.setattr(orchestrator, "load_user_mcp_servers", load)


def patch_tools(monkeypatch, by_hash: dict[str, list[BaseTool]]) -> None:
    """Stub tool loading so no MCP connection is opened."""
    registry = McpToolRegistry()

    async def loader(target) -> list[BaseTool]:
        return by_hash.get(target.config_hash, [])

    class Service:
        def __init__(self, session) -> None:
            self.load_tools = loader

    monkeypatch.setattr(orchestrator, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(
        "src.services.user_mcp_service.UserMcpService",
        Service,
    )


@pytest.mark.asyncio
async def test_user_without_servers_gets_the_shared_base_agent(monkeypatch, isolated_caches):
    """The common path is unchanged and costs nothing."""
    patch_servers(monkeypatch, {})

    agent = await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert agent is isolated_caches


@pytest.mark.asyncio
async def test_user_with_servers_gets_their_tools_bound(monkeypatch, isolated_caches):
    """A registered server's tools are added on top of the base tools."""
    patch_servers(monkeypatch, {"user_a": [server("meta-ads", "hash-a")]})
    patch_tools(monkeypatch, {"hash-a": [FakeTool(name="mcp__meta-ads__list_campaigns")]})

    agent = await orchestrator.resolve_agent_for_user("user_a", session=object())

    names = [tool.name for tool in agent.tools]
    assert names == ["base_tool", "mcp__meta-ads__list_campaigns"]
    assert agent is not isolated_caches


@pytest.mark.asyncio
async def test_one_users_tools_never_reach_another(monkeypatch, isolated_caches):
    """The whole point: user A's MCP tools are invisible to user B."""
    patch_servers(
        monkeypatch,
        {
            "user_a": [server("meta-ads", "hash-a")],
            "user_b": [server("jira", "hash-b")],
        },
    )
    patch_tools(
        monkeypatch,
        {
            "hash-a": [FakeTool(name="mcp__meta-ads__list_campaigns")],
            "hash-b": [FakeTool(name="mcp__jira__create_issue")],
        },
    )

    agent_a = await orchestrator.resolve_agent_for_user("user_a", session=object())
    agent_b = await orchestrator.resolve_agent_for_user("user_b", session=object())

    names_a = {tool.name for tool in agent_a.tools}
    names_b = {tool.name for tool in agent_b.tools}

    assert "mcp__meta-ads__list_campaigns" in names_a
    assert "mcp__meta-ads__list_campaigns" not in names_b
    assert "mcp__jira__create_issue" in names_b
    assert "mcp__jira__create_issue" not in names_a
    assert agent_a is not agent_b


@pytest.mark.asyncio
async def test_the_shared_base_agent_is_never_mutated(monkeypatch, isolated_caches):
    """Resolving for a user must not add tools to the process-wide agent."""
    patch_servers(monkeypatch, {"user_a": [server("meta-ads", "hash-a")]})
    patch_tools(monkeypatch, {"hash-a": [FakeTool(name="mcp__meta-ads__list_campaigns")]})

    await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert [tool.name for tool in isolated_caches.tools] == ["base_tool"]


@pytest.mark.asyncio
async def test_same_signature_reuses_the_cached_agent(monkeypatch, isolated_caches):
    """A second turn for the same user reuses the built graph."""
    patch_servers(monkeypatch, {"user_a": [server("meta-ads", "hash-a")]})
    patch_tools(monkeypatch, {"hash-a": [FakeTool(name="mcp__meta-ads__t")]})

    first = await orchestrator.resolve_agent_for_user("user_a", session=object())
    second = await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert first is second


@pytest.mark.asyncio
async def test_rotating_a_credential_rebuilds_the_agent(monkeypatch, isolated_caches):
    """A changed config hash produces a different signature and a new graph."""
    servers = {"user_a": [server("meta-ads", "hash-old")]}
    patch_servers(monkeypatch, servers)
    patch_tools(
        monkeypatch,
        {
            "hash-old": [FakeTool(name="mcp__meta-ads__old")],
            "hash-new": [FakeTool(name="mcp__meta-ads__new")],
        },
    )

    before = await orchestrator.resolve_agent_for_user("user_a", session=object())
    servers["user_a"] = [server("meta-ads", "hash-new")]
    after = await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert before is not after
    assert "mcp__meta-ads__new" in {tool.name for tool in after.tools}


@pytest.mark.asyncio
async def test_disabled_servers_are_skipped(monkeypatch, isolated_caches):
    """A disabled server contributes nothing and falls back to the base agent."""
    patch_servers(monkeypatch, {"user_a": [server("meta-ads", "hash-a", enabled=False)]})
    patch_tools(monkeypatch, {"hash-a": [FakeTool(name="mcp__meta-ads__t")]})

    agent = await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert agent is isolated_caches


@pytest.mark.asyncio
async def test_two_users_with_identical_config_share_one_graph(monkeypatch, isolated_caches):
    """Identical config and credentials means a byte-identical tool set."""
    patch_servers(
        monkeypatch,
        {
            "user_a": [server("shared", "hash-same")],
            "user_b": [server("shared", "hash-same")],
        },
    )
    patch_tools(monkeypatch, {"hash-same": [FakeTool(name="mcp__shared__t")]})

    agent_a = await orchestrator.resolve_agent_for_user("user_a", session=object())
    agent_b = await orchestrator.resolve_agent_for_user("user_b", session=object())

    assert agent_a is agent_b


@pytest.mark.asyncio
async def test_all_agents_share_one_checkpointer(monkeypatch, isolated_caches):
    """Thread history must survive a user adding a server mid-conversation."""
    patch_servers(monkeypatch, {"user_a": [server("meta-ads", "hash-a")]})
    patch_tools(monkeypatch, {"hash-a": [FakeTool(name="mcp__meta-ads__t")]})

    agent = await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert agent.checkpointer is isolated_caches.checkpointer


@pytest.mark.asyncio
async def test_no_session_returns_the_base_agent(monkeypatch, isolated_caches):
    """Without a database session there is nothing to resolve."""
    assert await orchestrator.resolve_agent_for_user("user_a", session=None) is isolated_caches


@pytest.mark.asyncio
async def test_missing_user_id_returns_the_base_agent(monkeypatch, isolated_caches):
    """An anonymous turn uses the base tool set."""
    assert await orchestrator.resolve_agent_for_user(None, session=object()) is isolated_caches


@pytest.mark.asyncio
async def test_server_lookup_failure_falls_back_to_base(monkeypatch, isolated_caches):
    """A database error must not cost the user their reply."""

    class BrokenService:
        def __init__(self, session) -> None:
            pass

        async def list_servers(self, user_id: str):
            raise RuntimeError("database is down")

    monkeypatch.setattr("src.services.user_mcp_service.UserMcpService", BrokenService)

    agent = await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert agent is isolated_caches


@pytest.mark.asyncio
async def test_dead_server_falls_back_to_base(monkeypatch, isolated_caches):
    """If every registered server fails to load, the turn still runs."""
    patch_servers(monkeypatch, {"user_a": [server("broken", "hash-broken")]})
    patch_tools(monkeypatch, {})

    agent = await orchestrator.resolve_agent_for_user("user_a", session=object())

    assert agent is isolated_caches


@pytest.mark.asyncio
async def test_agent_cache_is_bounded(monkeypatch, isolated_caches):
    """The LRU evicts so long-running processes do not grow without bound."""
    monkeypatch.setenv("RELIVO_MCP_MAX_CACHED_AGENTS", "2")
    by_user = {f"user_{i}": [server("s", f"hash-{i}")] for i in range(4)}
    patch_servers(monkeypatch, by_user)
    patch_tools(monkeypatch, {f"hash-{i}": [FakeTool(name=f"t{i}")] for i in range(4)})

    for user_id in by_user:
        await orchestrator.resolve_agent_for_user(user_id, session=object())

    assert len(orchestrator._agent_cache) == 2


@pytest.mark.asyncio
async def test_signature_is_order_independent() -> None:
    """The same servers in a different order produce the same cache key."""
    forward = orchestrator.agent_signature([server("a", "h1"), server("b", "h2")])
    reverse = orchestrator.agent_signature([server("b", "h2"), server("a", "h1")])

    assert forward == reverse
