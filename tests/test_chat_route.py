"""Tests for the streaming chat route."""

import json
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from src.agents import get_chat_agent
from src.main import create_app


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
        yield {
            "type": "messages",
            "data": (
                type("Chunk", (), {"content": "before"})(),
                {"langgraph_node": "model"},
            ),
        }
        raise RuntimeError("boom")


def _sse_data_parts(body: str) -> list[dict | str]:
    """Extract data payloads from an SSE stream."""
    parts: list[dict | str] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        value = line.removeprefix("data: ")
        if value == "[DONE]":
            parts.append(value)
        else:
            parts.append(json.loads(value))
    return parts


@pytest.mark.asyncio
async def test_app_startup_warms_orchestrator_agent(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Application startup should initialize the cached chat agent."""
    calls: list[str] = []
    fake_agent = SimpleNamespace(
        config=SimpleNamespace(name="Orchestrator", model="fake-model"),
        tools=[],
    )

    def warm_agent() -> SimpleNamespace:
        calls.append("warm")
        return fake_agent

    monkeypatch.setattr("src.main.warm_orchestrator_agent", warm_agent)
    caplog.set_level(logging.INFO)
    app = create_app()

    async with app.router.lifespan_context(app):
        pass

    assert calls == ["warm"]
    assert "Application startup started" in caplog.text
    assert "Orchestrator agent warmed name=Orchestrator model=str tools=0" in caplog.text
    assert "Application startup complete" in caplog.text
    assert "Application shutdown complete" in caplog.text


@pytest.mark.asyncio
async def test_chat_streams_agent_events() -> None:
    """The chat route should stream normalized agent events."""
    app = create_app()
    app.dependency_overrides[get_chat_agent] = lambda: FakeStreamingAgent()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"user_message": "world", "thread_id": "t1"})

    body = response.text
    parts = _sse_data_parts(body)

    assert response.status_code == 200
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert parts[0] == {"type": "start", "messageId": "t1"}
    assert {"type": "text-start", "id": "text-1"} in parts
    assert {"type": "text-delta", "id": "text-1", "delta": "hello world"} in parts
    assert {"type": "text-end", "id": "text-1"} in parts
    assert {"type": "finish"} in parts
    assert parts[-1] == "[DONE]"
    assert any(isinstance(part, dict) and part["type"] == "data-agent-update" for part in parts)


@pytest.mark.asyncio
async def test_chat_streams_errors() -> None:
    """The chat route should emit an SSE error event for stream failures."""
    app = create_app()
    app.dependency_overrides[get_chat_agent] = lambda: FailingStreamingAgent()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"user_message": "world"})

    body = response.text
    parts = _sse_data_parts(body)
    error_parts = [part for part in parts if isinstance(part, dict) and part.get("type") == "error"]

    assert response.status_code == 200
    assert error_parts == [
        {
            "type": "error",
            "errorText": "chat stream failed",
            "data": {
                "status": 500,
                "message": "chat stream failed",
                "error_tag": "chat_stream_failed",
            },
        }
    ]
    assert {"type": "finish"} in parts
    assert parts[-1] == "[DONE]"
    assert {
        "type": "text-delta",
        "id": "text-1",
        "delta": "before",
    } in parts
    assert "boom" not in body


@pytest.mark.asyncio
async def test_chat_rejects_blank_message(caplog: pytest.LogCaptureFixture) -> None:
    """Blank messages should fail before opening the stream."""
    app = create_app()

    caplog.set_level(logging.INFO)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"user_message": "   "})

    assert response.status_code == 422
    assert response.json() == {
        "status": 422,
        "message": "user_message cannot be blank",
        "error_tag": "blank_user_message",
    }
    assert "error.status=422" in caplog.text
    assert "error.message=user_message cannot be blank" in caplog.text
    assert "error.error_tag=blank_user_message" in caplog.text
    assert "error response generated" in caplog.text


@pytest.mark.asyncio
async def test_chat_request_validation_uses_standard_error_response() -> None:
    """Pydantic validation errors should use the client-facing error contract."""
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={})

    assert response.status_code == 422
    assert response.json() == {
        "status": 422,
        "message": "request validation failed",
        "error_tag": "request_validation_error",
    }


def test_chat_error_response_schema_is_referenced_in_openapi() -> None:
    """The chat OpenAPI docs should expose the standard error response schema."""
    app = create_app()

    schema = app.openapi()

    chat_422_response = schema["paths"]["/chat"]["post"]["responses"]["422"]
    assert json.dumps(chat_422_response)
    assert "ChatErrorResponse" in json.dumps(chat_422_response)
