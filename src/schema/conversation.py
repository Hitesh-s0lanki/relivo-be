"""Pydantic schemas for Conversation domain."""

from enum import IntEnum

from pydantic import Field

from src.schema.base import RelivoBaseModel


class ConversationStatus(IntEnum):
    """Conversation lifecycle status."""

    UNKNOWN = 0
    ACTIVE = 1
    ARCHIVED = 2
    CLOSED = 3
    DELETED = 4
    STREAMING = 5


class ConversationCreate(RelivoBaseModel):
    """Request body for creating a conversation."""

    user_id: str = Field(alias="userId")
    title: str | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE


class ConversationUpdate(RelivoBaseModel):
    """Request body for updating a conversation."""

    id: str
    user_id: str | None = Field(default=None, alias="userId")
    title: str | None = None
    status: ConversationStatus | None = None


class ConversationSchema(RelivoBaseModel):
    """Full conversation response model."""

    id: str
    user_id: str = Field(alias="userId")
    title: str | None = None
    status: ConversationStatus = ConversationStatus.UNKNOWN
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class ConversationList(RelivoBaseModel):
    """List of conversations response."""

    conversations: list[ConversationSchema] = Field(default_factory=list)


class GetAllConversationsRequest(RelivoBaseModel):
    """Request body for fetching all conversations for a user."""

    user_id: str = Field(alias="userId")
