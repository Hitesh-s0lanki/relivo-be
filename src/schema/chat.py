"""Pydantic schemas for Chat domain."""

from enum import IntEnum

from pydantic import Field

from src.schema.base import RelivoBaseModel


class MessageRole(IntEnum):
    """Message role."""

    USER = 1
    ASSISTANT = 2


class MessageStatus(IntEnum):
    """Message status."""

    STATUS_UNKNOWN = 0
    COMPLETED = 1
    STREAMING = 2
    CANCELLED = 3
    ERROR = 4


class AttachmentInput(RelivoBaseModel):
    """Attachment in a user message request."""

    url: str = ""
    media_type: str = Field(default="", alias="mediaType")
    title: str = ""


class UserMessageRequest(RelivoBaseModel):
    """Request body for initiating a chat message."""

    conversation_id: str = Field(default="", alias="conversationId")
    user_id: str = Field(default="", alias="userId")
    user_message: str = Field(default="", alias="userMessage")
    user_message_timestamp: int = Field(default=0, alias="userMessageTimestamp")
    attachments: list[AttachmentInput] = Field(default_factory=list)


class CancelMessageRequest(RelivoBaseModel):
    """Request body for cancelling an in-progress response."""

    response_id: str = Field(default="", alias="responseId")
    user_message_request: UserMessageRequest | None = Field(
        default=None, alias="userMessageRequest"
    )


class TextPart(RelivoBaseModel):
    """Text part of a UI message."""

    text: str = ""
    state: str = "done"


class UIMessagePart(RelivoBaseModel):
    """A single part of a UI message."""

    text: TextPart | None = None


class UIMessageMetadata(RelivoBaseModel):
    """Metadata for a UI message."""

    created_at: str = Field(default="", alias="createdAt")
    tokens: int = 0


class UIMessage(RelivoBaseModel):
    """A single UI message in the conversation."""

    id: str = ""
    role: MessageRole = MessageRole.USER
    parts: list[UIMessagePart] = Field(default_factory=list)
    metadata: UIMessageMetadata | None = None
    status: MessageStatus = MessageStatus.COMPLETED


class ConversationMessagesRequest(RelivoBaseModel):
    """Request body for getting conversation messages with pagination."""

    conversation_id: str = Field(default="", alias="conversationId")
    user_id: str = Field(default="", alias="userId")
    limit: int = 50
    offset: int = 0


class ConversationMessagesResponse(RelivoBaseModel):
    """Response body for conversation messages with pagination."""

    messages: list[UIMessage] = Field(default_factory=list)
    has_more: bool = Field(default=False, alias="hasMore")
    next_offset: int = Field(default=0, alias="nextOffset")
    count: int = 0
