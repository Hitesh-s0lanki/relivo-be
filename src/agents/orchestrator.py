"""Orchestrator agent definition."""

import asyncio
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.base_agent import AgentTool, BaseAgent, BaseAgentConfig
from src.tools import (
    get_demo_context,
    load_firecrawl_mcp_tools,
    memory_commit,
    memory_context,
    memory_search,
    memory_supersede,
    read_chat_attachment,
)
from src.tools.mcp_registry import get_tool_registry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ORCHESTRATOR_AGENT_NAME = "Orchestrator"
DEFAULT_CHAT_MODEL = "gpt-5-mini"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_MAX_CACHED_AGENTS = 32
# Bumped when the base tool set changes, so cached per-user agents rebuild.
BASE_AGENT_VERSION = "base@v1"
ORCHESTRATOR_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "orchestrator.md"
logger = logging.getLogger(__name__)
_orchestrator_agent: BaseAgent | None = None
_orchestrator_agent_lock = asyncio.Lock()

# One checkpointer for every agent instance. Conversation history lives here
# keyed by thread_id, so a user who adds an MCP server mid-thread must land on
# the same store rather than a fresh one.
_shared_checkpointer = InMemorySaver()

# LRU of built graphs keyed by tool signature, so a user's agent is built once.
_agent_cache: OrderedDict[tuple[str, ...], BaseAgent] = OrderedDict()
_agent_cache_lock = asyncio.Lock()


def get_orchestrator_agent() -> BaseAgent:
    """Build the Orchestrator agent once per process."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(warm_orchestrator_agent())

    raise RuntimeError("Use `await get_chat_agent()` inside an active event loop.")


async def get_chat_agent() -> BaseAgent:
    """Build the Orchestrator chat agent once per process."""
    return await warm_orchestrator_agent()


async def warm_orchestrator_agent() -> BaseAgent:
    """Initialize the cached Orchestrator agent during application startup."""
    global _orchestrator_agent

    if _orchestrator_agent is not None:
        return _orchestrator_agent

    async with _orchestrator_agent_lock:
        if _orchestrator_agent is None:
            _orchestrator_agent = await build_orchestrator_agent()
        return _orchestrator_agent


async def build_orchestrator_agent() -> BaseAgent:
    """Build the Orchestrator agent."""
    if os.getenv("OPENAI_API_KEY"):
        model: ChatOpenAI | FakeListChatModel = build_openai_chat_model()
        tools = await load_orchestrator_tools()
    else:
        model = FakeListChatModel(
            responses=[
                (
                    "OPENAI_API_KEY is not configured. This is the local demo fallback stream. "
                    "Set OPENAI_API_KEY to stream real model tokens, tool calls, and tool results."
                )
            ]
        )
        tools = []

    return BaseAgent(
        BaseAgentConfig(
            model=model,
            system_prompt=load_orchestrator_prompt(),
            name=ORCHESTRATOR_AGENT_NAME,
        ),
        tools=tools,
        checkpointer=_shared_checkpointer,
    )


async def resolve_agent_for_user(
    user_id: str | None,
    session: "AsyncSession | None",
) -> BaseAgent:
    """
    Return the agent for one user: base tools plus their own MCP tools.

    A user with no enabled MCP servers shares the process-wide base agent, so
    the common path costs nothing. Everyone else gets a graph built from their
    own tool signature and cached under it — no user's tools are ever bound into
    another user's agent.
    """
    base = await warm_orchestrator_agent()
    if not user_id or session is None or not os.getenv("OPENAI_API_KEY"):
        return base

    servers = await load_user_mcp_servers(user_id, session)
    if not servers:
        return base

    signature = agent_signature(servers)
    cached = await _get_cached_agent(signature)
    if cached is not None:
        return cached

    from src.services.user_mcp_service import UserMcpService

    tools = await get_tool_registry().get_tools_for_servers(
        UserMcpService(session).load_tools,
        servers,
    )
    if not tools:
        return base

    agent = BaseAgent(base.config, tools=[*base.tools, *tools], checkpointer=_shared_checkpointer)
    await _store_cached_agent(signature, agent)
    logger.info(
        "Resolved per-user agent user_id=%s servers=%s mcp_tools=%s",
        user_id,
        len(servers),
        len(tools),
    )
    return agent


async def load_user_mcp_servers(user_id: str, session: "AsyncSession") -> list:
    """Return the user's enabled MCP servers, or an empty list on failure."""
    from src.services.user_mcp_service import UserMcpService

    try:
        servers = await UserMcpService(session).list_servers(user_id)
    except Exception as exc:  # noqa: BLE001 - never fail a turn over MCP lookup
        logger.warning("Could not load MCP servers for user_id=%s: %s", user_id, exc)
        return []
    return [server for server in servers if server.enabled]


def agent_signature(servers: list) -> tuple[str, ...]:
    """Build the cache key for a user's tool set."""
    return (BASE_AGENT_VERSION, *sorted(server.config_hash for server in servers))


async def _get_cached_agent(signature: tuple[str, ...]) -> BaseAgent | None:
    async with _agent_cache_lock:
        agent = _agent_cache.get(signature)
        if agent is not None:
            _agent_cache.move_to_end(signature)
        return agent


async def _store_cached_agent(signature: tuple[str, ...], agent: BaseAgent) -> None:
    async with _agent_cache_lock:
        _agent_cache[signature] = agent
        _agent_cache.move_to_end(signature)
        while len(_agent_cache) > max_cached_agents():
            evicted, _ = _agent_cache.popitem(last=False)
            logger.info("Evicted cached agent signature=%s", evicted)


def clear_agent_cache() -> None:
    """Drop every cached per-user agent."""
    _agent_cache.clear()


def max_cached_agents() -> int:
    """Return the maximum number of per-user agent graphs to keep."""
    return int(os.getenv("RELIVO_MCP_MAX_CACHED_AGENTS", DEFAULT_MAX_CACHED_AGENTS))


async def load_orchestrator_tools() -> list[AgentTool]:
    """Load all tools available to the real Orchestrator model."""
    tools: list[AgentTool] = [
        get_demo_context,
        read_chat_attachment,
        memory_context,
        memory_search,
        memory_commit,
        memory_supersede,
    ]
    try:
        tools.extend(await load_firecrawl_mcp_tools())
    except Exception as exc:
        logger.warning("Failed to load Firecrawl MCP tools; continuing without them: %s", exc)
    return tools


def build_openai_chat_model() -> ChatOpenAI:
    """Build the OpenAI chat model with reasoning enabled."""
    return ChatOpenAI(
        model=os.getenv("RELIVO_CHAT_MODEL", DEFAULT_CHAT_MODEL),
        reasoning_effort=os.getenv("RELIVO_CHAT_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
        use_responses_api=env_bool("RELIVO_CHAT_USE_RESPONSES_API", default=True),
    )


def load_orchestrator_prompt() -> str:
    """Load the Orchestrator system prompt."""
    return ORCHESTRATOR_PROMPT_PATH.read_text(encoding="utf-8").strip()


def env_bool(name: str, *, default: bool) -> bool:
    """Read a boolean environment variable."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
