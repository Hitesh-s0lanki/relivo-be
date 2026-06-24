"""Tests for chat service configuration."""

import pytest

from src.agents.orchestrator import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_REASONING_EFFORT,
    ORCHESTRATOR_AGENT_NAME,
    build_openai_chat_model,
    env_bool,
    load_orchestrator_prompt,
)
from src.schemas.chat import ChatRequest
from src.services.chat_service import ChatService


class FailingAgent:
    """Agent stub that should not be called."""

    async def astream_events(self, *_args, **_kwargs):
        raise AssertionError("agent should not be called")
        yield


class StreamingAgent:
    """Agent stub that returns one model chunk."""

    def __init__(self) -> None:
        """Initialize the call marker."""
        self.called = False

    async def astream_events(self, *_args, **_kwargs):
        self.called = True
        yield {
            "type": "messages",
            "data": (
                type("MessageChunk", (), {"content": "Planned", "tool_call_chunks": []})(),
                {"langgraph_node": "model"},
            ),
        }


def test_build_openai_chat_model_uses_reasoning_defaults(monkeypatch) -> None:
    """The configured OpenAI model should default to reasoning settings."""
    monkeypatch.delenv("RELIVO_CHAT_MODEL", raising=False)
    monkeypatch.delenv("RELIVO_CHAT_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("RELIVO_CHAT_USE_RESPONSES_API", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    model = build_openai_chat_model()

    assert model.model_name == DEFAULT_CHAT_MODEL
    assert model.reasoning_effort == DEFAULT_REASONING_EFFORT
    assert model.use_responses_api is True


def test_orchestrator_prompt_is_loaded_from_markdown() -> None:
    """The Orchestrator agent should use the markdown prompt file."""
    prompt = load_orchestrator_prompt()

    assert ORCHESTRATOR_AGENT_NAME == "Orchestrator"
    assert "You are Orchestrator" in prompt
    assert "Use tools only when they add useful context" in prompt


def test_build_openai_chat_model_uses_env_overrides(monkeypatch) -> None:
    """The configured OpenAI model should honor environment overrides."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("RELIVO_CHAT_MODEL", "gpt-5")
    monkeypatch.setenv("RELIVO_CHAT_REASONING_EFFORT", "high")
    monkeypatch.setenv("RELIVO_CHAT_USE_RESPONSES_API", "false")

    model = build_openai_chat_model()

    assert model.model_name == "gpt-5"
    assert model.reasoning_effort == "high"
    assert model.use_responses_api is False


def test_env_bool_handles_common_truthy_values(monkeypatch) -> None:
    """Boolean environment parsing should support common truthy strings."""
    monkeypatch.setenv("RELIVO_TEST_BOOL", "yes")

    assert env_bool("RELIVO_TEST_BOOL", default=False) is True


def test_env_bool_uses_default_when_missing(monkeypatch) -> None:
    """Boolean environment parsing should return the provided default when absent."""
    monkeypatch.delenv("RELIVO_TEST_BOOL", raising=False)

    assert env_bool("RELIVO_TEST_BOOL", default=True) is True


@pytest.mark.asyncio
async def test_stream_chat_fast_returns_simple_greeting_without_agent() -> None:
    """Simple greetings should avoid model and tool latency."""
    service = ChatService(FailingAgent())

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(user_message="hello", thread_id="user-123")
        )
    ]

    assert events == [
        'data: {"type": "start", "messageId": "user-123"}\n\n',
        'data: {"type": "text-start", "id": "text-1"}\n\n',
        'data: {"type": "text-delta", "id": "text-1", "delta": "Hello! How can I help?"}\n\n',
        'data: {"type": "text-end", "id": "text-1"}\n\n',
        'data: {"type": "finish"}\n\n',
        "data: [DONE]\n\n",
    ]


@pytest.mark.asyncio
async def test_stream_chat_uses_agent_for_non_greeting() -> None:
    """Non-greeting messages should keep the normal agent path."""
    agent = StreamingAgent()
    service = ChatService(agent)

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(user_message="help me plan", thread_id="user-123")
        )
    ]

    assert agent.called is True
    assert 'data: {"type": "text-delta", "id": "text-1", "delta": "Planned"}\n\n' in events
