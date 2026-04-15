"""Conversation CRUD endpoints."""

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from src.schema.chat import ConversationMessagesRequest, ConversationMessagesResponse
from src.schema.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationSchema,
    ConversationUpdate,
    GetAllConversationsRequest,
)
from src.services.conversation_service import ConversationService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/conversation/create", response_model=ConversationSchema)
async def create_conversation(request: ConversationCreate) -> ConversationSchema:
    """Create a new conversation."""
    try:
        return await ConversationService().create_conversation(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create conversation: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
        ) from e


@router.get("/conversation/get/{conversation_id}", response_model=ConversationSchema)
async def get_conversation(conversation_id: str, user_id: str) -> ConversationSchema:
    """Get a single conversation by ID."""
    try:
        return await ConversationService().get_conversation(conversation_id, user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get conversation: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
        ) from e


@router.post("/conversation/get-all", response_model=ConversationList)
async def get_all_conversations(request: GetAllConversationsRequest) -> ConversationList:
    """Get all non-deleted conversations for a user."""
    try:
        return await ConversationService().get_all_conversations(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get all conversations: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
        ) from e


@router.put("/conversation/update", response_model=ConversationSchema)
async def update_conversation(request: ConversationUpdate) -> ConversationSchema:
    """Update a conversation's title or status."""
    try:
        return await ConversationService().update_conversation(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update conversation: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
        ) from e


@router.delete("/conversation/delete/{conversation_id}")
async def delete_conversation(conversation_id: str, user_id: str):
    """Soft-delete a conversation."""
    try:
        await ConversationService().delete_conversation(conversation_id, user_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "Conversation deleted successfully"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete conversation: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
        ) from e


@router.post("/conversation/messages", response_model=ConversationMessagesResponse)
async def get_conversation_messages(
    request: ConversationMessagesRequest,
) -> ConversationMessagesResponse:
    """Get paginated messages for a conversation."""
    try:
        return await ConversationService().get_messages(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get conversation messages: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
        ) from e
