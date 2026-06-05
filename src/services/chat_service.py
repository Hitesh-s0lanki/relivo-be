"""Chat streaming service backed by the LangChain agent harness."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.agents import BaseAgent
from src.schemas.chat import ChatRequest
from src.utils.error_response import build_error_response, log_error_response

logger = logging.getLogger(__name__)
FAST_GREETING_RESPONSES = {
    "hello": "Hello! How can I help?",
    "hi": "Hi! How can I help?",
    "hey": "Hey! How can I help?",
}


class ChatService:
    """Coordinates chat requests and converts agent output to SSE events."""

    def __init__(self, agent: BaseAgent) -> None:
        """Initialize the service with an agent dependency."""
        self.agent = agent

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        """Stream a chat response as Vercel AI SDK UI message stream frames."""
        text_started = False

        yield self._sse_data({"type": "start", "messageId": request.thread_id})

        if response := self._fast_response(request.user_message):
            yield self._sse_data({"type": "text-start", "id": "text-1"})
            yield self._sse_data({"type": "text-delta", "id": "text-1", "delta": response})
            yield self._sse_data({"type": "text-end", "id": "text-1"})
            yield self._sse_data({"type": "finish"})
            yield self._sse_data("[DONE]")
            return

        try:
            async for chunk in self.agent.astream_events(
                request.user_message,
                thread_id=request.thread_id,
                stream_mode=request.stream_mode,
            ):
                for part in self._normalize_agent_chunk(chunk):
                    if part["type"] == "text-delta" and not text_started:
                        yield self._sse_data({"type": "text-start", "id": "text-1"})
                        text_started = True
                    yield self._sse_data(part)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = build_error_response(
                status=500,
                message="chat stream failed",
                error_tag="chat_stream_failed",
            )
            log_error_response(logger, error, detail=str(exc), exc=exc)
            yield self._sse_data(
                {
                    "type": "error",
                    "errorText": error.message,
                    "data": error.model_dump(),
                }
            )
        finally:
            if text_started:
                yield self._sse_data({"type": "text-end", "id": "text-1"})
            yield self._sse_data({"type": "finish"})
            yield self._sse_data("[DONE]")

    @classmethod
    def _normalize_agent_chunk(cls, chunk: Any) -> list[dict[str, Any]]:
        if not isinstance(chunk, dict):
            return [{"type": "data-agent-event", "data": {"value": str(chunk)}}]

        event_type = chunk.get("type")
        if event_type == "messages":
            return cls._normalize_message_chunk(chunk)

        if event_type == "updates":
            return [
                part
                for payload in cls._normalize_update_chunk(chunk)
                for part in cls._update_payload_to_parts(payload)
            ]

        return [
            {
                "type": "data-agent-event",
                "data": {"type": event_type, "data": cls._json_safe(chunk.get("data"))},
            }
        ]

    @classmethod
    def _normalize_message_chunk(cls, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        data = chunk.get("data")
        if not isinstance(data, tuple) or len(data) < 2:
            return []

        message_chunk, metadata = data
        node = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
        content = cls._content_to_text(getattr(message_chunk, "content", ""))
        tool_call_chunks = cls._json_safe(getattr(message_chunk, "tool_call_chunks", []))
        parts: list[dict[str, Any]] = []

        if tool_call_chunks:
            parts.append(
                {
                    "type": "data-tool-call-chunk",
                    "data": {
                        "node": node,
                        "tool_call_chunks": tool_call_chunks,
                        "metadata": cls._json_safe(metadata),
                    },
                }
            )

        if content and node == "model":
            parts.append({"type": "text-delta", "id": "text-1", "delta": content})
        elif content:
            parts.append(
                {
                    "type": "data-agent-update",
                    "data": {
                        "node": node,
                        "content": content,
                        "metadata": cls._json_safe(metadata),
                    },
                }
            )

        return parts

    @classmethod
    def _normalize_update_chunk(cls, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        data = chunk.get("data")
        if not isinstance(data, dict):
            return [{"step": "unknown", "data": cls._json_safe(data)}]

        updates: list[dict[str, Any]] = []
        for step, step_data in data.items():
            messages = step_data.get("messages", []) if isinstance(step_data, dict) else []
            latest = messages[-1] if messages else None
            updates.append(
                {
                    "step": step,
                    "name": getattr(latest, "name", None),
                    "content": cls._content_to_text(getattr(latest, "content", "")),
                    "tool_calls": cls._json_safe(getattr(latest, "tool_calls", [])),
                }
            )

        return updates

    @classmethod
    def _update_payload_to_parts(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        tool_calls = payload.get("tool_calls", [])
        if tool_calls:
            return [
                {
                    "type": "tool-input-available",
                    "toolCallId": str(tool_call.get("id", "")),
                    "toolName": str(tool_call.get("name", "")),
                    "input": cls._json_safe(tool_call.get("args", {})),
                }
                for tool_call in tool_calls
                if isinstance(tool_call, dict)
            ]

        if payload.get("step") == "tools":
            return [
                {
                    "type": "data-agent-update",
                    "data": payload,
                }
            ]

        return [{"type": "data-agent-update", "data": payload}]

    @staticmethod
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

    @staticmethod
    def _json_safe(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    @staticmethod
    def _fast_response(user_message: str) -> str | None:
        normalized = user_message.strip().lower().rstrip("!.")
        return FAST_GREETING_RESPONSES.get(normalized)

    @staticmethod
    def _sse_data(data: dict[str, Any] | str) -> str:
        if isinstance(data, str):
            return f"data: {data}\n\n"
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
