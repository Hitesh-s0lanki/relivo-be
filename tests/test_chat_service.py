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
    memory_commit,
    memory_context,
    memory_search,
    memory_supersede,
    read_chat_attachment,
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
        self.prompts = []

    async def astream_events(self, *args, **kwargs):
        self.called = True
        self.prompts.append(args[0])
        self.context = kwargs.get("context")
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

    async def get_conversation(self, conversation_id):
        """Return a fake conversation for runtime context."""
        return SimpleNamespace(id=conversation_id, user_id="user-ctx")


class FakeUserFileLookup:
    """Fake file service that returns model-readable data URLs."""

    def __init__(self) -> None:
        """Initialize captured file ids."""
        self.file_ids = []

    async def create_data_url(self, file_id: str):
        """Return a deterministic data URL."""
        self.file_ids.append(file_id)
        return SimpleNamespace(id=file_id), f"data:image/png;base64,{file_id}"


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
    assert "Relivo stateful streaming chat agent" in prompt
    assert (
        "Call memory_context before answering requests that depend on saved user identity"
        in prompt
    )
    assert "Use tools for current or verifiable information" in prompt


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

    assert len(tools) == 6
    assert tools[0].name == "get_demo_context"
    assert tools[1].name == read_chat_attachment.name
    assert tools[2].name == memory_context.name
    assert tools[3].name == memory_search.name
    assert tools[4].name == memory_commit.name
    assert tools[5].name == memory_supersede.name


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
    assert agent.prompts == ["help me plan"]
    assert 'data: {"type": "text-delta", "id": "text-1", "delta": "Planned"}\n\n' in events


@pytest.mark.asyncio
async def test_stream_chat_builds_multimodal_prompt_for_attachments() -> None:
    """Image attachments should be passed to the agent as image URL content parts."""
    agent = StreamingAgent()
    service = ChatService(agent)

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(
                user_message="",
                thread_id="user-123",
                attachments=[
                    {
                        "url": "https://files.example.test/avatar.png",
                        "mediaType": "image/png",
                        "title": "avatar.png",
                    }
                ],
            )
        )
    ]

    assert agent.prompts == [
        [
            {"type": "text", "text": "Please analyze the attached file."},
            {
                "type": "image_url",
                "image_url": {"url": "https://files.example.test/avatar.png"},
            },
        ]
    ]
    assert 'data: {"type": "text-delta", "id": "text-1", "delta": "Planned"}\n\n' in events


@pytest.mark.asyncio
async def test_stream_chat_resolves_uploaded_image_to_data_url() -> None:
    """Uploaded image attachments should avoid passing private S3 URLs to OpenAI."""
    agent = StreamingAgent()
    file_lookup = FakeUserFileLookup()
    service = ChatService(agent, user_file_service=file_lookup)

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(
                user_message="What is this?",
                thread_id="user-123",
                attachments=[
                    {
                        "id": "file-id",
                        "url": "https://files.example.test/avatar.png",
                        "mediaType": "image/png",
                        "title": "avatar.png",
                        "providerFileId": "file-id",
                    }
                ],
            )
        )
    ]

    assert file_lookup.file_ids == ["file-id"]
    assert agent.prompts == [
        [
            {"type": "text", "text": "What is this?"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,file-id"},
            },
        ]
    ]
    assert 'data: {"type": "text-delta", "id": "text-1", "delta": "Planned"}\n\n' in events


@pytest.mark.asyncio
async def test_stream_chat_passes_document_attachments_as_file_refs() -> None:
    """Document attachments should be passed by providerFileId instead of private URLs."""
    agent = StreamingAgent()
    service = ChatService(agent)

    events = [
        event
        async for event in service.stream_chat(
            ChatRequest(
                user_message="Summarize this",
                thread_id="user-123",
                attachments=[
                    {
                        "url": "https://private.example.test/report.pdf?token=secret",
                        "mediaType": "application/pdf",
                        "title": "report.pdf",
                        "providerFileId": "file-id",
                    }
                ],
            )
        )
    ]

    prompt = agent.prompts[0]
    file_block = prompt[1]["text"]
    assert "[FILES]" in file_block
    assert "providerFileId: file-id" in file_block
    assert "read_chat_attachment" in file_block
    assert "https://private.example.test" not in file_block
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
