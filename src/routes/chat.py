from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.schema.chat import UserMessageRequest
from src.services.chat_service import ChatService
from src.utils.heartbeat_wrapper import add_heartbeat_to_stream

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(request: UserMessageRequest) -> StreamingResponse:
    """
    Stream an agent response for the given user message.

    Returns a text/event-stream response following the Vercel AI SDK Data Stream protocol.
    Heartbeat events are injected every 10 seconds of inactivity.
    """
    service = ChatService(request)
    generator = add_heartbeat_to_stream(service.stream(), interval=10.0)
    return StreamingResponse(generator, media_type="text/event-stream")
