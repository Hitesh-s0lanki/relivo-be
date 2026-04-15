"""Service layer for conversation business logic."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select

from src.db.database import async_session
from src.db.models import Conversation, Message
from src.schema.chat import (
    ConversationMessagesRequest,
    ConversationMessagesResponse,
    MessageRole,
    MessageStatus,
    TextPart,
    UIMessage,
    UIMessageMetadata,
    UIMessagePart,
)
from src.schema.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationSchema,
    ConversationStatus,
    ConversationUpdate,
    GetAllConversationsRequest,
)

logger = logging.getLogger(__name__)


class ConversationService:
    """Handles all conversation CRUD and message retrieval."""

    async def create_conversation(self, request: ConversationCreate) -> ConversationSchema:
        """Create a new conversation and persist it."""
        conv = Conversation(
            user_id=request.user_id,
            title=request.title,
            status=int(ConversationStatus.ACTIVE),
        )
        async with async_session() as db:
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
        return self._to_schema(conv)

    async def get_conversation(self, conversation_id: str, user_id: str) -> ConversationSchema:
        """Fetch a single conversation by ID, scoped to user_id."""
        if not conversation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Conversation ID is required."
            )
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="User ID is required."
            )
        conv_uuid = uuid.UUID(conversation_id)
        async with async_session() as db:
            result = await db.execute(
                select(Conversation).filter(
                    Conversation.id == conv_uuid,
                    Conversation.user_id == user_id,
                    Conversation.status != int(ConversationStatus.DELETED),
                )
            )
            conv = result.scalars().first()
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {conversation_id} not found.",
            )
        return self._to_schema(conv)

    async def get_all_conversations(
        self, request: GetAllConversationsRequest
    ) -> ConversationList:
        """Return all non-deleted conversations for a user, newest first."""
        if not request.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="User ID is required."
            )
        async with async_session() as db:
            result = await db.execute(
                select(Conversation)
                .filter(
                    Conversation.user_id == request.user_id,
                    Conversation.status != int(ConversationStatus.DELETED),
                )
                .order_by(Conversation.updated_at.desc())
            )
            convs = result.scalars().all()
        return ConversationList(conversations=[self._to_schema(c) for c in convs])

    async def update_conversation(self, request: ConversationUpdate) -> ConversationSchema:
        """Update mutable fields on an existing conversation."""
        if not request.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Conversation ID is required."
            )
        conv_uuid = uuid.UUID(request.id)
        async with async_session() as db:
            result = await db.execute(
                select(Conversation).filter(Conversation.id == conv_uuid)
            )
            conv = result.scalars().first()
            if not conv:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conversation {request.id} not found.",
                )
            if request.title is not None:
                conv.title = request.title
            if request.status is not None:
                conv.status = int(request.status)
            await db.commit()
            await db.refresh(conv)
        return self._to_schema(conv)

    async def delete_conversation(self, conversation_id: str, user_id: str) -> None:
        """Soft-delete a conversation (sets status to DELETED)."""
        if not conversation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Conversation ID is required."
            )
        conv_uuid = uuid.UUID(conversation_id)
        async with async_session() as db:
            result = await db.execute(
                select(Conversation).filter(
                    Conversation.id == conv_uuid,
                    Conversation.user_id == user_id,
                )
            )
            conv = result.scalars().first()
            if not conv:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conversation {conversation_id} not found.",
                )
            conv.status = int(ConversationStatus.DELETED)
            await db.commit()

    async def update_conversation_status(self, conversation_id: str, new_status: int) -> None:
        """Update conversation status (used internally by ChatService)."""
        conv_uuid = uuid.UUID(conversation_id)
        async with async_session() as db:
            result = await db.execute(
                select(Conversation).filter(Conversation.id == conv_uuid)
            )
            conv = result.scalars().first()
            if conv:
                conv.status = new_status
                await db.commit()

    async def get_conversation_status(self, conversation_id: str) -> int:
        """Return the raw status int for a conversation (DELETED=4 if not found)."""
        conv_uuid = uuid.UUID(conversation_id)
        async with async_session() as db:
            result = await db.execute(
                select(Conversation).filter(Conversation.id == conv_uuid)
            )
            conv = result.scalars().first()
        return conv.status if conv else int(ConversationStatus.DELETED)

    async def get_messages(
        self, request: ConversationMessagesRequest
    ) -> ConversationMessagesResponse:
        """Return paginated completed messages for a conversation as UIMessage objects."""
        if not request.conversation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Conversation ID is required."
            )
        conv_uuid = uuid.UUID(request.conversation_id)
        limit = min(request.limit or 50, 100)
        offset = request.offset or 0

        async with async_session() as db:
            conv_result = await db.execute(
                select(Conversation).filter(
                    Conversation.id == conv_uuid,
                    Conversation.user_id == request.user_id,
                )
            )
            if not conv_result.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conversation {request.conversation_id} not found.",
                )
            msgs_result = await db.execute(
                select(Message)
                .filter(
                    Message.conversation_id == conv_uuid,
                    Message.status == "completed",
                )
                .order_by(Message.sequence_number)
                .offset(offset)
                .limit(limit + 1)
            )
            messages = list(msgs_result.scalars().all())

        has_more = len(messages) > limit
        if has_more:
            messages = messages[:limit]

        ui_messages = [self._message_to_ui(msg) for msg in messages]
        return ConversationMessagesResponse(
            messages=ui_messages,
            hasMore=has_more,
            nextOffset=offset + len(messages),
            count=len(ui_messages),
        )

    def _message_to_ui(self, msg: Message) -> UIMessage:
        """Convert a DB Message row to UIMessage format."""
        role = MessageRole.USER if msg.role == "user" else MessageRole.ASSISTANT
        parts = [UIMessagePart(text=TextPart(text=msg.content or "", state="done"))]
        metadata = UIMessageMetadata(
            createdAt=msg.created_at.isoformat() if msg.created_at else "",
            tokens=0,
        )
        msg_status = (
            MessageStatus.COMPLETED if msg.status == "completed" else MessageStatus.STREAMING
        )
        return UIMessage(id=str(msg.id), role=role, parts=parts, metadata=metadata, status=msg_status)

    def _to_schema(self, conv: Conversation) -> ConversationSchema:
        """Convert a DB Conversation row to ConversationSchema."""
        return ConversationSchema(
            id=str(conv.id),
            userId=conv.user_id,
            title=conv.title,
            status=ConversationStatus(conv.status if conv.status is not None else 0),
            createdAt=conv.created_at.isoformat() if conv.created_at else "",
            updatedAt=conv.updated_at.isoformat() if conv.updated_at else "",
        )
