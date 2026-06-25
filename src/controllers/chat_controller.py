"""Chat HTTP controller."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import BaseAgent, get_chat_agent
from src.database import get_db_session
from src.schemas.chat import ChatErrorResponse, ChatRequest
from src.services.chat_service import ChatService
from src.services.conversation_service import ConversationService
from src.utils.error_response import build_error_response

router = APIRouter()
ChatAgentDependency = Depends(get_chat_agent)


def get_chat_service(
    agent: BaseAgent = ChatAgentDependency,
    session: Annotated[AsyncSession | None, Depends(get_db_session)] = None,
) -> ChatService:
    """Resolve the chat service dependency."""
    conversation_service = ConversationService(session) if session is not None else None
    return ChatService(agent, conversation_service)


ChatServiceDependency = Depends(get_chat_service)


CHAT_ENDPOINT_DESCRIPTION = """
Streams a chat response from the Relivo chat agent using Vercel AI SDK UI message
stream Server-Sent Events.

Request body:
- `user_message`: required user message, 1-8000 characters.
- `thread_id`: optional conversation thread id. Defaults to `demo`.
- `stream_mode`: optional agent stream modes. Supported values are `updates` and `messages`.

Stream part types:
- `start`: stream opened.
- `text-start`: assistant text block opened.
- `text-delta`: assistant text chunk.
- `text-end`: assistant text block closed.
- `tool-input-available`: tool call input is complete.
- `data-agent-update`: custom agent graph update data.
- `data-tool-call-chunk`: custom streamed tool call chunk data.
- `error`: stream failed after opening.
- `finish`: stream closed.

When `OPENAI_API_KEY` is not configured, the service streams a local demo fallback response.
"""

CHAT_STREAM_EXAMPLE = """data: {"type":"start","messageId":"user-123"}

data: {"type":"text-start","id":"text-1"}

data: {"type":"text-delta","id":"text-1","delta":"Hello"}

data: {"type":"text-end","id":"text-1"}

data: {"type":"finish"}

data: [DONE]
"""


@router.post(
    "/chat",
    tags=["Chat"],
    summary="Stream chat response",
    description=CHAT_ENDPOINT_DESCRIPTION,
    response_class=StreamingResponse,
    response_description="Server-Sent Events stream with chat agent output.",
    responses={
        200: {
            "description": "SSE stream opened successfully.",
            "content": {
                "text/event-stream": {
                    "example": CHAT_STREAM_EXAMPLE,
                }
            },
            "headers": {
                "Cache-Control": {
                    "description": "Prevents response caching.",
                    "schema": {"type": "string", "example": "no-cache"},
                },
                "Connection": {
                    "description": "Keeps the streaming connection open.",
                    "schema": {"type": "string", "example": "keep-alive"},
                },
                "X-Accel-Buffering": {
                    "description": "Disables buffering behind compatible reverse proxies.",
                    "schema": {"type": "string", "example": "no"},
                },
                "x-vercel-ai-ui-message-stream": {
                    "description": "Identifies the response as a Vercel AI SDK UI message stream.",
                    "schema": {"type": "string", "example": "v1"},
                },
            },
        },
        422: {
            "description": "Validation error. `user_message` is missing, invalid, or blank.",
            "model": ChatErrorResponse,
        },
    },
)
async def chat(
    request: ChatRequest,
    service: ChatService = ChatServiceDependency,
) -> StreamingResponse:
    """Stream a chat response as Server-Sent Events."""
    if not request.user_message.strip():
        error = build_error_response(
            status=422,
            message="user_message cannot be blank",
            error_tag="blank_user_message",
        )
        raise HTTPException(status_code=422, detail=error.model_dump())

    return StreamingResponse(
        service.stream_chat(request),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
