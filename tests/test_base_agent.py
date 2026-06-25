"""Tests for the base LangChain agent harness."""

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.agents import BaseAgent, BaseAgentConfig


def test_base_agent_invokes_and_returns_final_text() -> None:
    """The wrapper should return the final assistant message content."""
    model = FakeListChatModel(responses=["Hello from Relivo"])
    agent = BaseAgent(BaseAgentConfig(model=model))

    result = agent.invoke("Say hello", thread_id="invoke-test")

    assert result == "Hello from Relivo"


def test_base_agent_streams_sync_text_chunks() -> None:
    """The sync stream should yield only assistant text chunks."""
    model = FakeListChatModel(responses=["streamed"])
    agent = BaseAgent(BaseAgentConfig(model=model))

    result = "".join(agent.stream_text("Stream", thread_id="sync-stream-test"))

    assert result == "streamed"


def test_base_agent_streams_raw_agent_events() -> None:
    """The raw stream should expose LangChain event chunks."""
    model = FakeListChatModel(responses=["streamed"])
    agent = BaseAgent(BaseAgentConfig(model=model))

    events = list(agent.stream_events("Stream", thread_id="raw-stream-test"))

    assert {event["type"] for event in events} == {"messages", "updates"}


def test_base_agent_adds_context_to_configurable_runtime() -> None:
    """Trusted context should be available to tools through RunnableConfig."""
    kwargs = BaseAgent._run_kwargs(
        thread_id="thread-1",
        context={"user_id": "user-1", "agent_id": "agent-1", "ignored": "value"},
    )

    assert kwargs["config"]["configurable"] == {
        "thread_id": "thread-1",
        "user_id": "user-1",
        "agent_id": "agent-1",
    }
    assert kwargs["context"] == {"user_id": "user-1", "agent_id": "agent-1", "ignored": "value"}


@pytest.mark.asyncio
async def test_base_agent_streams_async_text_chunks() -> None:
    """The async stream should yield only assistant text chunks."""
    model = FakeListChatModel(responses=["async streamed"])
    agent = BaseAgent(BaseAgentConfig(model=model))

    chunks = [
        chunk async for chunk in agent.astream_text("Stream async", thread_id="async-stream-test")
    ]

    assert "".join(chunks) == "async streamed"
