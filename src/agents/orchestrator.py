"""Orchestrator agent definition."""

import asyncio
import logging
import os
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_openai import ChatOpenAI

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

ORCHESTRATOR_AGENT_NAME = "Orchestrator"
DEFAULT_CHAT_MODEL = "gpt-5-mini"
DEFAULT_REASONING_EFFORT = "low"
ORCHESTRATOR_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "orchestrator.md"
logger = logging.getLogger(__name__)
_orchestrator_agent: BaseAgent | None = None
_orchestrator_agent_lock = asyncio.Lock()


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
    )


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
