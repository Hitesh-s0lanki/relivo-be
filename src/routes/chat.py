"""Chat streaming endpoints: POST /chat, POST /conversation/cancel-response, GET /chat/resume-stream/{id}."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from src.schema.chat import CancelMessageRequest, UserMessageRequest
from src.schema.conversation import ConversationStatus
from src.services.chat_service import ChatService
from src.services.conversation_service import ConversationService
from src.utils.data_protocol import StreamProtocolBuilder
from src.utils.heartbeat_wrapper import add_heartbeat_to_stream
from src.utils.stream_registry import stream_registry

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat(request: UserMessageRequest) -> StreamingResponse:
    """Stream an agent response for the given user message."""
    service = ChatService(request)
    generator = add_heartbeat_to_stream(service.stream(), interval=10.0)
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post("/conversation/cancel-response")
async def cancel_response(request: CancelMessageRequest) -> JSONResponse:
    """Cancel an in-progress SSE response."""
    user_req = request.user_message_request
    if not user_req or not user_req.conversation_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "userMessageRequest.conversationId is required"},
        )

    cancelled = await stream_registry.cancel(user_req.conversation_id)
    if cancelled:
        logger.info("Cancelled active stream for %s", user_req.conversation_id)
        return JSONResponse(
            status_code=200,
            content={"detail": "Cancel signal sent — stream will stop shortly"},
        )
    return JSONResponse(
        status_code=200,
        content={"detail": "No active stream found — response may have already completed"},
    )


@router.get("/chat/resume-stream/{conversation_id}", response_model=None)
async def resume_stream(conversation_id: str) -> StreamingResponse:
    """Resume a stream for conversations that are still in STREAMING status."""
    conv_service = ConversationService()

    async def generator():
        conv_status = await conv_service.get_conversation_status(conversation_id)
        if conv_status != int(ConversationStatus.STREAMING):
            yield StreamProtocolBuilder.message_end(
                {"resumed": False, "reason": "already_finalized", "status": conv_status}
            ).to_sse()
            yield StreamProtocolBuilder.terminate_stream().to_sse()
            return

        stream_status = await stream_registry.get_status(conversation_id)
        if stream_status != "active":
            yield StreamProtocolBuilder.message_end(
                {"resumed": False, "reason": "stream_not_active", "status": stream_status}
            ).to_sse()
            yield StreamProtocolBuilder.terminate_stream().to_sse()
            return

        if await stream_registry.has_chunks(conversation_id):
            for chunk in await stream_registry.replay(conversation_id, 0):
                yield chunk

        async for chunk in stream_registry.subscribe(conversation_id):
            yield chunk

        yield StreamProtocolBuilder.message_end(
            {"resumed": True, "reason": "stream_completed"}
        ).to_sse()
        yield StreamProtocolBuilder.terminate_stream().to_sse()

    return StreamingResponse(generator(), media_type="text/event-stream")
