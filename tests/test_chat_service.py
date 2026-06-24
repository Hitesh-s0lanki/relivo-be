"""Tests for chat service configuration."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.agents.orchestrator import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_REASONING_EFFORT,
    ORCHESTRATOR_AGENT_NAME,
    build_openai_chat_model,
    env_bool,
    load_orchestrator_prompt,
    load_orchestrator_tools,
)
from src.schemas.chat import ChatRequest
from src.services.chat_service import ChatService
from src.tools import (
    DEFAULT_FIRECRAWL_MCP_URL,
    firecrawl_mcp_auth_config,
    firecrawl_mcp_url,
    load_firecrawl_mcp_tools,
)


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


class ToolStreamingAgent:
    """Agent stub that emits one tool call, one tool result, and final text."""

    async def astream_events(self, *_args, **_kwargs):
        yield {
            "type": "updates",
            "data": {
                "model": {
                    "messages": [
                        SimpleNamespace(
                            name="Orchestrator",
                            content="",
                            tool_calls=[
                                {
                                    "id": "call_firecrawl",
                                    "name": "firecrawl_search",
                                    "args": {"query": "Firecrawl MCP Server"},
                                }
                            ],
                        )
                    ]
                }
            },
        }
        yield {
            "type": "updates",
            "data": {
                "tools": {
                    "messages": [
                        SimpleNamespace(
                            name="firecrawl_search",
                            content='{"success": true, "data": {"web": []}}',
                            tool_calls=[],
                        )
                    ]
                }
            },
        }
        yield {
            "type": "messages",
            "data": (
                type("MessageChunk", (), {"content": "Done.", "tool_call_chunks": []})(),
                {"langgraph_node": "model"},
            ),
        }


class FakeConversationPersistence:
    """Fake conversation service that records created messages."""

    def __init__(self) -> None:
        """Initialize captured message storage."""
        self.created_messages = []
        self.created_tool_calls = []
        self.messages = []

    async def create_message(self, conversation_id, payload):
        """Capture the requested persisted message."""
        self.created_messages.append((conversation_id, payload))
        return SimpleNamespace(id="message-id")

    async def list_messages(self, _conversation_id):
        """Return fake conversation messages."""
        return self.messages

    async def create_tool_call(self, conversation_id, message_id, payload):
        """Capture the requested persisted tool call."""
        self.created_tool_calls.append((conversation_id, message_id, payload))
        return SimpleNamespace(id="tool-call-id")


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


def test_firecrawl_mcp_config_uses_env_api_key(monkeypatch) -> None:
    """Firecrawl MCP auth should be configured from environment variables."""
    monkeypatch.delenv("FIRECRAWL_MCP_URL", raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")

    assert firecrawl_mcp_url() == DEFAULT_FIRECRAWL_MCP_URL
    assert firecrawl_mcp_auth_config() == {"headers": {"Authorization": "Bearer fc-test"}}


def test_firecrawl_mcp_url_can_expand_env_api_key(monkeypatch) -> None:
    """Firecrawl MCP URL overrides should support key placeholders."""
    monkeypatch.setenv(
        "FIRECRAWL_MCP_URL",
        "https://mcp.firecrawl.dev/{FIRECRAWL_API_KEY}/v2/mcp",
    )
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")

    assert firecrawl_mcp_url() == "https://mcp.firecrawl.dev/fc-test/v2/mcp"
    assert firecrawl_mcp_auth_config() == {}


@pytest.mark.asyncio
async def test_firecrawl_mcp_tools_skip_default_hosted_url_without_key(monkeypatch) -> None:
    """Hosted Firecrawl MCP should not be called without an API key."""
    monkeypatch.delenv("FIRECRAWL_MCP_URL", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    assert await load_firecrawl_mcp_tools() == []


@pytest.mark.asyncio
async def test_load_orchestrator_tools_keeps_local_tool_when_firecrawl_fails(monkeypatch) -> None:
    """The agent should still start when Firecrawl MCP is temporarily unavailable."""

    async def fail_firecrawl_tools() -> list:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("src.agents.orchestrator.load_firecrawl_mcp_tools", fail_firecrawl_tools)

    tools = await load_orchestrator_tools()

    assert len(tools) == 1
    assert tools[0].name == "get_demo_context"


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


@pytest.mark.asyncio
async def test_stream_chat_persists_tool_calls_for_conversation_thread() -> None:
    """Tool calls from a chat stream should be saved for UUID conversation threads."""
    conversation_id = str(uuid4())
    persistence = FakeConversationPersistence()
    service = ChatService(ToolStreamingAgent(), persistence)

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(user_message="search docs", thread_id=conversation_id)
        )
    ]

    assert any('"toolName": "firecrawl_search"' in event for event in events)
    assert len(persistence.created_messages) == 1

    saved_conversation_id, payload = persistence.created_messages[0]
    assert saved_conversation_id == conversation_id
    assert payload.role == "agent"
    assert payload.text == "Done."
    assert payload.metadata == {"source": "chat_stream", "thread_id": conversation_id}
    assert len(payload.tool_calls) == 1
    assert payload.tool_calls[0].tool_call_id == "call_firecrawl"
    assert payload.tool_calls[0].name == "firecrawl_search"
    assert payload.tool_calls[0].arguments == {"query": "Firecrawl MCP Server"}
    assert payload.tool_calls[0].result == {"success": True, "data": {"web": []}}
    assert payload.tool_calls[0].status == "completed"


@pytest.mark.asyncio
async def test_stream_chat_skips_tool_persistence_for_non_conversation_thread() -> None:
    """Non-UUID thread ids should continue streaming without DB persistence."""
    persistence = FakeConversationPersistence()
    service = ChatService(ToolStreamingAgent(), persistence)

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(user_message="search docs", thread_id="ad-hoc-thread")
        )
    ]

    assert any('"toolName": "firecrawl_search"' in event for event in events)
    assert persistence.created_messages == []


@pytest.mark.asyncio
async def test_stream_chat_attaches_tool_calls_to_existing_agent_message() -> None:
    """Tool calls should attach to an already-saved matching assistant message."""
    conversation_id = str(uuid4())
    persistence = FakeConversationPersistence()
    persistence.messages = [
        SimpleNamespace(id="existing-agent-message", role="agent", text="Done.", tool_calls=[])
    ]
    service = ChatService(ToolStreamingAgent(), persistence)

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(user_message="search docs", thread_id=conversation_id)
        )
    ]

    assert any('"toolName": "firecrawl_search"' in event for event in events)
    assert persistence.created_messages == []
    assert len(persistence.created_tool_calls) == 1

    saved_conversation_id, message_id, payload = persistence.created_tool_calls[0]
    assert saved_conversation_id == conversation_id
    assert message_id == "existing-agent-message"
    assert payload.name == "firecrawl_search"
    assert payload.result == {"success": True, "data": {"web": []}}
