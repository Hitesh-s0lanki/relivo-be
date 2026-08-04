"""Tests for per-user agent selection inside the chat stream."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.schemas.chat import ChatRequest
from src.services.chat_service import ChatService


class RecordingAgent:
    """Agent stub that records whether it served the turn."""

    def __init__(self, name: str) -> None:
        """Initialize the stub with a label."""
        self.name = name
        self.called = False
        self.config = SimpleNamespace(name="Orchestrator")

    async def astream_events(self, *args, **kwargs):
        self.called = True
        yield {
            "type": "messages",
            "data": (
                type("MessageChunk", (), {"content": self.name, "tool_call_chunks": []})(),
                {"langgraph_node": "model"},
            ),
        }


class ConversationLookup:
    """Conversation service stub that resolves a user id."""

    def __init__(self, thread_id: str, user_id: str) -> None:
        """Store the conversation the lookup should return."""
        self.thread_id = thread_id
        self.user_id = user_id

    async def get_conversation(self, thread_id: str):
        return SimpleNamespace(id=self.thread_id, user_id=self.user_id)

    async def append_messages(self, *args, **kwargs):
        return None


async def collect(service: ChatService, thread_id: str) -> str:
    """Run one turn and return the joined stream."""
    request = ChatRequest(user_message="do the thing", thread_id=thread_id)
    return "".join([chunk async for chunk in service.stream_chat(request)])


@pytest.mark.asyncio
async def test_resolver_agent_serves_the_turn() -> None:
    """When a resolver is set, the per-user agent runs instead of the base."""
    thread_id = str(uuid4())
    base = RecordingAgent("base")
    per_user = RecordingAgent("per-user")
    seen: list[str] = []

    async def resolver(user_id: str):
        seen.append(user_id)
        return per_user

    service = ChatService(
        base,
        ConversationLookup(thread_id, "user_a"),
        agent_resolver=resolver,
    )
    stream = await collect(service, thread_id)

    assert seen == ["user_a"]
    assert per_user.called
    assert not base.called
    assert "per-user" in stream


@pytest.mark.asyncio
async def test_base_agent_serves_when_no_resolver_is_set() -> None:
    """Existing callers that pass only an agent keep working."""
    thread_id = str(uuid4())
    base = RecordingAgent("base")

    service = ChatService(base, ConversationLookup(thread_id, "user_a"))
    await collect(service, thread_id)

    assert base.called


@pytest.mark.asyncio
async def test_resolver_is_skipped_without_a_user_id() -> None:
    """An anonymous thread never triggers a per-user lookup."""
    base = RecordingAgent("base")
    called = False

    async def resolver(user_id: str):
        nonlocal called
        called = True
        return RecordingAgent("per-user")

    service = ChatService(base, agent_resolver=resolver)
    await collect(service, "not-a-uuid")

    assert base.called
    assert not called


@pytest.mark.asyncio
async def test_resolver_failure_falls_back_to_the_base_agent() -> None:
    """A resolution error must not cost the user their reply."""
    thread_id = str(uuid4())
    base = RecordingAgent("base")

    async def resolver(user_id: str):
        raise RuntimeError("mcp lookup exploded")

    service = ChatService(
        base,
        ConversationLookup(thread_id, "user_a"),
        agent_resolver=resolver,
    )
    stream = await collect(service, thread_id)

    assert base.called
    assert "base" in stream
    assert "chat_stream_failed" not in stream


@pytest.mark.asyncio
async def test_each_user_gets_their_own_agent() -> None:
    """Two users on the same service instance resolve to different agents."""
    thread_a, thread_b = str(uuid4()), str(uuid4())
    base = RecordingAgent("base")
    agents = {"user_a": RecordingAgent("a"), "user_b": RecordingAgent("b")}

    async def resolver(user_id: str):
        return agents[user_id]

    await collect(
        ChatService(base, ConversationLookup(thread_a, "user_a"), agent_resolver=resolver),
        thread_a,
    )
    await collect(
        ChatService(base, ConversationLookup(thread_b, "user_b"), agent_resolver=resolver),
        thread_b,
    )

    assert agents["user_a"].called
    assert agents["user_b"].called
    assert not base.called
