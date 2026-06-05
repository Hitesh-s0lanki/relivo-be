"""Orchestrator agent definition."""

import os
from functools import lru_cache
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_openai import ChatOpenAI

from src.agents.base_agent import BaseAgent, BaseAgentConfig
from src.tools import get_demo_context

ORCHESTRATOR_AGENT_NAME = "Orchestrator"
DEFAULT_CHAT_MODEL = "gpt-5-mini"
DEFAULT_REASONING_EFFORT = "low"
ORCHESTRATOR_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "orchestrator.md"


@lru_cache(maxsize=1)
def get_orchestrator_agent() -> BaseAgent:
    """Build the Orchestrator agent once per process."""
    if os.getenv("OPENAI_API_KEY"):
        model: ChatOpenAI | FakeListChatModel = build_openai_chat_model()
        tools = [get_demo_context]
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


def warm_orchestrator_agent() -> BaseAgent:
    """Initialize the cached Orchestrator agent during application startup."""
    return get_orchestrator_agent()


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


get_chat_agent = get_orchestrator_agent
