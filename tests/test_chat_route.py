"""Tests for the streaming chat route."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.routes.chat import get_demo_agent


class FakeStreamingAgent:
    """Small fake agent for deterministic route tests."""

    async def astream_events(
        self,
        prompt: str,
        *,
        thread_id: str,
        stream_mode: tuple[str, ...],
    ) -> AsyncIterator[dict]:
        yield {
            "type": "messages",
            "data": (
                type("Chunk", (), {"content": f"hello {prompt}", "tool_call_chunks": []})(),
                {"langgraph_node": "model"},
            ),
        }
        yield {
            "type": "updates",
            "data": {
                "model": {
                    "messages": [
                        type(
                            "Message",
                            (),
                            {
                                "name": "demo_agent",
                                "content": "final",
                                "tool_calls": [],
                            },
                        )()
                    ]
                }
            },
        }


class FailingStreamingAgent:
    """Fake agent that raises mid-stream."""

    async def astream_events(
        self,
        prompt: str,
        *,
        thread_id: str,
        stream_mode: tuple[str, ...],
    ) -> AsyncIterator[dict]:
        yield {"type": "messages", "data": (type("Chunk", (), {"content": "before"})(), {})}
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_chat_streams_agent_events() -> None:
    """The chat route should stream normalized agent events."""
    app = create_app()
    app.dependency_overrides[get_demo_agent] = lambda: FakeStreamingAgent()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "world", "thread_id": "t1"})

    body = response.text
    assert response.status_code == 200
    assert "event: start" in body
    assert "event: message" in body
    assert "hello world" in body
    assert "event: update" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_chat_streams_errors() -> None:
    """The chat route should emit an SSE error event for stream failures."""
    app = create_app()
    app.dependency_overrides[get_demo_agent] = lambda: FailingStreamingAgent()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "world"})

    body = response.text
    assert response.status_code == 200
    assert "event: error" in body
    assert "boom" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_chat_rejects_blank_message() -> None:
    """Blank messages should fail before opening the stream."""
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "   "})

    assert response.status_code == 422
