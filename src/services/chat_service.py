"""Chat streaming service backed by the LangChain agent harness."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.agents import BaseAgent
from src.agents.base_agent import AgentPrompt
from src.schemas.chat import ChatRequest
from src.schemas.conversation import MessageCreate, ToolCallCreate
from src.schemas.user_file import AttachmentInput
from src.services.conversation_service import ConversationNotFoundError, ConversationService
from src.services.user_file_service import UserFileNotFoundError, UserFileService
from src.utils.error_response import build_error_response, log_error_response

logger = logging.getLogger(__name__)
FAST_GREETING_RESPONSES = {
    "hello": "Hello! How can I help?",
    "hi": "Hi! How can I help?",
    "hey": "Hey! How can I help?",
}


@dataclass(slots=True)
class CapturedToolCall:
    """Tool call data captured from the agent stream."""

    tool_call_id: str | None
    name: str
    arguments: dict[str, Any] | None
    result: dict[str, Any] | str | None = None
    status: str = "running"
    sequence: int = 0


class ChatService:
    """Coordinates chat requests and converts agent output to SSE events."""

    def __init__(
        self,
        agent: BaseAgent,
        conversation_service: ConversationService | None = None,
        user_file_service: UserFileService | None = None,
    ) -> None:
        """Initialize the service with an agent dependency."""
        self.agent = agent
        self.conversation_service = conversation_service
        self.user_file_service = user_file_service

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        """Stream a chat response as Vercel AI SDK UI message stream frames."""
        text_started = False
        stream_failed = False
        text_parts: list[str] = []
        tool_calls: list[CapturedToolCall] = []

        yield self._sse_data({"type": "start", "messageId": request.thread_id})

        if not request.attachments and (response := self._fast_response(request.user_message)):
            yield self._sse_data({"type": "text-start", "id": "text-1"})
            yield self._sse_data({"type": "text-delta", "id": "text-1", "delta": response})
            yield self._sse_data({"type": "text-end", "id": "text-1"})
            yield self._sse_data({"type": "finish"})
            yield self._sse_data("[DONE]")
            return

        try:
            async for chunk in self.agent.astream_events(
                await self._agent_prompt(request),
                thread_id=request.thread_id,
                stream_mode=request.stream_mode,
            ):
                for part in self._normalize_agent_chunk(chunk):
                    self._capture_persistence_part(part, text_parts, tool_calls)
                    if part["type"] == "text-delta" and not text_started:
                        yield self._sse_data({"type": "text-start", "id": "text-1"})
                        text_started = True
                    yield self._sse_data(part)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stream_failed = True
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
            if not stream_failed:
                await self._persist_tool_chat(request, "".join(text_parts), tool_calls)
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

    @classmethod
    def _capture_persistence_part(
        cls,
        part: dict[str, Any],
        text_parts: list[str],
        tool_calls: list[CapturedToolCall],
    ) -> None:
        """Capture text and tool calls from normalized stream parts."""
        part_type = part.get("type")
        if part_type == "text-delta":
            text_parts.append(str(part.get("delta", "")))
            return

        if part_type == "tool-input-available":
            tool_calls.append(
                CapturedToolCall(
                    tool_call_id=str(part.get("toolCallId") or "") or None,
                    name=str(part.get("toolName") or ""),
                    arguments=cls._dict_or_none(part.get("input")),
                    sequence=len(tool_calls),
                )
            )
            return

        if part_type != "data-agent-update":
            return

        payload = part.get("data")
        if not isinstance(payload, dict) or payload.get("step") != "tools":
            return

        tool_name = str(payload.get("name") or "")
        tool_call = cls._latest_matching_tool_call(tool_calls, tool_name)
        if tool_call is None:
            return

        tool_call.result = cls._tool_result_from_content(payload.get("content"))
        tool_call.status = "completed"

    @staticmethod
    def _latest_matching_tool_call(
        tool_calls: list[CapturedToolCall],
        tool_name: str,
    ) -> CapturedToolCall | None:
        for tool_call in reversed(tool_calls):
            if tool_call.name == tool_name and tool_call.result is None:
                return tool_call
        for tool_call in reversed(tool_calls):
            if tool_call.name == tool_name:
                return tool_call
        return None

    async def _persist_tool_chat(
        self,
        request: ChatRequest,
        assistant_text: str,
        tool_calls: list[CapturedToolCall],
    ) -> None:
        """Persist a tool-using assistant response when thread_id is a conversation id."""
        if not self.conversation_service or not tool_calls or not self._is_uuid(request.thread_id):
            return

        try:
            tool_call_payloads = self._tool_call_payloads(tool_calls)
            messages = await self.conversation_service.list_messages(request.thread_id)
            existing_message = self._matching_agent_message(messages, assistant_text)
            if existing_message is not None:
                for tool_call_payload in tool_call_payloads:
                    await self.conversation_service.create_tool_call(
                        request.thread_id,
                        str(existing_message.id),
                        tool_call_payload,
                    )
                return

            await self.conversation_service.create_message(
                request.thread_id,
                MessageCreate(
                    role="agent",
                    text=assistant_text or None,
                    tool_calls=tool_call_payloads,
                    metadata={"source": "chat_stream", "thread_id": request.thread_id},
                ),
            )
        except ConversationNotFoundError:
            logger.info(
                "Skipping chat tool persistence because conversation was not found thread_id=%s",
                request.thread_id,
            )
        except Exception as exc:
            logger.warning("Failed to persist chat tool calls: %s", exc, exc_info=exc)

    @staticmethod
    def _tool_call_payloads(tool_calls: list[CapturedToolCall]) -> list[ToolCallCreate]:
        return [
            ToolCallCreate(
                tool_call_id=tool_call.tool_call_id,
                name=tool_call.name,
                arguments=tool_call.arguments,
                result=tool_call.result,
                status=(tool_call.status if tool_call.status != "running" else "completed"),
                sequence=tool_call.sequence,
            )
            for tool_call in tool_calls
            if tool_call.name
        ]

    @staticmethod
    def _matching_agent_message(messages: list[Any], assistant_text: str) -> Any | None:
        for message in reversed(messages):
            if (
                getattr(message, "role", None) == "agent"
                and getattr(message, "text", None) == assistant_text
                and not getattr(message, "tool_calls", [])
            ):
                return message
        return None

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
    def _dict_or_none(value: Any) -> dict[str, Any] | None:
        return value if isinstance(value, dict) else None

    @staticmethod
    def _tool_result_from_content(content: Any) -> dict[str, Any] | str | None:
        if not isinstance(content, str):
            return ChatService._json_safe(content)
        if not content:
            return None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
        return parsed if isinstance(parsed, dict) else content

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            UUID(value)
        except ValueError:
            return False
        return True

    @staticmethod
    def _fast_response(user_message: str) -> str | None:
        normalized = user_message.strip().lower().rstrip("!.")
        return FAST_GREETING_RESPONSES.get(normalized)

    async def _agent_prompt(self, request: ChatRequest) -> AgentPrompt:
        """Build text-only or multimodal agent input from a chat request."""
        if not request.attachments:
            return request.user_message

        text = request.user_message.strip() or "Please analyze the attached file."
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        non_image_lines: list[str] = []

        for attachment in request.attachments:
            if self._is_image_attachment(attachment):
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": await self._image_url_for_model(attachment)},
                    }
                )
                continue

            non_image_lines.append(
                f"- {attachment.title} ({attachment.media_type}): {attachment.url}"
            )

        if non_image_lines:
            content.append(
                {
                    "type": "text",
                    "text": "\n\nAttached files:\n" + "\n".join(non_image_lines),
                }
            )

        return content

    async def _image_url_for_model(self, attachment: AttachmentInput) -> str:
        """Return a model-readable image URL, preferring data URLs for stored uploads."""
        file_id = self._attachment_file_id(attachment)
        if not file_id or self.user_file_service is None:
            return attachment.url

        try:
            _metadata, data_url = await self.user_file_service.create_data_url(file_id)
        except UserFileNotFoundError:
            return attachment.url

        return data_url

    @staticmethod
    def _attachment_file_id(attachment: AttachmentInput) -> str | None:
        extra = attachment.model_extra or {}
        value = extra.get("providerFileId") or extra.get("provider_file_id") or extra.get("id")
        return str(value) if value else None

    @staticmethod
    def _is_image_attachment(attachment: AttachmentInput) -> bool:
        return attachment.media_type.split(";")[0].strip().lower().startswith("image/")

    @staticmethod
    def _sse_data(data: dict[str, Any] | str) -> str:
        if isinstance(data, str):
            return f"data: {data}\n\n"
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
