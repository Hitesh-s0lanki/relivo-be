"""Streaming chat endpoint backed by the demo LangChain agent."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agents import BaseAgent, BaseAgentConfig

router = APIRouter()


class ChatRequest(BaseModel):
    """Request body for streaming chat."""

    message: str = Field(..., min_length=1, max_length=8000)
    thread_id: str = Field(default="demo", min_length=1, max_length=200)
    stream_mode: tuple[Literal["updates", "messages"], ...] = ("updates", "messages")


@tool
def get_demo_context(topic: str) -> str:
    """Return demo context for a topic."""
    return (
        f"Demo context for {topic}: stream model tokens, tool calls, tool results, "
        "agent step updates, and terminal errors as separate events."
    )


@lru_cache(maxsize=1)
def get_demo_agent() -> BaseAgent:
    """Build the demo chat agent once per process."""
    if os.getenv("OPENAI_API_KEY"):
        model: str | FakeListChatModel = os.getenv("RELIVO_CHAT_MODEL", "openai:gpt-4.1-mini")
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
            system_prompt=(
                "You are the Relivo demo streaming agent. Be concise. "
                "When tools are available, use them before answering."
            ),
            name="demo_agent",
        ),
        tools=tools,
    )


DemoAgentDependency = Depends(get_demo_agent)


@router.post("/chat")
async def chat(
    request: ChatRequest,
    agent: BaseAgent = DemoAgentDependency,
) -> StreamingResponse:
    """Stream a demo agent response as Server-Sent Events."""
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="message cannot be blank")

    return StreamingResponse(
        _stream_chat(request, agent),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_chat(request: ChatRequest, agent: BaseAgent) -> AsyncIterator[str]:
    yield _sse("start", {"thread_id": request.thread_id})

    try:
        async for chunk in agent.astream_events(
            request.message,
            thread_id=request.thread_id,
            stream_mode=request.stream_mode,
        ):
            for event_name, payload in _normalize_agent_chunk(chunk):
                yield _sse(event_name, payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        yield _sse("error", {"message": "chat stream failed", "detail": str(exc)})
    finally:
        yield _sse("done", {"thread_id": request.thread_id})


def _normalize_agent_chunk(chunk: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(chunk, dict):
        return [("event", {"value": str(chunk)})]

    event_type = chunk.get("type")
    if event_type == "messages":
        return [("message", _normalize_message_chunk(chunk))]

    if event_type == "updates":
        return [
            ("update", payload)
            for payload in _normalize_update_chunk(chunk)
        ]

    return [("event", {"type": event_type, "data": _json_safe(chunk.get("data"))})]


def _normalize_message_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    data = chunk.get("data")
    if not isinstance(data, tuple) or len(data) < 2:
        return {"content": "", "metadata": {}}

    message_chunk, metadata = data
    return {
        "node": metadata.get("langgraph_node") if isinstance(metadata, dict) else None,
        "content": _content_to_text(getattr(message_chunk, "content", "")),
        "tool_call_chunks": _json_safe(getattr(message_chunk, "tool_call_chunks", [])),
        "metadata": _json_safe(metadata),
    }


def _normalize_update_chunk(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    data = chunk.get("data")
    if not isinstance(data, dict):
        return [{"step": "unknown", "data": _json_safe(data)}]

    updates: list[dict[str, Any]] = []
    for step, step_data in data.items():
        messages = step_data.get("messages", []) if isinstance(step_data, dict) else []
        latest = messages[-1] if messages else None
        updates.append(
            {
                "step": step,
                "name": getattr(latest, "name", None),
                "content": _content_to_text(getattr(latest, "content", "")),
                "tool_calls": _json_safe(getattr(latest, "tool_calls", [])),
            }
        )

    return updates


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "".join(parts)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
